"""
PR6 执行层集成测试：拉取 RESERVED、抢占、落库 FILLED/FAILED、重试退避
"""
import asyncio
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
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.execution.exceptions import TransientOrderError
from src.common.reason_codes import (
    SKIPPED_ALREADY_CLAIMED,
    RETRY_EXHAUSTED,
)


@pytest.fixture
def exec_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def exec_db_url(exec_tmp_path):
    return "sqlite+aiosqlite:///" + (exec_tmp_path / "exec.db").as_posix()


@pytest.fixture
def exec_sync_db_url(exec_tmp_path):
    return "sqlite:///" + (exec_tmp_path / "exec.db").as_posix()


@pytest.fixture
def exec_schema(exec_sync_db_url):
    """初始化执行测试用 DB schema（与 webhook 测试一致，create_all）"""
    engine = create_engine(exec_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def exec_session_factory(exec_db_url, exec_schema):
    """为执行测试设置 SessionFactory（不依赖 FastAPI 生命周期）"""
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
async def test_worker_pulls_reserved_and_marks_filled(exec_session_factory, exec_tmp_path):
    """预置一条 RESERVED，执行一次 execute_one，断言 status=FILLED，exchange_order_id 已写入"""
    now = datetime.now(timezone.utc)
    decision_id = "test-decision-filled-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-1",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    # 新 session 执行
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, PaperExchangeAdapter(filled=True), RiskManager())
        result = await engine.execute_one(decision_id)
    assert result.get("decision_id") == decision_id
    assert result.get("status") == "filled"
    assert result.get("exchange_order_id")
    # 校验 DB
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        row = await repo.get_by_decision_id(decision_id)
        assert row is not None
        assert row.status == FILLED
        assert row.exchange_order_id is not None


@pytest.mark.asyncio
async def test_worker_concurrent_claim_is_idempotent(exec_session_factory):
    """同一 decision_id 并发调用 execute_one 两次，仅一次成功处理，另一次 skipped"""
    now = datetime.now(timezone.utc)
    decision_id = "test-decision-concurrent-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-2",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    exchange = PaperExchangeAdapter(filled=True)
    risk = RiskManager()

    async def run_one():
        async with get_db_session() as session:
            dom_repo = DecisionOrderMapRepository(session)
            engine = ExecutionEngine(dom_repo, exchange, risk)
            return await engine.execute_one(decision_id)

    r1, r2 = await asyncio.gather(run_one(), run_one())
    statuses = [r1.get("status"), r2.get("status")]
    assert "filled" in statuses
    assert "skipped" in statuses
    for r in (r1, r2):
        assert "decision_id" in r
        assert r.get("decision_id") == decision_id
    skipped_one = r1 if r1.get("status") == "skipped" else r2
    assert skipped_one.get("reason_code") == SKIPPED_ALREADY_CLAIMED
    # DB 仅一条且为 FILLED
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        row = await repo.get_by_decision_id(decision_id)
        assert row.status == FILLED
        assert row.exchange_order_id is not None


@pytest.mark.asyncio
async def test_retry_backoff_on_transient_error(exec_session_factory):
    """ExchangeAdapter 抛 TransientOrderError：首次 RESERVED+attempt_count=1+next_run_at；达到最大次数后 FAILED(reason_code=RETRY_EXHAUSTED)"""
    config = WorkerConfig(max_attempts=3, backoff_seconds=[1, 5, 30])

    class FailingPaperAdapter(PaperExchangeAdapter):
        """始终抛 TransientOrderError 的 Adapter"""
        async def create_order(self, symbol, side, qty, client_order_id, **kwargs):
            raise TransientOrderError("simulated transient error")

    now = datetime.now(timezone.utc)
    decision_id = "test-decision-retry-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-3",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )

    exchange = FailingPaperAdapter(filled=True)
    risk = RiskManager()

    for attempt in range(1, config.max_attempts + 1):
        async with get_db_session() as session:
            dom_repo = DecisionOrderMapRepository(session)
            engine = ExecutionEngine(dom_repo, exchange, risk, config=config)
            result = await engine.execute_one(decision_id)
        assert result.get("decision_id") == decision_id
        async with get_db_session() as session:
            repo = DecisionOrderMapRepository(session)
            row = await repo.get_by_decision_id(decision_id)
            assert row is not None
            if attempt < config.max_attempts:
                assert row.status == RESERVED
                assert row.attempt_count == attempt
                assert row.next_run_at is not None
                # 将 next_run_at 置为过去以便下一轮被拉取
                row.next_run_at = datetime.now(timezone.utc)
                await session.flush()
            else:
                assert row.status == FAILED
                assert row.attempt_count == config.max_attempts
                assert row.last_error == RETRY_EXHAUSTED
                assert result.get("reason_code") == RETRY_EXHAUSTED


@pytest.mark.asyncio
async def test_execute_one_return_contract_has_decision_id_and_reason_code(exec_session_factory):
    """PR7：execute_one 返回 dict 必含 decision_id；skipped/failed 含 reason_code（来自统一常量）"""
    # 成功：必含 decision_id、status
    decision_id = "test-contract-success-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-c",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=datetime.now(timezone.utc),
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, PaperExchangeAdapter(filled=True), RiskManager())
        result = await engine.execute_one(decision_id)
    assert "decision_id" in result
    assert result["decision_id"] == decision_id
    assert result.get("status") == "filled"

    # 跳过：同一 decision 再执行一次应 skipped，含 reason_code（新 session）
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine2 = ExecutionEngine(dom_repo, PaperExchangeAdapter(filled=True), RiskManager())
        result2 = await engine2.execute_one(decision_id)
    assert "decision_id" in result2
    assert result2["decision_id"] == decision_id
    assert result2.get("status") == "skipped"
    assert result2.get("reason_code") == SKIPPED_ALREADY_CLAIMED
