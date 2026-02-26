"""
DecisionOrderMapRepository 单元测试
"""
import pytest
from datetime import datetime, timezone
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.models.decision_order_map_status import RESERVED, PLACED, FILLED
from src.app.dependencies import get_db_session


@pytest.mark.asyncio
async def test_create_reserved_success(db_session_factory):
    """测试成功创建 RESERVED 占位记录（happy path）"""
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        
        decision_id = "test_decision_001"
        signal_id = "test_signal_001"
        strategy_id = "MOCK_STRATEGY"
        symbol = "BTCUSDT"
        side = "BUY"
        created_at = datetime.now(timezone.utc)
        
        # 创建 RESERVED 记录
        record = await repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            created_at=created_at
        )
        
        assert record is not None
        assert record.decision_id == decision_id
        assert record.status == RESERVED
        
        # 提交后验证
        await session.commit()
        
        # 查询验证
        retrieved = await repo.get_by_decision_id(decision_id)
        assert retrieved is not None
        assert retrieved.decision_id == decision_id
        assert retrieved.status == RESERVED


@pytest.mark.asyncio
async def test_get_by_decision_id(db_session_factory):
    """测试根据 decision_id 查询记录"""
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        
        decision_id = "test_decision_002"
        created_at = datetime.now(timezone.utc)
        
        # 创建记录
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="signal_002",
            strategy_id="MOCK_STRATEGY",
            symbol="BTCUSDT",
            side="BUY",
            created_at=created_at
        )
        await session.commit()
        
        # 查询记录
        record = await repo.get_by_decision_id(decision_id)
        assert record is not None
        assert record.decision_id == decision_id
        
        # 查询不存在的记录
        nonexistent = await repo.get_by_decision_id("nonexistent_decision")
        assert nonexistent is None


@pytest.mark.asyncio
async def test_update_status(db_session_factory):
    """测试更新状态（不做状态机校验）"""
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        
        decision_id = "test_decision_003"
        created_at = datetime.now(timezone.utc)
        
        # 创建 RESERVED 记录
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="signal_003",
            strategy_id="MOCK_STRATEGY",
            symbol="BTCUSDT",
            side="BUY",
            created_at=created_at
        )
        await session.commit()
        
        # 更新状态为 PLACED
        async with get_db_session() as session2:
            repo2 = DecisionOrderMapRepository(session2)
            await repo2.update_status(
                decision_id=decision_id,
                status=PLACED,
                local_order_id="local_order_001",
                exchange_order_id="exchange_order_001"
            )
            await session2.commit()
        
        # 验证更新
        async with get_db_session() as session3:
            repo3 = DecisionOrderMapRepository(session3)
            updated = await repo3.get_by_decision_id(decision_id)
            assert updated is not None
            assert updated.status == PLACED
            assert updated.local_order_id == "local_order_001"
            assert updated.exchange_order_id == "exchange_order_001"


@pytest.mark.asyncio
async def test_update_status_nonexistent_raises_error(db_session_factory):
    """测试更新不存在的记录应抛出错误"""
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        
        # 尝试更新不存在的记录
        with pytest.raises(ValueError, match="not found"):
            await repo.update_status(
                decision_id="nonexistent_decision",
                status=FILLED
            )
