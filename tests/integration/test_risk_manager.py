"""
PR9 风控集成测试：仓位限制、冷却、同向抑制、RISK_* 事件
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models
from src.models.decision_order_map_status import RESERVED, FILLED, FAILED
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.risk_state_repository import RiskStateRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.common.reason_codes import (
    POSITION_LIMIT_EXCEEDED,
    COOLDOWN_ACTIVE,
    DUPLICATE_DIRECTION,
)
from src.common.event_types import (
    RISK_CHECK_STARTED,
    RISK_PASSED,
    RISK_REJECTED,
    ORDER_SUBMIT_STARTED,
    ORDER_SUBMIT_OK,
    FILLED as EV_FILLED,
)


@pytest.fixture
def risk_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def risk_db_url(risk_tmp_path):
    return "sqlite+aiosqlite:///" + (risk_tmp_path / "risk.db").as_posix()


@pytest.fixture
def risk_sync_db_url(risk_tmp_path):
    return "sqlite:///" + (risk_tmp_path / "risk.db").as_posix()


@pytest.fixture
def risk_schema(risk_sync_db_url):
    engine = create_engine(risk_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def risk_session_factory(risk_db_url, risk_schema):
    engine = create_async_engine(risk_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


def _make_engine_with_risk(
    session,
    risk_config: RiskConfig,
    position_repo=None,
    risk_state_repo=None,
):
    dom_repo = DecisionOrderMapRepository(session)
    position_repo = position_repo or PositionRepository(session)
    risk_state_repo = risk_state_repo or RiskStateRepository(session)
    risk_manager = RiskManager(
        position_repo=position_repo,
        dom_repo=dom_repo,
        risk_state_repo=risk_state_repo,
        risk_config=risk_config,
    )
    engine = ExecutionEngine(
        dom_repo,
        PaperExchangeAdapter(filled=True),
        risk_manager,
        position_repo=position_repo,
        risk_state_repo=risk_state_repo,
    )
    return engine


@pytest.mark.asyncio
async def test_risk_rejects_when_position_limit_exceeded(risk_session_factory):
    """预置 positions quantity=1.5，max_position_qty=2.0，decision qty=1.0 -> FAILED, POSITION_LIMIT_EXCEEDED"""
    now = datetime.now(timezone.utc)
    decision_id = "test-risk-position-limit-001"
    risk_config = RiskConfig(max_position_qty=Decimal("2.0"))
    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        await pos_repo.upsert("strat-1", "BTCUSDT", Decimal("1.5"), side="LONG")
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-r1",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1.0"),
        )
    async with get_db_session() as session:
        engine = _make_engine_with_risk(session, risk_config)
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "failed"
    assert result.get("reason_code") == POSITION_LIMIT_EXCEEDED
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        row = await repo.get_by_decision_id(decision_id)
        assert row.status == FAILED
        assert row.last_error == POSITION_LIMIT_EXCEEDED
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    event_types = [e.event_type for e in events]
    assert RISK_CHECK_STARTED in event_types
    assert RISK_REJECTED in event_types
    rejected = next(e for e in events if e.event_type == RISK_REJECTED)
    assert rejected.reason_code == POSITION_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_risk_rejects_on_cooldown(risk_session_factory):
    """cooldown_seconds=60，第一次 FILLED 后，第二次同 (strategy_id,symbol,side) 立即执行应拒绝 COOLDOWN_ACTIVE"""
    now = datetime.now(timezone.utc)
    risk_config = RiskConfig(cooldown_seconds=60.0)
    decision_id_1 = "test-risk-cooldown-001"
    decision_id_2 = "test-risk-cooldown-002"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id_1,
            signal_id="sig-c1",
            strategy_id="strat-cooldown",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        engine = _make_engine_with_risk(session, risk_config)
        result1 = await engine.execute_one(decision_id_1)
    assert result1.get("status") == "filled"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id_2,
            signal_id="sig-c2",
            strategy_id="strat-cooldown",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        engine = _make_engine_with_risk(session, risk_config)
        result2 = await engine.execute_one(decision_id_2)
    assert result2.get("status") == "failed"
    assert result2.get("reason_code") == COOLDOWN_ACTIVE
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id_2)
    event_types = [e.event_type for e in events]
    assert RISK_CHECK_STARTED in event_types
    assert RISK_REJECTED in event_types
    rejected = next(e for e in events if e.event_type == RISK_REJECTED)
    assert rejected.reason_code == COOLDOWN_ACTIVE


@pytest.mark.asyncio
async def test_risk_rejects_duplicate_direction_window(risk_session_factory):
    """same_direction_dedupe_window_seconds=300，窗口内已有 FILLED 同向记录，新 decision 拒绝 DUPLICATE_DIRECTION"""
    now = datetime.now(timezone.utc)
    risk_config = RiskConfig(same_direction_dedupe_window_seconds=300.0)
    decision_id_1 = "test-risk-dedup-001"
    decision_id_2 = "test-risk-dedup-002"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id_1,
            signal_id="sig-d1",
            strategy_id="strat-dedup",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        engine = _make_engine_with_risk(session, risk_config)
        result1 = await engine.execute_one(decision_id_1)
    assert result1.get("status") == "filled"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id_2,
            signal_id="sig-d2",
            strategy_id="strat-dedup",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        engine = _make_engine_with_risk(session, risk_config)
        result2 = await engine.execute_one(decision_id_2)
    assert result2.get("status") == "failed"
    assert result2.get("reason_code") == DUPLICATE_DIRECTION
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id_2)
    event_types = [e.event_type for e in events]
    assert RISK_CHECK_STARTED in event_types
    assert RISK_REJECTED in event_types
    rejected = next(e for e in events if e.event_type == RISK_REJECTED)
    assert rejected.reason_code == DUPLICATE_DIRECTION


@pytest.mark.asyncio
async def test_risk_passed_writes_events(risk_session_factory):
    """正常 decision 执行，events 至少包含 RISK_CHECK_STARTED, RISK_PASSED，且仍有 ORDER_SUBMIT_* 与 FILLED"""
    now = datetime.now(timezone.utc)
    decision_id = "test-risk-passed-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-p1",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        engine = _make_engine_with_risk(session, RiskConfig())
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "filled"
    assert result.get("exchange_order_id")
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    event_types = [e.event_type for e in events]
    assert RISK_CHECK_STARTED in event_types
    assert RISK_PASSED in event_types
    assert ORDER_SUBMIT_STARTED in event_types
    assert ORDER_SUBMIT_OK in event_types
    assert EV_FILLED in event_types


@pytest.mark.asyncio
async def test_risk_rejected_audit_sample_printed(risk_session_factory):
    """风控拒绝时打印事件样例（用于验收材料）"""
    now = datetime.now(timezone.utc)
    decision_id = "audit-risk-rejected-001"
    risk_config = RiskConfig(max_position_qty=Decimal("0.5"))
    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        await pos_repo.upsert("strat-1", "BTCUSDT", Decimal("1"), side="LONG")
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-audit",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        engine = _make_engine_with_risk(session, risk_config)
        await engine.execute_one(decision_id)
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    print("\n=== 风控拒绝事件样例 (decision_id=%s, 按 created_at 顺序) ===" % decision_id)
    for e in events:
        print(
            "  event_type=%r reason_code=%r message=%r created_at=%s"
            % (e.event_type, e.reason_code, e.message, e.created_at)
        )
    assert any(e.event_type == RISK_REJECTED and e.reason_code == POSITION_LIMIT_EXCEEDED for e in events)
