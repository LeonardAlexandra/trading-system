"""
Phase1.1 A1：strategy_runtime_state 表 Repository（字段映射，供 C1 对接）
C5：增加更新状态为 PAUSED 的接口，与终态日志在同一事务内由 strategy_manager 调用。
"""
from typing import Optional

from sqlalchemy import select, update
from src.models.strategy_runtime_state import StrategyRuntimeState, STATUS_PAUSED, STATUS_RUNNING
from src.repositories.base import BaseRepository


class StrategyRuntimeStateRepository(BaseRepository[StrategyRuntimeState]):
    """strategy_runtime_state 表访问；锁逻辑在 C1；C5 支持更新 status 为 PAUSED。"""

    async def get_by_strategy_id(self, strategy_id: str) -> Optional[StrategyRuntimeState]:
        stmt = select(StrategyRuntimeState).where(StrategyRuntimeState.strategy_id == strategy_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status_to_paused(self, strategy_id: str) -> bool:
        """C5：将策略状态更新为 PAUSED。须在事务内调用，与 STRATEGY_PAUSED 终态日志同事务。"""
        stmt = (
            update(StrategyRuntimeState)
            .where(StrategyRuntimeState.strategy_id == strategy_id)
            .values(status=STATUS_PAUSED)
        )
        result = await self.session.execute(stmt)
        return result.rowcount == 1

    async def update_status_to_running(self, strategy_id: str) -> bool:
        """B1/C7：将策略状态更新为 RUNNING（仅恢复成功分支内调用，与 STRATEGY_RESUMED 终态日志同事务）。"""
        stmt = (
            update(StrategyRuntimeState)
            .where(StrategyRuntimeState.strategy_id == strategy_id)
            .values(status=STATUS_RUNNING)
        )
        result = await self.session.execute(stmt)
        return result.rowcount == 1
