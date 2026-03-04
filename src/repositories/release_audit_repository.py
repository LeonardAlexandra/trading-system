"""
Phase2.1 A2：ReleaseAuditRepository

只读写 Phase 2.1 自有表 release_audit（仅追加，禁止删改）。
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.release_audit import ReleaseAudit


class ReleaseAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, record: ReleaseAudit) -> ReleaseAudit:
        """仅追加，禁止 UPDATE/DELETE。"""
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_strategy_id(self, strategy_id: str) -> List[ReleaseAudit]:
        stmt = (
            select(ReleaseAudit)
            .where(ReleaseAudit.strategy_id == strategy_id)
            .order_by(desc(ReleaseAudit.created_at), desc(ReleaseAudit.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_param_version_id(self, param_version_id: str) -> List[ReleaseAudit]:
        stmt = (
            select(ReleaseAudit)
            .where(ReleaseAudit.param_version_id == param_version_id)
            .order_by(desc(ReleaseAudit.created_at), desc(ReleaseAudit.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_by_strategy(
        self, strategy_id: str, action: Optional[str] = None
    ) -> Optional[ReleaseAudit]:
        stmt = select(ReleaseAudit).where(ReleaseAudit.strategy_id == strategy_id)
        if action:
            stmt = stmt.where(ReleaseAudit.action == action)
        stmt = stmt.order_by(desc(ReleaseAudit.created_at), desc(ReleaseAudit.id)).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
