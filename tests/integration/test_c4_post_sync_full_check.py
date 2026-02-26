"""
Phase1.1 C4：对账/EXTERNAL_SYNC 同步后 RiskManager 全量检查

验证：同步完成后必触发 full_check；使用同步后最新数据；不通过时衔接到 on_risk_check_failed（C5）。
"""
from decimal import Decimal
import pytest
from sqlalchemy import text

from src.app.dependencies import get_db_session, set_session_factory
from src.execution.position_manager import PositionManager, ReconcileItem
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.repositories.trade_repo import TradeRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository


async def _ensure_runtime_state(session, strategy_id: str):
    return await session.execute(
        text(
            "INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, lock_ttl_seconds) VALUES (:sid, 30)"
        ),
        {"sid": strategy_id},
    )


@pytest.mark.asyncio
async def test_c4_full_check_called_after_reconcile_and_uses_sync_data(db_session_factory):
    """C4-01/C4-02：传入 risk_manager 时，同步完成后必调用 full_check，且使用同步后最新数据（同 session position_repo）。"""
    set_session_factory(db_session_factory)
    strategy_id = "C4_STRAT"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.commit()
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_manager = RiskManager(position_repo=position_repo, risk_config=RiskConfig(max_position_qty=Decimal("1000")))
            pm = PositionManager(trade_repo, position_repo, log_repo)
            out = await pm.reconcile(
                session,
                strategy_id,
                [ReconcileItem("c4-1", "BTCUSDT", "BUY", Decimal("0.1"), fallback_price=Decimal("50000"))],
                lock_holder_id="c4-test",
                risk_manager=risk_manager,
            )
    assert out["ok"] is True
    assert out["synced"] == 1
    assert "risk_check_passed" in out
    assert out["risk_check_passed"] is True
    assert out.get("risk_reason_code") is None


@pytest.mark.asyncio
async def test_c4_full_check_fails_then_on_risk_check_failed_called(db_session_factory):
    """C4-03：full_check 不通过时调用 on_risk_check_failed（C5 衔接），且返回 risk_check_passed=False。"""
    set_session_factory(db_session_factory)
    strategy_id = "C4_STRAT_FAIL"
    called = []

    async def on_fail(sid: str, reason_code: str, message: str):
        called.append((sid, reason_code, message))

    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.commit()
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_config = RiskConfig(max_position_qty=Decimal("0.01"))
            risk_manager = RiskManager(position_repo=position_repo, risk_config=risk_config)
            pm = PositionManager(trade_repo, position_repo, log_repo)
            out = await pm.reconcile(
                session,
                strategy_id,
                [ReconcileItem("c4-fail-1", "BTCUSDT", "BUY", Decimal("1"), fallback_price=Decimal("50000"))],
                lock_holder_id="c4-test",
                risk_manager=risk_manager,
                on_risk_check_failed=on_fail,
            )
    assert out["risk_check_passed"] is False
    assert out.get("risk_reason_code") == "POSITION_LIMIT_EXCEEDED"
    assert len(called) == 1
    assert called[0][0] == strategy_id
    assert called[0][1] == "POSITION_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_c4_risk_manager_required_raises(db_session_factory):
    """C4-01 封版：risk_manager 缺失时必须显式失败，不得静默跳过 full_check。"""
    set_session_factory(db_session_factory)
    strategy_id = "C4_NO_RM"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.commit()
    async with get_db_session() as session:
        async with session.begin():
            pm = PositionManager(
                TradeRepository(session),
                PositionRepository(session),
                PositionReconcileLogRepository(session),
            )
            with pytest.raises(ValueError) as exc_info:
                await pm.reconcile(
                    session,
                    strategy_id,
                    [ReconcileItem("x", "BTCUSDT", "BUY", Decimal("1"), fallback_price=Decimal("50000"))],
                    lock_holder_id="c4-test",
                    risk_manager=None,
                )
    assert "C4-01" in str(exc_info.value)
    assert "risk_manager" in str(exc_info.value).lower()
    assert "must not be skipped" in str(exc_info.value).lower() or "required" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_c4_full_check_reads_sync_after_data_same_transaction_no_commit(db_session_factory):
    """C4-02 最小复现：同一事务内同步写入后 full_check 读到最新持仓（无需 commit）。"""
    set_session_factory(db_session_factory)
    strategy_id = "C4_SAME_TXN"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.commit()
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_config = RiskConfig(max_position_qty=Decimal("5"))
            risk_manager = RiskManager(position_repo=position_repo, risk_config=risk_config)
            pm = PositionManager(trade_repo, position_repo, log_repo)
            out = await pm.reconcile(
                session,
                strategy_id,
                [ReconcileItem("c4-txn-1", "BTCUSDT", "BUY", Decimal("10"), fallback_price=Decimal("50000"))],
                lock_holder_id="c4-test",
                risk_manager=risk_manager,
            )
    assert out["synced"] == 1
    assert out["risk_check_passed"] is False
    assert out.get("risk_reason_code") == "POSITION_LIMIT_EXCEEDED"
