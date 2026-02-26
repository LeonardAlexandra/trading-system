"""
Phase2.0 D1：主流程应用层入口（非 HTTP）。

封装事务边界：strategy/version/time_range -> compute -> evaluate -> commit。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.phase2.evaluation_config import EvaluatorConfig
from src.phase2.evaluation_report_result import EvaluationReportResult
from src.phase2.evaluator import Evaluator
from src.phase2.metrics_calculator import MetricsCalculator
from src.repositories.evaluation_report_repository import EvaluationReportRepository
from src.repositories.metrics_snapshot_repository import MetricsRepository
from src.repositories.trade_repo import TradeRepository


class Phase2MainFlowService:
    """D1 应用层主流程入口，负责会话与事务边界。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def run_main_flow(
        self,
        *,
        strategy_id: str,
        strategy_version_id: str,
        param_version_id: Optional[str],
        period_start: datetime,
        period_end: datetime,
        config: Optional[EvaluatorConfig] = None,
    ) -> EvaluationReportResult:
        async with self._session_factory() as session:
            trade_repo = TradeRepository(session)
            metrics_repo = MetricsRepository(session)
            report_repo = EvaluationReportRepository(session)
            calc = MetricsCalculator(trade_repo)
            evaluator = Evaluator(calc, metrics_repo, report_repo)
            result = await evaluator.evaluate(
                strategy_id=strategy_id,
                strategy_version_id=strategy_version_id,
                param_version_id=param_version_id,
                period_start=period_start,
                period_end=period_end,
                config=config,
            )
            await session.commit()
            return result

    async def query_by_strategy_version(self, strategy_version_id: str):
        async with self._session_factory() as session:
            repo = EvaluationReportRepository(session)
            return await repo.get_by_strategy_version(strategy_version_id)

    async def query_by_evaluated_at(self, strategy_id: str, from_ts: datetime, to_ts: datetime):
        async with self._session_factory() as session:
            repo = EvaluationReportRepository(session)
            return await repo.get_by_evaluated_at(strategy_id, from_ts, to_ts)

    async def query_by_param_version(self, param_version_id: str):
        async with self._session_factory() as session:
            repo = EvaluationReportRepository(session)
            return await repo.get_by_param_version(param_version_id)

    async def query_by_baseline_version(self, baseline_version_id: str):
        async with self._session_factory() as session:
            repo = EvaluationReportRepository(session)
            return await repo.get_by_baseline_version(baseline_version_id)
