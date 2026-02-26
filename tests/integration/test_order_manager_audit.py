"""
PR12 工程级整改：OrderManager 与 ExecutionEngine 边界 + execution_events 审计链。
覆盖：ExecutionEngine 已创建订单 → OrderManager cancel/sync → execution_events 顺序与最终订单状态正确。
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
from src.models.decision_order_map_status import RESERVED
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.repositories.orders_repo import OrdersRepository
from src.models.order import Order
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.order_manager import OrderManager
from src.execution.risk_manager import RiskManager
from src.common.event_types import (
    CLAIMED,
    ORDER_SUBMIT_OK,
    FILLED as EV_FILLED,
    ORDER_CANCELLED as EV_ORDER_CANCELLED,
    ORDER_SYNCED as EV_ORDER_SYNCED,
)
from src.common.order_status import ORDER_STATUS_SUBMITTED, ORDER_STATUS_CANCELLED


@pytest.fixture
async def audit_session_factory(db_session_factory):
    """复用全局 db_session_factory，保证 execution_events 表存在。"""
    yield db_session_factory


@pytest.mark.asyncio
async def test_engine_then_order_manager_cancel_events_and_order_state(audit_session_factory):
    """
    ExecutionEngine 执行成功（Paper filled=False）→ 插入 orders 表 → OrderManager.cancel_order
    → execution_events 含 CLAIMED / ORDER_SUBMIT_* / FILLED / ORDER_CANCELLED，顺序正确；
    orders 表该订单状态为 CANCELLED。
    """
    decision_id = "audit-cancel-001"
    now = datetime.now(timezone.utc)

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-a1",
            strategy_id="strat-a",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        await session.commit()

    adapter = PaperExchangeAdapter(filled=False)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, adapter, RiskManager())
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "filled"
    exchange_order_id = result.get("exchange_order_id")
    assert exchange_order_id

    local_order_id = "local-audit-cancel-001"
    async with get_db_session() as session:
        order_repo = OrdersRepository(session)
        order = Order(
            order_id=local_order_id,
            exchange_order_id=exchange_order_id,
            strategy_id="strat-a",
            decision_id=decision_id,
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            filled_quantity=Decimal("0"),
            status=ORDER_STATUS_SUBMITTED,
        )
        await order_repo.create(order)
        await session.commit()

    async with get_db_session() as session:
        order_repo = OrdersRepository(session)
        event_repo = ExecutionEventRepository(session)
        manager = OrderManager(adapter, order_repo, event_repo)
        ok = await manager.cancel_order(local_order_id, reason="user_cancel")
        await session.commit()
    assert ok is True

    async with get_db_session() as session:
        order_repo = OrdersRepository(session)
        event_repo = ExecutionEventRepository(session)
        updated = await order_repo.get_by_local_order_id(local_order_id)
        assert updated is not None
        assert updated.status == ORDER_STATUS_CANCELLED

        events = await event_repo.list_by_decision_id(decision_id)
        event_types = [e.event_type for e in events]
        assert CLAIMED in event_types
        assert ORDER_SUBMIT_OK in event_types
        assert EV_FILLED in event_types
        assert EV_ORDER_CANCELLED in event_types
        cancelled_idx = next(i for i, e in enumerate(events) if e.event_type == EV_ORDER_CANCELLED)
        filled_idx = next(i for i, e in enumerate(events) if e.event_type == EV_FILLED)
        assert cancelled_idx > filled_idx
        ev_cancelled = events[cancelled_idx]
        assert ev_cancelled.exchange_order_id == exchange_order_id
        assert "order_id=" + local_order_id in (ev_cancelled.message or "")
        assert ev_cancelled.reason_code == "user"


@pytest.mark.asyncio
async def test_engine_then_order_manager_sync_events_and_order_state(audit_session_factory):
    """
    ExecutionEngine 执行成功 → 插入 orders 表 → OrderManager.sync_order_status
    → execution_events 含 ORDER_SYNCED；订单状态与交易所一致。
    """
    decision_id = "audit-sync-002"
    now = datetime.now(timezone.utc)

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-a2",
            strategy_id="strat-a",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.02"),
        )
        await session.commit()

    adapter = PaperExchangeAdapter(filled=False)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, adapter, RiskManager())
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "filled"
    exchange_order_id = result.get("exchange_order_id")
    assert exchange_order_id

    local_order_id = "local-audit-sync-002"
    async with get_db_session() as session:
        order_repo = OrdersRepository(session)
        order = Order(
            order_id=local_order_id,
            exchange_order_id=exchange_order_id,
            strategy_id="strat-a",
            decision_id=decision_id,
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.02"),
            filled_quantity=Decimal("0"),
            status=ORDER_STATUS_SUBMITTED,
        )
        await order_repo.create(order)
        await session.commit()

    async with get_db_session() as session:
        order_repo = OrdersRepository(session)
        event_repo = ExecutionEventRepository(session)
        manager = OrderManager(adapter, order_repo, event_repo)
        updated = await manager.sync_order_status(local_order_id, source="system")
        await session.commit()
    assert updated.order_id == local_order_id

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
        assert any(e.event_type == EV_ORDER_SYNCED for e in events)
        synced_ev = next(e for e in events if e.event_type == EV_ORDER_SYNCED)
        assert "order_id=" + local_order_id in (synced_ev.message or "")
        assert synced_ev.exchange_order_id == exchange_order_id
        assert synced_ev.reason_code == "system"
