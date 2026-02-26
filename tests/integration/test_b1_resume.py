"""
Phase1.1 B1：POST /strategy/{id}/resume（强校验恢复 + diff 标准公式）
D4/D5：强校验失败 400+diff，强校验成功 2xx+STRATEGY_RESUMED 落库。
"""
from decimal import Decimal
import pytest
from sqlalchemy import text

from src.app.dependencies import get_db_session, set_session_factory
from src.execution.strategy_manager import (
    resume_strategy,
    RESUME_CHECK_FAILED_CODE,
    FIELD_STATE_IS_PAUSED,
    FIELD_RISK_PASSED,
)
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.models.strategy_runtime_state import STATUS_PAUSED, STATUS_RUNNING
from src.models.position_reconcile_log import STRATEGY_RESUMED
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository


async def _ensure_runtime_state(session, strategy_id: str, status: str = "RUNNING"):
    await session.execute(
        text(
            "INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, :st, 30)"
        ),
        {"sid": strategy_id, "st": status},
    )


@pytest.mark.asyncio
async def test_b1_resume_not_found(db_session_factory):
    """B1：不存在的 strategy id 返回 not_found（对应 404）。"""
    set_session_factory(db_session_factory)
    async with get_db_session() as session:
        async with session.begin():
            state_repo = StrategyRuntimeStateRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_manager = RiskManager(position_repo=position_repo, risk_config=RiskConfig())
            outcome, diff = await resume_strategy(
                session,
                "NONEXISTENT_STRAT",
                state_repo=state_repo,
                position_repo=position_repo,
                reconcile_log_repo=log_repo,
                risk_manager=risk_manager,
            )
    assert outcome == "not_found"
    assert diff is None


@pytest.mark.asyncio
async def test_b1_resume_check_failed_400_diff(db_session_factory):
    """B1/D4：强校验不通过时返回 check_failed，diff 符合标准公式（code, checks, snapshot）。"""
    set_session_factory(db_session_factory)
    strategy_id = "B1_FAIL_STRAT"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id, status=STATUS_RUNNING)
    async with get_db_session() as session:
        async with session.begin():
            state_repo = StrategyRuntimeStateRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_config = RiskConfig(max_position_qty=Decimal("0.01"))
            risk_manager = RiskManager(position_repo=position_repo, risk_config=risk_config)
            outcome, diff = await resume_strategy(
                session,
                strategy_id,
                state_repo=state_repo,
                position_repo=position_repo,
                reconcile_log_repo=log_repo,
                risk_manager=risk_manager,
                risk_config_override=risk_config,
            )
    assert outcome == "check_failed"
    assert diff is not None
    assert diff.get("code") == RESUME_CHECK_FAILED_CODE
    assert "checks" in diff
    assert isinstance(diff["checks"], list)
    assert "snapshot" in diff
    assert diff["snapshot"].get("strategy_id") == strategy_id
    assert diff["snapshot"].get("status") == STATUS_RUNNING
    fields = [c["field"] for c in diff["checks"]]
    assert FIELD_STATE_IS_PAUSED in fields
    assert FIELD_RISK_PASSED in fields
    assert all("expected" in c and "actual" in c and "pass" in c for c in diff["checks"])


@pytest.mark.asyncio
async def test_b1_resume_paused_but_risk_fails_400(db_session_factory):
    """B1/D4：策略为 PAUSED 但风控 full_check 不通过时返回 check_failed 及 diff。"""
    set_session_factory(db_session_factory)
    strategy_id = "B1_PAUSED_RISK_FAIL"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id, status=STATUS_PAUSED)
    async with get_db_session() as session:
        async with session.begin():
            pos_repo = PositionRepository(session)
            await pos_repo.upsert(strategy_id, "BTCUSDT", Decimal("100"), side="LONG")
    async with get_db_session() as session:
        async with session.begin():
            state_repo = StrategyRuntimeStateRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_config = RiskConfig(max_position_qty=Decimal("1"))
            risk_manager = RiskManager(position_repo=position_repo, risk_config=risk_config)
            outcome, diff = await resume_strategy(
                session,
                strategy_id,
                state_repo=state_repo,
                position_repo=position_repo,
                reconcile_log_repo=log_repo,
                risk_manager=risk_manager,
                risk_config_override=risk_config,
            )
    assert outcome == "check_failed"
    assert diff is not None
    assert diff["code"] == RESUME_CHECK_FAILED_CODE
    risk_checks = [c for c in diff["checks"] if c["field"] == FIELD_RISK_PASSED]
    assert len(risk_checks) == 1 and risk_checks[0]["pass"] is False


@pytest.mark.asyncio
async def test_b1_resume_success_2xx_and_strategy_resumed(db_session_factory):
    """B1/D5：强校验通过时恢复成功，状态变为 RUNNING，STRATEGY_RESUMED 落库（同事务）。"""
    set_session_factory(db_session_factory)
    strategy_id = "B1_OK_STRAT"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id, status=STATUS_PAUSED)
    async with get_db_session() as session:
        async with session.begin():
            state_repo = StrategyRuntimeStateRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_config = RiskConfig()
            risk_manager = RiskManager(position_repo=position_repo, risk_config=risk_config)
            outcome, diff = await resume_strategy(
                session,
                strategy_id,
                state_repo=state_repo,
                position_repo=position_repo,
                reconcile_log_repo=log_repo,
                risk_manager=risk_manager,
                risk_config_override=risk_config,
            )
    assert outcome == "ok"
    assert diff is None
    async with get_db_session() as session:
        state = await StrategyRuntimeStateRepository(session).get_by_strategy_id(strategy_id)
        assert state is not None
        assert getattr(state, "status", None) == STATUS_RUNNING
        logs = await PositionReconcileLogRepository(session).list_by_strategy(strategy_id, limit=5)
        resumed = [l for l in logs if l.event_type == STRATEGY_RESUMED]
    assert len(resumed) >= 1, "STRATEGY_RESUMED must be written (C7)"
