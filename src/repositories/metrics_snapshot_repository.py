"""
Phase2.0 C1：MetricsRepository（仅读写 Phase 2.0 表 metrics_snapshot）

接口契约以交付包 C1 与蓝本 D.1 为唯一口径：
- write(snapshot) -> None：仅写入 metrics_snapshot 表。
- get_by_strategy_period(strategy_id, period_start, period_end)：精确匹配 period_start 与 period_end。
- get_by_strategy_time_range(strategy_id, start_ts, end_ts)：与 [start_ts, end_ts] 存在重叠的快照。
- get_by_strategy_version(strategy_version_id)：按策略版本查询，仅读 metrics_snapshot，结果按 period_start 升序（满足“按策略/版本/时间段查询”）。

This API MUST NOT mutate any Phase 1.2 data.
"""
from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.metrics_snapshot import MetricsSnapshot


class MetricsRepository:
    """
    指标快照仓储：仅读写 metrics_snapshot 表（蓝本 D.1）。
    不包含业务判断或指标计算；字段严格为 A1/B.2/C.1 文档化字段。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(self, snapshot: MetricsSnapshot) -> None:
        """仅写入 metrics_snapshot 表；不读写 Phase 1.2 表（D.1）。"""
        self.session.add(snapshot)

    async def get_by_strategy_period(
        self,
        strategy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> List[MetricsSnapshot]:
        """
        按 strategy_id 与精确 period 查询（period_start == 给定值 AND period_end == 给定值）。
        仅读 metrics_snapshot（D.1）。
        """
        stmt = (
            select(MetricsSnapshot)
            .where(
                MetricsSnapshot.strategy_id == strategy_id,
                MetricsSnapshot.period_start == period_start,
                MetricsSnapshot.period_end == period_end,
            )
            .order_by(MetricsSnapshot.period_start)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_strategy_time_range(
        self,
        strategy_id: str,
        start_ts: datetime,
        end_ts: datetime,
    ) -> List[MetricsSnapshot]:
        """
        按 strategy_id 与时间范围查询：返回快照区间 [period_start, period_end] 与 [start_ts, end_ts] 存在重叠的记录。
        重叠条件：period_start <= end_ts AND period_end >= start_ts。仅读 metrics_snapshot（D.1）。
        """
        stmt = (
            select(MetricsSnapshot)
            .where(
                MetricsSnapshot.strategy_id == strategy_id,
                MetricsSnapshot.period_start <= end_ts,
                MetricsSnapshot.period_end >= start_ts,
            )
            .order_by(MetricsSnapshot.period_start)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_strategy_version(self, strategy_version_id: str) -> List[MetricsSnapshot]:
        """
        按 strategy_version_id 查询，仅读 metrics_snapshot；结果按 period_start 升序（锁死排序）。
        不触碰 Phase 1.2 表；不引入指标计算、Evaluator、baseline、结论等语义。
        """
        stmt = (
            select(MetricsSnapshot)
            .where(MetricsSnapshot.strategy_version_id == strategy_version_id)
            .order_by(MetricsSnapshot.period_start)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
