"""
Phase1.1 C6：STRATEGY_PAUSED 终态日志（含差异快照）

验证：每次 STRATEGY_PAUSED 写入都包含非空、可解析的差异快照；字段与文档一致；不包含敏感数据。
"""
from decimal import Decimal
import json
import pytest
from sqlalchemy import text

from src.app.dependencies import get_db_session, set_session_factory
from src.execution.position_manager import PositionManager, ReconcileItem
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.execution.strategy_manager import (
    pause_strategy,
    DIFF_SNAPSHOT_REQUIRED_KEYS,
    DIFF_SNAPSHOT_MAX_MESSAGE_LEN,
)
from src.models.position_reconcile_log import STRATEGY_PAUSED
from src.repositories.trade_repo import TradeRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository

# C6：禁止出现在差异快照中的敏感字段名（与 Phase1.1 约定一致）
SENSITIVE_KEYS = frozenset({
    "account_id", "balance", "webhook_secret", "raw_payload", "signature",
    "password", "token", "api_key", "secret",
})


async def _ensure_runtime_state(session, strategy_id: str):
    await session.execute(
        text(
            "INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, 'RUNNING', 30)"
        ),
        {"sid": strategy_id},
    )


@pytest.mark.asyncio
async def test_c6_strategy_paused_has_non_empty_parseable_diff_snapshot(db_session_factory):
    """C6：每次 STRATEGY_PAUSED 写入都包含非空差异快照，且可解析、字段与文档一致。"""
    set_session_factory(db_session_factory)
    strategy_id = "C6_DIFF_STRAT"
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
                    session, sid, reason_code, message,
                    state_repo=state_repo,
                    reconcile_log_repo=log_repo,
                    position_repo=position_repo,
                    lock_holder_id="c6-test",
                )

            await pm.reconcile(
                session,
                strategy_id,
                [ReconcileItem("c6-1", "BTCUSDT", "BUY", Decimal("1"), fallback_price=Decimal("50000"))],
                lock_holder_id="c6-test",
                risk_manager=risk_manager,
                on_risk_check_failed=on_fail,
            )
    async with get_db_session() as session:
        log_repo2 = PositionReconcileLogRepository(session)
        logs = await log_repo2.list_by_strategy(strategy_id, limit=10)
        paused_logs = [l for l in logs if l.event_type == STRATEGY_PAUSED]
    assert len(paused_logs) >= 1, "STRATEGY_PAUSED log must exist"
    log = paused_logs[0]
    assert getattr(log, "diff_snapshot", None), "diff_snapshot must be non-empty"
    raw = log.diff_snapshot.strip()
    assert len(raw) > 0, "C6: diff_snapshot must be non-empty"
    data = json.loads(raw)
    assert isinstance(data, dict), "C6: diff_snapshot must be parseable JSON object"
    for key in DIFF_SNAPSHOT_REQUIRED_KEYS:
        assert key in data, f"C6: diff_snapshot must contain required key {key!r}"
    assert isinstance(data.get("positions"), list), "C6: positions must be list"
    assert len(data["message"]) <= DIFF_SNAPSHOT_MAX_MESSAGE_LEN, "C6: message length bounded"


@pytest.mark.asyncio
async def test_c6_diff_snapshot_contains_no_sensitive_keys(db_session_factory):
    """C6：差异快照不包含敏感数据（账户、余额、secret 等）。"""
    set_session_factory(db_session_factory)
    strategy_id = "C6_NO_SENSITIVE"
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
                    session, sid, reason_code, message,
                    state_repo=state_repo,
                    reconcile_log_repo=log_repo,
                    position_repo=position_repo,
                    lock_holder_id="c6-nosense",
                )

            await pm.reconcile(
                session,
                strategy_id,
                [ReconcileItem("c6-2", "ETHUSDT", "BUY", Decimal("0.5"), fallback_price=Decimal("3000"))],
                lock_holder_id="c6-nosense",
                risk_manager=risk_manager,
                on_risk_check_failed=on_fail,
            )
    async with get_db_session() as session:
        log_repo2 = PositionReconcileLogRepository(session)
        logs = await log_repo2.list_by_strategy(strategy_id, limit=10)
        paused_logs = [l for l in logs if l.event_type == STRATEGY_PAUSED]
    assert len(paused_logs) >= 1
    data = json.loads(paused_logs[0].diff_snapshot)

    def check_no_sensitive(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k.lower() not in {s.lower() for s in SENSITIVE_KEYS}, (
                    f"C6: diff_snapshot must not contain sensitive key {k!r} at {path}"
                )
                check_no_sensitive(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                check_no_sensitive(v, f"{path}[{i}]")

    check_no_sensitive(data)
