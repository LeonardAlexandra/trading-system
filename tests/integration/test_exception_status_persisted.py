"""
封版 BLOCKER-3：异常状态独立 session commit 验证

证明：TIMEOUT/FAILED/UNKNOWN 通过独立 Session 显式 commit 落库，不依赖主请求 session。
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401 - ensure Trade, DedupSignal with processed
from src.models.decision_order_map_status import RESERVED, FAILED
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.execution.execution_engine import _persist_exception_status
from src.execution.risk_manager import RiskManager


@pytest.fixture
def seal_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def seal_db_url(seal_tmp_path):
    return "sqlite+aiosqlite:///" + (seal_tmp_path / "seal_exception.db").as_posix()


@pytest.fixture
def seal_sync_url(seal_tmp_path):
    return "sqlite:///" + (seal_tmp_path / "seal_exception.db").as_posix()


@pytest.fixture
def seal_schema(seal_sync_url):
    engine = create_engine(seal_sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def seal_session_factory(seal_db_url, seal_schema):
    engine = create_async_engine(seal_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_persist_exception_status_commits_in_independent_session(seal_session_factory):
    """
    直接调用 _persist_exception_status：先落一条 RESERVED，再在独立 session 中更新为 FAILED 并 commit。
    在新 session 中查询，status 必须为 FAILED。证明异常状态由独立 session 落库，不依赖主 session。
    """
    now = datetime.now(timezone.utc)
    decision_id = "seal-failed-persist-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-seal-1",
            strategy_id="strat-seal",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.001"),
        )

    await _persist_exception_status(
        decision_id,
        FAILED,
        last_error="ORDER_REJECTED",
        updated_at=now,
    )

    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        row = await repo.get_by_decision_id(decision_id)
    assert row is not None
    assert row.status == FAILED
    assert row.last_error == "ORDER_REJECTED"
