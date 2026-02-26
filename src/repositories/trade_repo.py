"""
Trade Repository（Phase1.0 表存在；Phase1.1 A2 支持 source_type / external_trade_id）

创建或更新 trade 时支持传入 source_type=EXTERNAL_SYNC、external_trade_id。
EXTERNAL_SYNC 幂等由 DB 唯一约束 uq_trade_strategy_external_trade_id 保证，插入前可按 (strategy_id, external_trade_id) 判重。

工程级边界（作用域锁定）：SIGNAL 行不得写入 external_trade_id。
- 写入层：source_type=SIGNAL 时 external_trade_id 必须为 None（由调用方保证；Repo 不替 SIGNAL 填 external_trade_id）。
- EXTERNAL_SYNC 路径（如 C3）唯一可设置 external_trade_id；插入前建议 get_by_strategy_external_trade_id 判重。

Phase2.0 C2：list_by_strategy_and_executed_time_range 为只读接口，供 MetricsCalculator 按 B.2 口径读取 trade，不写表。
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from src.models.trade import Trade
from src.repositories.base import BaseRepository


class TradeRepository(BaseRepository[Trade]):
    """trade 表访问；支持信号驱动与 EXTERNAL_SYNC 写入；SIGNAL 行不得写 external_trade_id（见模块 docstring）。"""

    async def get_by_trade_id(self, trade_id: str) -> Optional[Trade]:
        stmt = select(Trade).where(Trade.trade_id == trade_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_strategy_external_trade_id(
        self, strategy_id: str, external_trade_id: str
    ) -> Optional[Trade]:
        """按 EXTERNAL_SYNC 幂等键查询，插入前判重用。"""
        stmt = select(Trade).where(
            Trade.strategy_id == strategy_id,
            Trade.external_trade_id == external_trade_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_strategy_and_executed_time_range(
        self,
        strategy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> List[Trade]:
        """
        只读：按 strategy_id 与 executed_at 在 [period_start, period_end] 内查询，按 executed_at 升序。
        供 Phase2.0 MetricsCalculator 按 B.2 口径只读 trade 表；本方法不执行任何 INSERT/UPDATE/DELETE。
        """
        stmt = (
            select(Trade)
            .where(
                Trade.strategy_id == strategy_id,
                Trade.executed_at >= period_start,
                Trade.executed_at <= period_end,
            )
            .order_by(Trade.executed_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, trade: Trade) -> Trade:
        """写入一条 trade。SIGNAL 时调用方必须保证 trade.external_trade_id 为 None；EXTERNAL_SYNC 唯一性由 DB 约束保证。"""
        self.session.add(trade)
        return trade
