"""
Phase1.1 C7：STRATEGY_RESUMED 终态日志（恢复成功时的终态记录）

验证：B1 恢复成功时必写 STRATEGY_RESUMED；日志与状态更新同事务；含恢复时间（created_at）、
触发方式、可选恢复前挂起原因（来自最近 STRATEGY_PAUSED）。
"""
from decimal import Decimal
import json
import pytest
from sqlalchemy import text

from src.app.dependencies import get_db_session, set_session_factory
from src.execution.position_manager import PositionManager, ReconcileItem
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.execution.strategy_manager import pause_strategy, resume_strategy
from src.models.strategy_runtime_state import STATUS_PAUSED, STATUS_RUNNING
from src.models.position_reconcile_log import STRATEGY_PAUSED, STRATEGY_RESUMED
from src.repositories.trade_repo import TradeRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository


async def _ensure_runtime_state(session, strategy_id: str, status: str = "RUNNING"):
    await session.execute(
        text(
            "INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, :st, 30)"
        ),
        {"sid": strategy_id, "st": status},
    )


@pytest.mark.asyncio
async def test_c7_resume_success_writes_strategy_resumed_same_transaction(db_session_factory):
    """C7：B1 恢复成功时 DB 中存在 STRATEGY_RESUMED 记录，与状态更新同事务。"""
    set_session_factory(db_session_factory)
    strategy_id = "C7_STRAT"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id, status=STATUS_PAUSED)
    async with get_db_session() as session:
        async with session.begin():
            state_repo = StrategyRuntimeStateRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_manager = RiskManager(position_repo=position_repo, risk_config=RiskConfig())
            outcome, _ = await resume_strategy(
                session,
                strategy_id,
                state_repo=state_repo,
                position_repo=position_repo,
                reconcile_log_repo=log_repo,
                risk_manager=risk_manager,
            )
    assert outcome == "ok"
    async with get_db_session() as session:
        logs = await PositionReconcileLogRepository(session).list_by_strategy(strategy_id, limit=10)
        resumed = [l for l in logs if l.event_type == STRATEGY_RESUMED]
    assert len(resumed) >= 1
    row = resumed[0]
    assert getattr(row, "strategy_id", None) == strategy_id
    assert getattr(row, "created_at", None) is not None


@pytest.mark.asyncio
async def test_c7_resumed_log_contains_trigger_and_previous_paused_reason(db_session_factory):
    """C7：STRATEGY_RESUMED 的 diff_snapshot 含 trigger、previous_status，且有 PAUSED 时含恢复前挂起原因。"""
    set_session_factory(db_session_factory)
    strategy_id = "C7_WITH_PAUSED"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id, status=STATUS_RUNNING)
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
                    session, sid, reason_code, message,
                    state_repo=state_repo,
                    reconcile_log_repo=log_repo,
                    position_repo=position_repo,
                    lock_holder_id="c7-pause",
                )

            await pm.reconcile(
                session,
                strategy_id,
                [ReconcileItem("c7-1", "BTCUSDT", "BUY", Decimal("1"), fallback_price=Decimal("50000"))],
                lock_holder_id="c7-pause",
                risk_manager=risk_manager,
                on_risk_check_failed=on_fail,
            )
    async with get_db_session() as session:
        async with session.begin():
            state_repo = StrategyRuntimeStateRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_config = RiskConfig()
            risk_manager = RiskManager(position_repo=position_repo, risk_config=risk_config)
            outcome, _ = await resume_strategy(
                session,
                strategy_id,
                state_repo=state_repo,
                position_repo=position_repo,
                reconcile_log_repo=log_repo,
                risk_manager=risk_manager,
            )
    assert outcome == "ok"
    async with get_db_session() as session:
        logs = await PositionReconcileLogRepository(session).list_by_strategy(strategy_id, limit=10)
        resumed = [l for l in logs if l.event_type == STRATEGY_RESUMED]
    assert len(resumed) >= 1
    data = json.loads(resumed[0].diff_snapshot)
    assert data.get("trigger") == "API"
    assert data.get("previous_status") == STATUS_PAUSED
    assert "previous_paused_reason_code" in data
    assert data.get("previous_paused_reason_code") == "POSITION_LIMIT_EXCEEDED"
