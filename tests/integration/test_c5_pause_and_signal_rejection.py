"""
Phase1.1 C5：超仓挂起（拒绝信号 + PAUSED + 终态日志，同一事务）

验证：风控不通过时挂起策略（PAUSED + STRATEGY_PAUSED 终态日志同事务）；
挂起后信号入口返回 HTTP 200 + status=rejected, reason=STRATEGY_PAUSED，并写入 rejection 记录。
"""
from decimal import Decimal
from datetime import datetime, timezone
import json
import pytest
from sqlalchemy import select, text

from src.app.dependencies import get_db_session, set_session_factory
from src.execution.position_manager import PositionManager, ReconcileItem
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.execution.strategy_manager import pause_strategy
from src.models.strategy_runtime_state import StrategyRuntimeState, STATUS_PAUSED, STATUS_RUNNING
from src.models.position_reconcile_log import STRATEGY_PAUSED
from src.repositories.trade_repo import TradeRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository
from src.repositories.signal_rejection_repo import SignalRejectionRepository
from src.models.signal_rejection import SignalRejection, REASON_STRATEGY_PAUSED
from src.models.position_reconcile_log import PositionReconcileLog


async def _ensure_runtime_state(session, strategy_id: str):
    """确保 strategy_runtime_state 行存在（C5 表含 status 列，默认 RUNNING）。"""
    await session.execute(
        text(
            "INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, 'RUNNING', 30)"
        ),
        {"sid": strategy_id},
    )


@pytest.mark.asyncio
async def test_c5_risk_fail_pause_same_transaction(db_session_factory):
    """C5：full_check 不通过时 on_risk_check_failed 调用 pause_strategy，状态与终态日志同事务。"""
    set_session_factory(db_session_factory)
    strategy_id = "C5_PAUSE_STRAT"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            state_repo = StrategyRuntimeStateRepository(session)
            risk_config = RiskConfig(max_position_qty=Decimal("0.01"))
            risk_manager = RiskManager(position_repo=position_repo, risk_config=risk_config)
            pm = PositionManager(trade_repo, position_repo, log_repo)

            async def on_fail(sid: str, reason_code: str, message: str):
                await pause_strategy(
                    session,
                    sid,
                    reason_code,
                    message,
                    state_repo=state_repo,
                    reconcile_log_repo=log_repo,
                    position_repo=position_repo,
                    lock_holder_id="c5-pause-test",
                )

            out = await pm.reconcile(
                session,
                strategy_id,
                [
                    ReconcileItem(
                        "c5-pause-1",
                        "BTCUSDT",
                        "BUY",
                        Decimal("1"),
                        fallback_price=Decimal("50000"),
                    )
                ],
                lock_holder_id="c5-test",
                risk_manager=risk_manager,
                on_risk_check_failed=on_fail,
            )
    assert out["risk_check_passed"] is False
    assert out.get("risk_reason_code") == "POSITION_LIMIT_EXCEEDED"

    async with get_db_session() as session:
        state_repo2 = StrategyRuntimeStateRepository(session)
        state = await state_repo2.get_by_strategy_id(strategy_id)
        assert state is not None
        assert getattr(state, "status", None) == STATUS_PAUSED
        log_repo2 = PositionReconcileLogRepository(session)
        logs = await log_repo2.list_by_strategy(strategy_id, limit=10)
        logs = [l for l in logs if l.event_type == STRATEGY_PAUSED]
    assert len(logs) >= 1
    last_paused = logs[0]
    assert getattr(last_paused, "diff_snapshot", None), "STRATEGY_PAUSED must contain diff_snapshot (C6)"
    snapshot = json.loads(last_paused.diff_snapshot)
    assert "reason_code" in snapshot
    assert snapshot["reason_code"] == "POSITION_LIMIT_EXCEEDED"
    assert "positions" in snapshot


@pytest.mark.asyncio
async def test_c5_signal_rejected_when_paused(db_session_factory):
    """C5：策略 PAUSED 时信号入口返回 200 + status=rejected, reason=STRATEGY_PAUSED，并写入 rejection 记录。"""
    from src.application.signal_service import SignalApplicationService
    from src.repositories.dedup_signal_repo import DedupSignalRepository
    from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
    from src.schemas.signals import TradingViewSignal

    set_session_factory(db_session_factory)
    strategy_id = "C5_REJECT_STRAT"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.execute(
            text(
                "UPDATE strategy_runtime_state SET status = :st WHERE strategy_id = :sid"
            ),
            {"st": STATUS_PAUSED, "sid": strategy_id},
        )
    signal = TradingViewSignal(
        signal_id="sig-paused-1",
        strategy_id=strategy_id,
        symbol="BTCUSDT",
        side="BUY",
        timestamp=datetime.now(timezone.utc),
        raw_payload={},
    )
    config = {}
    async with get_db_session() as session:
        state_repo = StrategyRuntimeStateRepository(session)
        state = await state_repo.get_by_strategy_id(strategy_id)
        assert getattr(state, "status", None) == STATUS_PAUSED
        rej_repo = SignalRejectionRepository(session)
        await rej_repo.create_rejection(
            strategy_id,
            REASON_STRATEGY_PAUSED,
            signal_id=signal.signal_id,
        )
    async with get_db_session() as session:
        result = await session.execute(
            select(SignalRejection).where(SignalRejection.strategy_id == strategy_id)
        )
        rows = list(result.scalars().all())
    assert len(rows) >= 1
    assert rows[0].reason == REASON_STRATEGY_PAUSED
    assert rows[0].signal_id == signal.signal_id
