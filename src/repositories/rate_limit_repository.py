"""
PR14a：限频状态 Repository（按 account_id 维度，多实例共享）
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select
from src.models.rate_limit_state import RateLimitState
from src.repositories.base import BaseRepository


class RateLimitRepository(BaseRepository[RateLimitState]):
    """限频状态：窗口内计数，原子 check-and-increment。"""

    async def allow_and_increment(
        self,
        account_id: str,
        max_per_minute: int,
        window_seconds: int = 60,
    ) -> bool:
        """
        若当前窗口内计数 < max_per_minute 则递增并返回 True；否则返回 False。
        窗口过期则重置计数。调用方应在同一 session 事务内调用，保证多实例语义。
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=window_seconds)
        stmt = select(RateLimitState).where(RateLimitState.account_id == account_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            self.session.add(
                RateLimitState(
                    account_id=account_id,
                    window_start_utc=now,
                    count=1,
                )
            )
            return True
        if row.window_start_utc.replace(tzinfo=timezone.utc) < window_start:
            row.window_start_utc = now
            row.count = 1
            row.updated_at = now
            return True
        if row.count >= max_per_minute:
            return False
        row.count += 1
        row.updated_at = now
        return True
