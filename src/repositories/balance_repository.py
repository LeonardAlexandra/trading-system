"""
Paper 账户余额 Repository（PR9；PR15c fallback 用 list_all）
"""
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from src.models.balance import Balance
from src.repositories.base import BaseRepository


class BalanceRepository(BaseRepository[Balance]):
    """Balance Repository"""

    async def list_all(self) -> List[Balance]:
        """PR15c：列出所有资产余额，供 AccountManager fallback 组装 AccountInfo。"""
        result = await self.session.execute(select(Balance))
        return list(result.scalars().all())

    async def get(self, asset: str) -> Optional[Balance]:
        stmt = select(Balance).where(Balance.asset == asset)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, asset: str, available: Decimal) -> Balance:
        row = await self.get(asset)
        now = datetime.now(timezone.utc)
        if row is None:
            row = Balance(asset=asset, available=available)
            self.session.add(row)
        else:
            row.available = available
            row.updated_at = now
        return row

    async def debit(self, asset: str, amount: Decimal) -> Balance:
        row = await self.get(asset)
        if row is None:
            row = Balance(asset=asset, available=-amount)
            self.session.add(row)
        else:
            row.available = (row.available or Decimal("0")) - amount
            row.updated_at = datetime.now(timezone.utc)
        return row

    async def credit(self, asset: str, amount: Decimal) -> Balance:
        row = await self.get(asset)
        if row is None:
            row = Balance(asset=asset, available=amount)
            self.session.add(row)
        else:
            row.available = (row.available or Decimal("0")) + amount
            row.updated_at = datetime.now(timezone.utc)
        return row
