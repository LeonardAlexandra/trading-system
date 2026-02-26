"""
DedupSignalRepository 单元测试
"""
import pytest
from datetime import datetime, timezone
from src.repositories.dedup_signal_repo import DedupSignalRepository
from src.app.dependencies import get_db_session


def _utc_timestamp(dt: datetime) -> float:
    """归一化为 UTC 时间戳（SQLite 读回 naive 时视为 UTC）"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).timestamp()
    return dt.timestamp()


@pytest.mark.asyncio
async def test_try_insert_success(db_session_factory):
    """测试成功插入信号记录（happy path）"""
    async with get_db_session() as session:
        repo = DedupSignalRepository(session)
        
        signal_id = "test_signal_001"
        received_at = datetime.now(timezone.utc)
        
        # 插入成功应返回 True
        result = await repo.try_insert(signal_id, received_at)
        assert result is True
        
        # 验证记录已创建（时间用 UTC 时间戳比较，避免 SQLite naive/aware 不一致）
        record = await repo.get(signal_id)
        assert record is not None
        assert record.signal_id == signal_id
        expected_ts = _utc_timestamp(received_at)
        assert abs(_utc_timestamp(record.first_seen_at) - expected_ts) < 2
        assert abs(_utc_timestamp(record.received_at) - expected_ts) < 2


@pytest.mark.asyncio
async def test_try_insert_duplicate_returns_false(db_session_factory):
    """测试重复插入返回 False（验证幂等依赖 DB 主键冲突）"""
    async with get_db_session() as session:
        repo = DedupSignalRepository(session)
        
        signal_id = "test_signal_002"
        received_at = datetime.now(timezone.utc)
        
        # 第一次插入成功
        result1 = await repo.try_insert(signal_id, received_at)
        assert result1 is True
        await session.commit()  # 提交第一次插入
        
        # 第二次插入相同 signal_id 应返回 False（幂等）
        async with get_db_session() as session2:
            repo2 = DedupSignalRepository(session2)
            result2 = await repo2.try_insert(signal_id, received_at)
            assert result2 is False  # 重复信号返回 False，不抛异常


@pytest.mark.asyncio
async def test_get_existing_signal(db_session_factory):
    """测试查询已存在的信号"""
    async with get_db_session() as session:
        repo = DedupSignalRepository(session)
        
        signal_id = "test_signal_003"
        received_at = datetime.now(timezone.utc)
        
        # 插入记录
        await repo.try_insert(signal_id, received_at)
        await session.commit()
        
        # 查询记录
        record = await repo.get(signal_id)
        assert record is not None
        assert record.signal_id == signal_id


@pytest.mark.asyncio
async def test_get_nonexistent_signal(db_session_factory):
    """测试查询不存在的信号返回 None"""
    async with get_db_session() as session:
        repo = DedupSignalRepository(session)
        
        # 查询不存在的 signal_id
        record = await repo.get("nonexistent_signal")
        assert record is None
