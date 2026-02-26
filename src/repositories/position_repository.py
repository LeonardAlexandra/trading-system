"""
Paper 持仓 Repository（PR9；PR11：按 strategy_id 隔离）
"""
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select
from src.models.position import Position
from src.repositories.base import BaseRepository


class PositionRepository(BaseRepository[Position]):
    """Position Repository，PR11：所有读写按 (strategy_id, symbol) 隔离。"""

    async def get(self, strategy_id: str, symbol: str) -> Optional[Position]:
        stmt = select(Position).where(
            Position.strategy_id == strategy_id,
            Position.symbol == symbol,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_by_strategy(self, strategy_id: str) -> List[Position]:
        """PR11：获取某策略下所有持仓。"""
        stmt = select(Position).where(Position.strategy_id == strategy_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> List[Position]:
        """C6：获取全表持仓（用于 get_status(strategy_id=None)）。"""
        stmt = select(Position)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        strategy_id: str,
        symbol: str,
        quantity: Decimal,
        *,
        side: str = "LONG",
        avg_price: Optional[Decimal] = None,
    ) -> Position:
        row = await self.get(strategy_id, symbol)
        now = datetime.now(timezone.utc)
        if row is None:
            row = Position(
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                avg_price=avg_price,
            )
            self.session.add(row)
        else:
            row.quantity = quantity
            if avg_price is not None:
                row.avg_price = avg_price
            row.updated_at = now
        return row

    async def increase(
        self,
        strategy_id: str,
        symbol: str,
        qty: Decimal,
        avg_price: Optional[Decimal] = None,
        *,
        side: str = "LONG",
    ) -> Position:
        row = await self.get(strategy_id, symbol)
        now = datetime.now(timezone.utc)
        if row is None:
            row = Position(
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                quantity=qty,
                avg_price=avg_price,
            )
            self.session.add(row)
        else:
            prev_qty = row.quantity or Decimal("0")
            prev_avg = row.avg_price
            new_qty = prev_qty + qty
            if avg_price is not None and qty > 0:
                new_avg = (
                    (prev_avg * prev_qty + avg_price * qty) / new_qty
                    if prev_avg is not None
                    else avg_price
                )
            else:
                new_avg = prev_avg
            row.quantity = new_qty
            row.avg_price = new_avg
            row.updated_at = now
        return row

    async def decrease(self, strategy_id: str, symbol: str, qty: Decimal) -> Position:
        row = await self.get(strategy_id, symbol)
        if row is None:
            row = Position(
                strategy_id=strategy_id,
                symbol=symbol,
                side="LONG",
                quantity=-qty,
            )
            self.session.add(row)
        else:
            row.quantity = (row.quantity or Decimal("0")) - qty
            row.updated_at = datetime.now(timezone.utc)
        return row
