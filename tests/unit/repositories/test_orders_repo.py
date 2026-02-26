"""
OrdersRepository 单元测试
"""
import pytest
from decimal import Decimal
from src.repositories.orders_repo import OrdersRepository
from src.models.order import Order
from src.app.dependencies import get_db_session


@pytest.mark.asyncio
async def test_create_order_success(db_session_factory):
    """测试成功创建订单记录（happy path）"""
    async with get_db_session() as session:
        repo = OrdersRepository(session)
        
        order = Order(
            order_id="test_order_001",
            exchange_order_id="exchange_001",
            strategy_id="MOCK_STRATEGY",
            decision_id="test_decision_001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            filled_quantity=Decimal("0"),
            price=Decimal("50000.0"),
            status="PENDING"
        )
        
        # 创建订单
        created = await repo.create(order)
        assert created is not None
        assert created.order_id == "test_order_001"
        
        # 提交后验证
        await session.commit()
        
        # 查询验证
        retrieved = await repo.get_by_local_order_id("test_order_001")
        assert retrieved is not None
        assert retrieved.order_id == "test_order_001"
        assert retrieved.symbol == "BTCUSDT"
        assert retrieved.status == "PENDING"


@pytest.mark.asyncio
async def test_get_by_local_order_id(db_session_factory):
    """测试根据本地订单号查询订单"""
    async with get_db_session() as session:
        repo = OrdersRepository(session)
        
        order = Order(
            order_id="test_order_002",
            strategy_id="MOCK_STRATEGY",
            decision_id="test_decision_002",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            status="PENDING"
        )
        
        await repo.create(order)
        await session.commit()
        
        # 查询存在的订单
        retrieved = await repo.get_by_local_order_id("test_order_002")
        assert retrieved is not None
        assert retrieved.order_id == "test_order_002"
        
        # 查询不存在的订单
        nonexistent = await repo.get_by_local_order_id("nonexistent_order")
        assert nonexistent is None


@pytest.mark.asyncio
async def test_list_by_decision_id(db_session_factory):
    """测试根据 decision_id 查询订单列表"""
    async with get_db_session() as session:
        repo = OrdersRepository(session)
        
        decision_id = "test_decision_003"
        
        # 创建多个订单（同一 decision_id）
        order1 = Order(
            order_id="test_order_003_1",
            strategy_id="MOCK_STRATEGY",
            decision_id=decision_id,
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            status="PENDING"
        )
        order2 = Order(
            order_id="test_order_003_2",
            strategy_id="MOCK_STRATEGY",
            decision_id=decision_id,
            symbol="ETHUSDT",
            side="SELL",
            quantity=Decimal("0.1"),
            status="PENDING"
        )
        
        await repo.create(order1)
        await repo.create(order2)
        await session.commit()
        
        # 查询列表
        orders = await repo.list_by_decision_id(decision_id)
        assert len(orders) == 2
        order_ids = {o.order_id for o in orders}
        assert "test_order_003_1" in order_ids
        assert "test_order_003_2" in order_ids
        
        # 查询不存在的 decision_id
        empty_list = await repo.list_by_decision_id("nonexistent_decision")
        assert len(empty_list) == 0
