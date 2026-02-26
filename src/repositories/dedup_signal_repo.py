"""
DedupSignal Repository（信号去重表）
"""
from typing import Optional
from datetime import datetime
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from src.models.dedup_signal import DedupSignal
from src.repositories.base import BaseRepository


class DedupSignalRepository(BaseRepository[DedupSignal]):
    """信号去重表 Repository"""
    
    async def try_insert(
        self,
        signal_id: str,
        received_at: datetime,
        raw_payload: bytes | str | None = None
    ) -> bool:
        """
        尝试插入信号记录（幂等操作，依赖 DB 主键冲突）
        
        语义：
        - 插入成功返回 True
        - 若因主键冲突（重复信号）返回 False
        - 不得抛异常给上层（除非非冲突错误）
        
        Args:
            signal_id: 信号 ID（主键）
            received_at: 接收时间
            raw_payload: 原始 payload（可选，当前模型不支持，保留接口兼容性）
        
        Returns:
            True 表示插入成功，False 表示信号已存在（主键冲突）
        """
        # 创建新记录
        dedup_signal = DedupSignal(
            signal_id=signal_id,
            first_seen_at=received_at,  # 首次接收时间
            received_at=received_at,  # 当前接收时间
        )
        
        # 使用 SAVEPOINT 处理 IntegrityError（PR3 约束：禁止直接 rollback）
        # 嵌套事务回滚不影响外层事务
        for attempt in range(4):
            try:
                async with self.session.begin_nested():
                    self.session.add(dedup_signal)
                    # 尝试 flush 以触发主键冲突检查（不 commit，由上层管理）
                    await self.session.flush()
                return True
            except IntegrityError:
                # 主键冲突（重复信号），SAVEPOINT 已自动回滚，不影响外层事务
                return False
            except OperationalError as exc:
                # SQLite 并发写锁短暂冲突时做有限重试，避免将瞬态锁误判为 500。
                if "database is locked" not in str(exc).lower():
                    raise
                if attempt == 3:
                    # 在高并发同信号场景下，将锁冲突退化为“已处理/重复”而不是 500。
                    return False
                await asyncio.sleep(0.02 * (attempt + 1))
        return False
    
    async def get(self, signal_id: str) -> Optional[DedupSignal]:
        """
        根据 signal_id 查询信号记录
        
        Args:
            signal_id: 信号 ID
        
        Returns:
            DedupSignal 对象，如果不存在则返回 None
        """
        stmt = select(DedupSignal).where(DedupSignal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
