"""
风控状态 Repository（PR9：冷却时间等）

Cooldown 策略（产品语义）：
- 成交后 cooldown：仅在订单 FILLED 后更新 last_allowed_at。
- 放行后若下单失败（transient / final failed），不占用冷却，同 key 下一笔仍可立即尝试。
- 由 ExecutionEngine 在成功落库 FILLED 后调用 set_last_allowed_at，不在 RISK_PASSED 时调用。
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from src.models.risk_state import RiskState
from src.repositories.base import BaseRepository


class RiskStateRepository(BaseRepository[RiskState]):
    """RiskState Repository，key = strategy_id|symbol|side。Cooldown：成交后 cooldown（仅 FILLED 后写 last_allowed_at）。"""

    def _key(self, strategy_id: str, symbol: str, side: str) -> str:
        return f"{strategy_id}|{symbol}|{side}"

    async def get(self, strategy_id: str, symbol: str, side: str) -> Optional[RiskState]:
        k = self._key(strategy_id, symbol, side)
        stmt = select(RiskState).where(RiskState.key == k)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_last_allowed_at(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        last_allowed_at: datetime,
    ) -> RiskState:
        k = self._key(strategy_id, symbol, side)
        row = await self.get(strategy_id, symbol, side)
        now = datetime.now(timezone.utc)
        if row is None:
            row = RiskState(key=k, last_allowed_at=last_allowed_at)
            self.session.add(row)
        else:
            row.last_allowed_at = last_allowed_at
            row.updated_at = now
        return row
