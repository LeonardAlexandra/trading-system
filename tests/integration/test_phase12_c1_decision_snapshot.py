"""
Phase1.2 C1：决策输入快照集成测试（同事务写入 + 写入失败策略）
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401 - ensure all models registered
from src.models.decision_order_map_status import RESERVED, FILLED, FAILED
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager


@pytest.fixture
def c1_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def c1_db_url(c1_tmp_path):
    return "sqlite+aiosqlite:///" + (c1_tmp_path / "c1.db").as_posix()


@pytest.fixture
def c1_sync_db_url(c1_tmp_path):
    return "sqlite:///" + (c1_tmp_path / "c1.db").as_posix()


@pytest.fixture
def c1_schema(c1_sync_db_url):
    engine = create_engine(c1_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def c1_session_factory(c1_db_url, c1_schema):
    engine = create_async_engine(c1_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_written_on_success_flow(c1_session_factory):
    """正常路径：execute_one 成功后 DB 中有一条 decision_snapshot，decision_id 一致，四块完整。"""
    now = datetime.now(timezone.utc)
    decision_id = "c1-happy-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-c1",
            strategy_id="strat-c1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        snapshot_repo = DecisionSnapshotRepository(session)
        alert_calls = []

        def _alert(did: str, sid: str, reason: str) -> None:
            alert_calls.append((did, sid, reason))

        engine = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            snapshot_repo=snapshot_repo,
            alert_callback=_alert,
        )
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "filled"
    assert len(alert_calls) == 0

    async with get_db_session() as session:
        snap_repo = DecisionSnapshotRepository(session)
        row = await snap_repo.get_by_decision_id(decision_id)
    assert row is not None
    assert row.decision_id == decision_id
    assert row.strategy_id == "strat-c1"
    assert "signal_id" in row.signal_state and row.signal_state.get("symbol") == "BTCUSDT"
    assert "allowed" in row.risk_check_result
    assert "decision_id" in row.decision_result


@pytest.mark.asyncio
async def test_save_failure_rejects_decision_and_triggers_alert(c1_session_factory):
    """写入失败策略：mock save 抛异常 → ExecutionEngine 未调用 create_order，返回 failed，触发 alert，无 trade。"""
    now = datetime.now(timezone.utc)
    decision_id = "c1-fail-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-fail",
            strategy_id="strat-fail",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )

    create_order_called = []

    class SpyAdapter(PaperExchangeAdapter):
        async def create_order(self, **kwargs):
            create_order_called.append(kwargs)
            return await super().create_order(**kwargs)

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        alert_calls = []

        def _alert(did: str, sid: str, reason: str) -> None:
            alert_calls.append((did, sid, reason))

        class FailingSnapshotRepo(DecisionSnapshotRepository):
            async def save(self, snapshot):
                raise RuntimeError("mock save failure")

        snapshot_repo = FailingSnapshotRepo(session)
        engine = ExecutionEngine(
            dom_repo,
            SpyAdapter(filled=True),
            RiskManager(),
            snapshot_repo=snapshot_repo,
            alert_callback=_alert,
        )
        result = await engine.execute_one(decision_id)

    assert result.get("status") == "failed"
    assert result.get("reason_code") == "DECISION_SNAPSHOT_SAVE_FAILED"
    assert len(create_order_called) == 0, "ExecutionEngine 不得调用 create_order（决策已被拒绝）"
    assert len(alert_calls) == 1
    assert alert_calls[0][0] == decision_id
    assert alert_calls[0][1] == "strat-fail"
    assert "mock save failure" in (alert_calls[0][2] or "")

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        row = await dom_repo.get_by_decision_id(decision_id)
    assert row is not None
    assert row.status == FAILED
    assert row.last_error == "DECISION_SNAPSHOT_SAVE_FAILED"

    async with get_db_session() as session:
        snap_repo = DecisionSnapshotRepository(session)
        snap = await snap_repo.get_by_decision_id(decision_id)
    assert snap is None, "快照写入失败时不应有 decision_snapshot 记录"
