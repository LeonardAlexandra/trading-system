"""
PR8 执行事件集成测试：CLAIMED / ORDER_SUBMIT_* / FILLED / RETRY_SCHEDULED / FINAL_FAILED
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
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.execution.exceptions import TransientOrderError
from src.common.reason_codes import RETRY_EXHAUSTED, EXCHANGE_TRANSIENT_ERROR
from src.common.event_types import (
    CLAIMED,
    ORDER_SUBMIT_STARTED,
    ORDER_SUBMIT_OK,
    ORDER_SUBMIT_FAILED,
    RETRY_SCHEDULED as EV_RETRY_SCHEDULED,
    FINAL_FAILED,
    FILLED as EV_FILLED,
)


@pytest.fixture
def exec_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def exec_db_url(exec_tmp_path):
    return "sqlite+aiosqlite:///" + (exec_tmp_path / "exec_events.db").as_posix()


@pytest.fixture
def exec_sync_db_url(exec_tmp_path):
    return "sqlite:///" + (exec_tmp_path / "exec_events.db").as_posix()


@pytest.fixture
def exec_schema(exec_sync_db_url):
    engine = create_engine(exec_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def exec_session_factory(exec_db_url, exec_schema):
    engine = create_async_engine(exec_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_events_written_on_success_flow(exec_session_factory):
    """预置 RESERVED，execute_one 成功，断言 execution_event 至少：CLAIMED, ORDER_SUBMIT_STARTED, ORDER_SUBMIT_OK, FILLED"""
    now = datetime.now(timezone.utc)
    decision_id = "test-events-success-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-e1",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, PaperExchangeAdapter(filled=True), RiskManager())
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "filled"
    assert result.get("exchange_order_id")

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    event_types = [e.event_type for e in events]
    assert CLAIMED in event_types
    assert ORDER_SUBMIT_STARTED in event_types
    assert ORDER_SUBMIT_OK in event_types
    assert EV_FILLED in event_types
    for e in events:
        assert e.decision_id == decision_id
        assert e.id, "execution_event.id 必须由 append_event 统一生成、不可遗漏"
    ok_events = [e for e in events if e.event_type == ORDER_SUBMIT_OK or e.event_type == EV_FILLED]
    assert len(ok_events) >= 1
    assert any(e.exchange_order_id for e in ok_events)


@pytest.mark.asyncio
async def test_events_written_on_retry_flow(exec_session_factory):
    """Exchange 抛 TransientOrderError，断言：CLAIMED, ORDER_SUBMIT_STARTED, ORDER_SUBMIT_FAILED, RETRY_SCHEDULED；attempt_count、reason_code 正确"""
    config = WorkerConfig(max_attempts=3, backoff_seconds=[1, 5, 30])

    class FailingPaperAdapter(PaperExchangeAdapter):
        async def create_order(self, symbol, side, qty, client_order_id, **kwargs):
            raise TransientOrderError("simulated transient error")

    now = datetime.now(timezone.utc)
    decision_id = "test-events-retry-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-e2",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, FailingPaperAdapter(filled=True), RiskManager(), config=config)
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "retry_scheduled"
    assert result.get("reason_code") == "RETRY_SCHEDULED"
    assert result.get("attempt_count") == 1

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    event_types = [e.event_type for e in events]
    assert CLAIMED in event_types
    assert ORDER_SUBMIT_STARTED in event_types
    assert ORDER_SUBMIT_FAILED in event_types
    assert EV_RETRY_SCHEDULED in event_types
    failed_ev = next(e for e in events if e.event_type == ORDER_SUBMIT_FAILED)
    assert failed_ev.reason_code == EXCHANGE_TRANSIENT_ERROR
    assert failed_ev.attempt_count == 1
    retry_ev = next(e for e in events if e.event_type == EV_RETRY_SCHEDULED)
    assert retry_ev.reason_code == "RETRY_SCHEDULED"
    assert retry_ev.attempt_count == 1
    for e in events:
        assert e.id, "execution_event.id 必须由 append_event 统一生成、不可遗漏"


@pytest.mark.asyncio
async def test_events_retry_flow_audit_sample_printed(exec_session_factory):
    """Retry flow：打印事件序列，验收 ORDER_SUBMIT_FAILED.reason_code=EXCHANGE_TRANSIENT_ERROR 与 RETRY_SCHEDULED.reason_code=RETRY_SCHEDULED"""
    config = WorkerConfig(max_attempts=3, backoff_seconds=[1, 5, 30])

    class FailingPaperAdapter(PaperExchangeAdapter):
        async def create_order(self, symbol, side, qty, client_order_id, **kwargs):
            raise TransientOrderError("simulated transient error")

    now = datetime.now(timezone.utc)
    decision_id = "audit-retry-sample-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-audit-retry",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, FailingPaperAdapter(filled=True), RiskManager(), config=config)
        await engine.execute_one(decision_id)
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    print("\n=== Retry flow 数据库事件样例 (decision_id=%s, 按 created_at 顺序) ===" % decision_id)
    for e in events:
        print(
            "  event_type=%r reason_code=%r exchange_order_id=%r attempt_count=%s"
            % (e.event_type, e.reason_code, e.exchange_order_id, e.attempt_count)
        )
    failed_ev = next((e for e in events if e.event_type == ORDER_SUBMIT_FAILED), None)
    retry_ev = next((e for e in events if e.event_type == EV_RETRY_SCHEDULED), None)
    assert failed_ev is not None and failed_ev.reason_code == EXCHANGE_TRANSIENT_ERROR
    assert retry_ev is not None and retry_ev.reason_code == "RETRY_SCHEDULED"


@pytest.mark.asyncio
async def test_events_audit_sample_printed(exec_session_factory):
    """与 success_flow 相同，仅用于验收时打印数据库事件样例（不含敏感信息）"""
    now = datetime.now(timezone.utc)
    decision_id = "audit-sample-001"
    async with get_db_session() as session:
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
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, PaperExchangeAdapter(filled=True), RiskManager())
        await engine.execute_one(decision_id)
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    print("\n=== 数据库事件样例 (decision_id=%s, 按 created_at 顺序) ===" % decision_id)
    for e in events:
        print(
            "  event_type=%r reason_code=%r exchange_order_id=%r attempt_count=%s created_at=%s"
            % (e.event_type, e.reason_code, e.exchange_order_id, e.attempt_count, e.created_at)
        )
    # P2-1：连续事件 created_at 应自然递增（不再完全相同）
    for i in range(1, len(events)):
        assert events[i].created_at >= events[i - 1].created_at, "created_at 应递增"
    assert len(events) >= 4
