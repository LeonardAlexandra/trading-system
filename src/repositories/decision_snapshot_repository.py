"""
Phase1.2 C1：决策输入快照 Repository（仅 insert + select，无 update/delete）

蓝本 D.1：save 失败抛异常；禁止按 decision_id 的 update/delete。
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.decision_snapshot import DecisionSnapshot


class DecisionSnapshotRepository:
    """
    决策输入快照仓储。仅暴露 save、get_by_decision_id、list_by_strategy_time。
    禁止提供 update/delete 或任何覆盖写语义。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, snapshot: DecisionSnapshot) -> None:
        """
        写入一条决策输入快照。失败时抛出异常，由调用方处理（不产出 TradingDecision、告警、写日志）。
        """
        self.session.add(snapshot)
        await self.session.flush()

    async def get_by_decision_id(self, decision_id: str) -> Optional[DecisionSnapshot]:
        """按 decision_id 单条查询。"""
        stmt = select(DecisionSnapshot).where(DecisionSnapshot.decision_id == decision_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_strategy_time(
        self,
        strategy_id: str,
        start_ts: datetime,
        end_ts: datetime,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[DecisionSnapshot]:
        """按 strategy_id + 时间范围分页查询。"""
        stmt = (
            select(DecisionSnapshot)
            .where(
                DecisionSnapshot.strategy_id == strategy_id,
                DecisionSnapshot.created_at >= start_ts,
                DecisionSnapshot.created_at <= end_ts,
            )
            .order_by(DecisionSnapshot.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
