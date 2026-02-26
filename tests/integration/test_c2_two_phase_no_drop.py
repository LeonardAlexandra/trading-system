"""
Phase1.1 C2 两阶段互斥 + 阶段3 拿不到锁不丢单（最小复现证据）

证明：create_order 成功后若阶段3 拿不到锁，DB 中至少有 PENDING_EXCHANGE 记录可恢复，且返回 filled_pending_commit，绝不出现「交易所已下单但本地无记录」。
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
from src.models.decision_order_map_status import RESERVED, FILLED, PENDING_EXCHANGE
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter, CreateOrderResult
from src.execution.risk_manager import RiskManager
from src.common.reason_codes import PENDING_EXCHANGE_ACK_NOT_COMMITTED
from src.common.event_types import PENDING_EXCHANGE_ACK_NOT_COMMITTED as EV_PENDING_EXCHANGE_ACK_NOT_COMMITTED
from src.common.order_status import ORDER_STATUS_FILLED
from src.locks.reconcile_lock import ReconcileLock


@pytest.fixture
def c2_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def c2_db_url(c2_tmp_path):
    return "sqlite+aiosqlite:///" + (c2_tmp_path / "c2_no_drop.db").as_posix()


@pytest.fixture
def c2_sync_url(c2_tmp_path):
    return "sqlite:///" + (c2_tmp_path / "c2_no_drop.db").as_posix()


@pytest.fixture
def c2_schema(c2_sync_url):
    engine = create_engine(c2_sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def c2_session_factory(c2_db_url, c2_schema):
    engine = create_async_engine(c2_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_phase3_lock_not_acquired_does_not_drop_order(c2_session_factory):
    """
    模拟：阶段1 已写 PENDING_EXCHANGE 并 commit，create_order 返回成功，
    阶段3 拿不到锁（被对账/其他会话占用）时，必须至少保留 PENDING_EXCHANGE 且返回 filled_pending_commit，不丢单。
    """
    now = datetime.now(timezone.utc)
    decision_id = "c2-no-drop-001"
    strategy_id = "strat-1"
    session_factory = c2_session_factory

    async with get_db_session() as session:
        await session.execute(
            text("INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, lock_ttl_seconds) VALUES (:sid, 30)"),
            {"sid": strategy_id},
        )
        await session.commit()
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-c2",
            strategy_id=strategy_id,
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
        await session.commit()

    class AdapterThatLetsHolderAcquire(PaperExchangeAdapter):
        async def create_order(self, symbol, side, qty, client_order_id, **kwargs):
            async def hold_lock():
                async with get_db_session() as sess:
                    lock = ReconcileLock(sess, "reconcile-holder", max_acquire_retries=0)
                    ok = await lock.acquire(strategy_id)
                    await sess.commit()
                    if ok:
                        await asyncio.sleep(2.0)
                        await lock.release(strategy_id)
                        await sess.commit()

            asyncio.create_task(hold_lock())
            await asyncio.sleep(0.3)
            return CreateOrderResult(
                exchange_order_id="ex-001",
                client_order_id=client_order_id,
                status=ORDER_STATUS_FILLED,
            )

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        adapter = AdapterThatLetsHolderAcquire()
        engine = ExecutionEngine(dom_repo, adapter, RiskManager())
        result = await engine.execute_one(decision_id)

    assert result.get("decision_id") == decision_id
    assert result.get("status") == "filled_pending_commit"
    assert result.get("reason_code") == PENDING_EXCHANGE_ACK_NOT_COMMITTED
    assert result.get("exchange_order_id") == "ex-001"

    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        row = await repo.get_by_decision_id(decision_id)
        assert row is not None
        assert row.status == PENDING_EXCHANGE

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    event_types = [e.event_type for e in events]
    assert EV_PENDING_EXCHANGE_ACK_NOT_COMMITTED in event_types
