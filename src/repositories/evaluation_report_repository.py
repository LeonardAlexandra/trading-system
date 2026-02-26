"""
Phase2.0 C3/C4：EvaluationReport 仓储

- C3 范围：write(session, report_orm) 仅写入 evaluation_report 表；
- C4 范围：增加只读查询：
  - get_by_strategy_version(strategy_version_id)
  - get_by_evaluated_at(strategy_id, from_ts, to_ts)
  - get_by_param_version(param_version_id)

本仓储仅读写 Phase 2.0 自有表 evaluation_report；
禁止对 Phase 1.2 任何表执行写操作。
This API MUST NOT mutate any Phase 1.2 data.
"""
from datetime import datetime
from typing import List

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.evaluation_report import EvaluationReport


class EvaluationReportRepository:
    """
    评估报告仓储：C3 提供 write，C4 提供只读查询；
    仅读写 Phase 2.0 表 evaluation_report，不读写 Phase 1.2 表。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(self, report: EvaluationReport) -> None:
        """仅写入 evaluation_report 表；不触碰 Phase 1.2 表（蓝本 D.3）。"""
        self.session.add(report)

    async def get_by_strategy_version(
        self,
        strategy_version_id: str,
    ) -> List[EvaluationReport]:
        """
        按 strategy_version_id 查询评估结果列表。
        仅仅读取 evaluation_report。
        """
        stmt = (
            select(EvaluationReport)
            .where(EvaluationReport.strategy_version_id == strategy_version_id)
            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_evaluated_at(
        self,
        strategy_id: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> List[EvaluationReport]:
        """
        按 strategy_id 与 evaluated_at 时间范围查询评估结果。
        仅仅读取 evaluation_report。
        """
        stmt = (
            select(EvaluationReport)
            .where(
                EvaluationReport.strategy_id == strategy_id,
                EvaluationReport.evaluated_at >= from_ts,
                EvaluationReport.evaluated_at <= to_ts,
            )
            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_param_version(
        self,
        param_version_id: str,
    ) -> List[EvaluationReport]:
        """
        按 param_version_id 查询评估结果列表。
        仅仅读取 evaluation_report；baseline_version_id 仍仅引用 strategy_version。
        """
        stmt = (
            select(EvaluationReport)
            .where(EvaluationReport.param_version_id == param_version_id)
            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_baseline_version(
        self,
        baseline_version_id: str,
    ) -> List[EvaluationReport]:
        """
        按 baseline_version_id 查询评估结果列表。
        仅仅读取 evaluation_report；baseline_version_id 仅允许 strategy_version_id。
        """
        stmt = (
            select(EvaluationReport)
            .where(EvaluationReport.baseline_version_id == baseline_version_id)
            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
