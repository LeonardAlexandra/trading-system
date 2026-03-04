"""
Phase2.1 A3：LearningAuditRepository

只读写 Phase 2.1 自有表 learning_audit（仅追加，禁止删改）。
"""
from typing import List

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.learning_audit import LearningAudit


class LearningAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, record: LearningAudit) -> LearningAudit:
        """仅追加，禁止 UPDATE/DELETE。"""
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_strategy_id(self, strategy_id: str) -> List[LearningAudit]:
        stmt = (
            select(LearningAudit)
            .where(LearningAudit.strategy_id == strategy_id)
            .order_by(desc(LearningAudit.created_at), desc(LearningAudit.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_param_version_id_candidate(
        self, param_version_id_candidate: str
    ) -> List[LearningAudit]:
        stmt = (
            select(LearningAudit)
            .where(LearningAudit.param_version_id_candidate == param_version_id_candidate)
            .order_by(desc(LearningAudit.created_at), desc(LearningAudit.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
