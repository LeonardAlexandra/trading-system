"""
Phase2.1 A4：ParamVersionRepository

只读写 Phase 2.1 自有表 param_version；
禁止对 Phase 2.0 表（evaluation_report / metrics_snapshot）执行任何写操作。
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.param_version import ParamVersion, VALID_RELEASE_STATES


class ParamVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, pv: ParamVersion) -> ParamVersion:
        self.session.add(pv)
        await self.session.flush()
        return pv

    async def get_by_param_version_id(self, param_version_id: str) -> Optional[ParamVersion]:
        stmt = select(ParamVersion).where(ParamVersion.param_version_id == param_version_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_strategy_id(self, strategy_id: str) -> List[ParamVersion]:
        stmt = (
            select(ParamVersion)
            .where(ParamVersion.strategy_id == strategy_id)
            .order_by(desc(ParamVersion.created_at), desc(ParamVersion.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_strategy_and_state(
        self, strategy_id: str, release_state: str
    ) -> List[ParamVersion]:
        stmt = (
            select(ParamVersion)
            .where(
                ParamVersion.strategy_id == strategy_id,
                ParamVersion.release_state == release_state,
            )
            .order_by(desc(ParamVersion.created_at), desc(ParamVersion.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self, strategy_id: str) -> Optional[ParamVersion]:
        rows = await self.get_by_strategy_and_state(strategy_id, "active")
        return rows[0] if rows else None

    async def get_stable(self, strategy_id: str) -> Optional[ParamVersion]:
        rows = await self.get_by_strategy_and_state(strategy_id, "stable")
        return rows[0] if rows else None

    async def update_release_state(
        self, param_version_id: str, new_state: str
    ) -> Optional[ParamVersion]:
        if new_state not in VALID_RELEASE_STATES:
            raise ValueError(f"Invalid release_state: {new_state!r}")
        stmt = (
            update(ParamVersion)
            .where(ParamVersion.param_version_id == param_version_id)
            .values(release_state=new_state, updated_at=datetime.now(timezone.utc))
            .returning(ParamVersion)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none()
