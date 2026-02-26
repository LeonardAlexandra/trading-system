"""
Phase2.0 C4：StrategyVersionRepository（策略版本只读访问）

本仓储仅提供策略版本的只读查询能力，满足 C4：
- get_by_id(session, version_id)
- list_by_strategy(session, strategy_id)

【口径声明】：
C4 的策略版本可查 = 仅覆盖已产生 evaluation_report 的 strategy_version_id。
由于当前代码库未定义独立的 strategy_version 表，本实现以 evaluation_report 表中的
(strategy_id, strategy_version_id) 作为“版本存在性与列表”的只读推导来源（方案B）。

实现约定：
- 仅仅读取 Phase 2.0 表 evaluation_report，不对 Phase 1.2 任何表执行写操作；
- This API MUST NOT mutate any Phase 1.2 data.
"""
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.evaluation_report import EvaluationReport


@dataclass(frozen=True)
class StrategyVersionView:
    """
    只读视图：基于 evaluation_report 聚合得到的策略版本信息。
    不引入新的持久化表结构，仅用于 C4 查询。
    """

    strategy_id: str
    strategy_version_id: str


class StrategyVersionRepository:
    """
    策略版本只读仓储（C4 T2.0-4）：
    - get_by_id(version_id) -> StrategyVersionView? （按 strategy_version_id 查询一条）
    - list_by_strategy(strategy_id) -> list[StrategyVersionView]

    数据来源：Phase 2.0 表 evaluation_report。
    不对 Phase 1.2 表执行任何写操作。
    This API MUST NOT mutate any Phase 1.2 data.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, version_id: str) -> Optional[StrategyVersionView]:
        """
        按 strategy_version_id 查询一个策略版本视图。
        使用 evaluation_report 中首条匹配记录的 strategy_id 作为归属。
        """
        stmt = (
            select(EvaluationReport)
            .where(EvaluationReport.strategy_version_id == version_id)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        row: Optional[EvaluationReport] = result.scalar_one_or_none()
        if row is None:
            return None
        return StrategyVersionView(
            strategy_id=row.strategy_id,
            strategy_version_id=row.strategy_version_id,
        )

    async def list_by_strategy(self, strategy_id: str) -> List[StrategyVersionView]:
        """
        按 strategy_id 查询所有已存在评估报告的 strategy_version_id 列表（去重）。
        仅仅读取 evaluation_report。
        结果按 strategy_version_id 升序排列（稳定排序）。
        """
        stmt = (
            select(EvaluationReport.strategy_version_id)
            .where(EvaluationReport.strategy_id == strategy_id)
            .distinct()
            .order_by(EvaluationReport.strategy_version_id.asc())
        )
        result = await self.session.execute(stmt)
        versions: List[str] = [row[0] for row in result.all()]
        return [
            StrategyVersionView(strategy_id=strategy_id, strategy_version_id=vid)
            for vid in versions
        ]

