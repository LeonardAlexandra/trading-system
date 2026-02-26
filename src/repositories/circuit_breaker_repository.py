"""
PR14a：断路器状态 Repository（按 account_id 维度，多实例共享）
"""
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from src.models.circuit_breaker_state import CircuitBreakerState
from src.repositories.base import BaseRepository


class CircuitBreakerRepository(BaseRepository[CircuitBreakerState]):
    """断路器状态：失败计数与熔断 until。"""

    async def get_state(self, account_id: str) -> Optional[CircuitBreakerState]:
        """获取 account_id 对应状态。"""
        stmt = select(CircuitBreakerState).where(CircuitBreakerState.account_id == account_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def is_open(
        self,
        account_id: str,
        open_seconds: int,
    ) -> Tuple[bool, Optional[datetime], bool]:
        """
        返回 (是否熔断中, opened_at_utc, just_closed)。
        若 opened_at 已过 open_seconds 则视为已关闭并重置状态，此时 just_closed=True 便于审计 CIRCUIT_CLOSED。
        """
        row = await self.get_state(account_id)
        if row is None or row.opened_at_utc is None:
            return False, None, False
        now = datetime.now(timezone.utc)
        opened_at = row.opened_at_utc
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        if (now - opened_at).total_seconds() >= open_seconds:
            row.opened_at_utc = None
            row.failures_count = 0
            row.updated_at = now
            return False, None, True
        return True, row.opened_at_utc, False

    async def record_failure(
        self,
        account_id: str,
        threshold: int,
        open_seconds: int,
    ) -> Tuple[int, bool]:
        """
        记录一次失败；若 failures_count >= threshold 则打开熔断。
        返回 (当前 failures_count, 是否本次触发了打开)。
        """
        now = datetime.now(timezone.utc)
        row = await self.get_state(account_id)
        if row is None:
            row = CircuitBreakerState(
                account_id=account_id,
                failures_count=1,
                opened_at_utc=now if threshold <= 1 else None,
            )
            self.session.add(row)
            return 1, threshold <= 1
        if row.opened_at_utc is not None:
            return row.failures_count, False
        row.failures_count += 1
        row.updated_at = now
        if row.failures_count >= threshold:
            row.opened_at_utc = now
            return row.failures_count, True
        return row.failures_count, False

    async def record_success(self, account_id: str) -> None:
        """成功则重置失败计数。"""
        row = await self.get_state(account_id)
        if row is not None:
            row.failures_count = 0
            row.opened_at_utc = None
            row.updated_at = datetime.now(timezone.utc)

    async def close_circuit(self, account_id: str) -> None:
        """强制关闭熔断（用于测试或运维）。"""
        row = await self.get_state(account_id)
        if row is not None:
            row.opened_at_utc = None
            row.failures_count = 0
            row.updated_at = datetime.now(timezone.utc)
