"""
OrderManager 单元测试（PR12 + 工程级整改：审计事件）
"""
import pytest
from decimal import Decimal

from src.execution.order_manager import OrderManager
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.repositories.orders_repo import OrdersRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.models.order import Order
from src.common.order_status import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_SUBMITTED,
)
from src.common.event_types import ORDER_CANCELLED as EV_ORDER_CANCELLED, ORDER_SYNCED as EV_ORDER_SYNCED
from src.app.dependencies import get_db_session


@pytest.mark.asyncio
async def test_get_order_exists(db_session_factory):
    """能查询到已存在的订单"""
    async with get_db_session() as session:
        repo = OrdersRepository(session)
        order = Order(
            order_id="local_001",
            exchange_order_id="ex_001",
            strategy_id="S1",
            decision_id="d1",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            filled_quantity=Decimal("0"),
            status=ORDER_STATUS_SUBMITTED,
        )
        await repo.create(order)
        await session.commit()

        adapter = PaperExchangeAdapter(filled=False)
        manager = OrderManager(adapter, OrdersRepository(session), ExecutionEventRepository(session))
        got = await manager.get_order("local_001")
        assert got is not None
        assert got.order_id == "local_001"
        assert got.status == ORDER_STATUS_SUBMITTED


@pytest.mark.asyncio
async def test_get_order_not_found(db_session_factory):
    """不存在的订单返回 None"""
    async with get_db_session() as session:
        adapter = PaperExchangeAdapter()
        manager = OrderManager(adapter, OrdersRepository(session), ExecutionEventRepository(session))
        got = await manager.get_order("nonexistent")
        assert got is None


@pytest.mark.asyncio
async def test_cancel_order_success(db_session_factory):
    """能取消未成交订单，本地状态更新为 CANCELLED"""
    async with get_db_session() as session:
        adapter = PaperExchangeAdapter(filled=False)
        result = await adapter.create_order(
            symbol="BTCUSDT",
            side="BUY",
            qty=Decimal("0.01"),
            client_order_id="d1",
        )
        exchange_order_id = result.exchange_order_id

        repo = OrdersRepository(session)
        order = Order(
            order_id="local_cancel",
            exchange_order_id=exchange_order_id,
            strategy_id="S1",
            decision_id="d1",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            filled_quantity=Decimal("0"),
            status=ORDER_STATUS_SUBMITTED,
        )
        await repo.create(order)
        await session.commit()

        event_repo = ExecutionEventRepository(session)
        manager = OrderManager(adapter, OrdersRepository(session), event_repo)
        ok = await manager.cancel_order("local_cancel", reason="user")
        assert ok is True
        await session.commit()

        updated = await repo.get_by_local_order_id("local_cancel")
        assert updated is not None
        assert updated.status == ORDER_STATUS_CANCELLED
        events = await event_repo.list_by_decision_id("d1")
        assert any(e.event_type == EV_ORDER_CANCELLED for e in events)
        cancelled_ev = next(e for e in events if e.event_type == EV_ORDER_CANCELLED)
        assert "order_id=local_cancel" in (cancelled_ev.message or "")
        assert cancelled_ev.exchange_order_id == exchange_order_id
        assert cancelled_ev.reason_code == "user"


@pytest.mark.asyncio
async def test_cancel_order_already_filled_returns_false(db_session_factory):
    """已成交订单取消失败，返回 False"""
    async with get_db_session() as session:
        adapter = PaperExchangeAdapter(filled=True)
        result = await adapter.create_order(
            symbol="BTCUSDT",
            side="BUY",
            qty=Decimal("0.01"),
            client_order_id="d1",
        )
        repo = OrdersRepository(session)
        order = Order(
            order_id="local_filled",
            exchange_order_id=result.exchange_order_id,
            strategy_id="S1",
            decision_id="d1",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            filled_quantity=Decimal("0.01"),
            status=ORDER_STATUS_FILLED,
        )
        await repo.create(order)
        await session.commit()

        manager = OrderManager(adapter, OrdersRepository(session), ExecutionEventRepository(session))
        ok = await manager.cancel_order("local_filled", reason="user")
        assert ok is False


@pytest.mark.asyncio
async def test_cancel_order_not_found_returns_false(db_session_factory):
    """订单不存在时取消返回 False"""
    async with get_db_session() as session:
        adapter = PaperExchangeAdapter()
        manager = OrderManager(adapter, OrdersRepository(session), ExecutionEventRepository(session))
        ok = await manager.cancel_order("nonexistent", reason="user")
        assert ok is False


@pytest.mark.asyncio
async def test_sync_order_status_updates_local(db_session_factory):
    """从交易所同步状态并更新本地订单"""
    async with get_db_session() as session:
        adapter = PaperExchangeAdapter(filled=False)
        result = await adapter.create_order(
            symbol="BTCUSDT",
            side="BUY",
            qty=Decimal("0.02"),
            client_order_id="d1",
        )
        repo = OrdersRepository(session)
        order = Order(
            order_id="local_sync",
            exchange_order_id=result.exchange_order_id,
            strategy_id="S1",
            decision_id="d1",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.02"),
            filled_quantity=Decimal("0"),
            status=ORDER_STATUS_SUBMITTED,
        )
        await repo.create(order)
        await session.commit()

        event_repo = ExecutionEventRepository(session)
        manager = OrderManager(adapter, OrdersRepository(session), event_repo)
        updated = await manager.sync_order_status("local_sync")
        assert updated.order_id == "local_sync"
        assert updated.status == ORDER_STATUS_SUBMITTED
        await session.commit()

        from_db = await repo.get_by_local_order_id("local_sync")
        assert from_db.status == ORDER_STATUS_SUBMITTED
        events = await event_repo.list_by_decision_id("d1")
        assert any(e.event_type == EV_ORDER_SYNCED for e in events)
        synced_ev = next(e for e in events if e.event_type == EV_ORDER_SYNCED)
        assert "order_id=local_sync" in (synced_ev.message or "")
        assert synced_ev.reason_code == "system"


@pytest.mark.asyncio
async def test_sync_order_status_not_found_raises(db_session_factory):
    """订单不存在时 sync_order_status 抛出 ValueError"""
    async with get_db_session() as session:
        adapter = PaperExchangeAdapter()
        manager = OrderManager(adapter, OrdersRepository(session), ExecutionEventRepository(session))
        with pytest.raises(ValueError, match="Order not found"):
            await manager.sync_order_status("nonexistent")
