"""
Phase2.0 C3：Evaluator（T2.0-3）

只读 Phase 1.2 与 MetricsCalculator 输出（或 metrics_snapshot）；做版本比较与结论生成；
仅写入 evaluation_report；不自行从 trade 计算指标；禁止对 Phase 1.2 任何表写操作；
禁止输出「建议参数」/写回/发布/回滚语义。
This API MUST NOT mutate any Phase 1.2 data.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.models.evaluation_report import EvaluationReport
from src.models.metrics_snapshot import MetricsSnapshot
from src.phase2.evaluation_config import (
    EvaluatorConfig,
    normalize_constraint_definition,
    normalize_objective_definition,
)
from src.phase2.evaluation_report_result import EvaluationReportResult
from src.phase2.metrics_result import MetricsResult
from src.repositories.evaluation_report_repository import EvaluationReportRepository
from src.repositories.metrics_snapshot_repository import MetricsRepository


def _collect_constraint_violations(metrics: MetricsResult, constraint: Dict[str, Any]) -> List[str]:
    """
    按 B.1 constraint_definition 判定当前指标是否满足约束。
    仅使用可解释的约束：min_trade_count；max_drawdown_pct/max_risk_exposure 在无口径时暂不判定。
    禁止输出「建议参数」「可写回」「供优化」。
    """
    violations: List[str] = []
    min_trade = constraint.get("min_trade_count")
    if min_trade is not None and metrics.trade_count < int(min_trade):
        violations.append("min_trade_count")

    max_dd_pct = constraint.get("max_drawdown_pct")
    # 选项：将 max_drawdown_pct 视为「最大允许回撤绝对值阈值」（与 B.2 max_drawdown 单位一致）。
    # 若 metrics.max_drawdown 大于该阈值，则不满足约束。
    if max_dd_pct is not None and metrics.max_drawdown is not None:
        if metrics.max_drawdown > Decimal(str(max_dd_pct)):
            violations.append("max_drawdown_pct")

    # 以 B.2 已有 max_drawdown 作为风险暴露判定代理，保证约束可判定与可审计。
    max_risk_exposure = constraint.get("max_risk_exposure")
    if max_risk_exposure is not None and metrics.max_drawdown is not None:
        if metrics.max_drawdown > Decimal(str(max_risk_exposure)):
            violations.append("max_risk_exposure")

    return violations


def _constraint_pass(metrics: MetricsResult, constraint: Dict[str, Any]) -> bool:
    return len(_collect_constraint_violations(metrics, constraint)) == 0


def _build_comparison_summary(
    current: MetricsResult,
    baseline_snapshot: Optional[MetricsSnapshot],
    constraint_violations: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    生成与基线的对比摘要（仅事实对比，禁止「建议参数」「可写回」「供优化」）。
    baseline_version_id 仅 strategy_version_id；comparison_summary 仅数据差异。
    """
    if baseline_snapshot is None:
        if constraint_violations:
            return {"constraint_violations": list(constraint_violations)}
        return None
    cur = {
        "trade_count": current.trade_count,
        "win_rate": float(current.win_rate) if current.win_rate is not None else None,
        "realized_pnl": float(current.realized_pnl) if current.realized_pnl is not None else None,
        "max_drawdown": float(current.max_drawdown) if current.max_drawdown is not None else None,
        "avg_holding_time_sec": (
            float(current.avg_holding_time_sec)
            if current.avg_holding_time_sec is not None
            else None
        ),
    }
    base = {
        "trade_count": baseline_snapshot.trade_count,
        "win_rate": float(baseline_snapshot.win_rate) if baseline_snapshot.win_rate is not None else None,
        "realized_pnl": float(baseline_snapshot.realized_pnl) if baseline_snapshot.realized_pnl is not None else None,
        "max_drawdown": float(baseline_snapshot.max_drawdown) if baseline_snapshot.max_drawdown is not None else None,
        "avg_holding_time_sec": (
            float(baseline_snapshot.avg_holding_time_sec)
            if baseline_snapshot.avg_holding_time_sec is not None
            else None
        ),
    }
    delta = {}
    for k in cur:
        a, b = cur[k], base[k]
        if a is not None and b is not None and isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta[k] = round(a - b, 8) if isinstance(a, float) or isinstance(b, float) else (a - b)
    summary = {"current": cur, "baseline": base, "delta": delta}
    if constraint_violations:
        summary["constraint_violations"] = list(constraint_violations)
    return summary


class Evaluator:
    """
    评估器：调用 MetricsCalculator 或读取 metrics_snapshot，生成结论与对比摘要，仅写 evaluation_report。
    不直接读 trade 表算指标；不写 Phase 1.2 表；不输出「建议参数」、不调用写回/发布/回滚。
    """

    def __init__(
        self,
        metrics_calculator: Any,  # MetricsCalculator
        metrics_repository: MetricsRepository,
        evaluation_report_repository: EvaluationReportRepository,
    ) -> None:
        self._metrics_calculator = metrics_calculator
        self._metrics_repository = metrics_repository
        self._evaluation_report_repository = evaluation_report_repository

    async def evaluate(
        self,
        strategy_id: str,
        strategy_version_id: str,
        param_version_id: Optional[str],
        period_start: datetime,
        period_end: datetime,
        config: Optional[EvaluatorConfig] = None,
    ) -> EvaluationReportResult:
        """
        执行评估：调用 MetricsCalculator.compute 得到指标，可选写入 metrics_snapshot，
        根据 objective/constraint 与 baseline 生成 conclusion、comparison_summary，
        仅写入 evaluation_report 表；返回含 0.2 五项的 EvaluationReportResult。
        """
        cfg = config or EvaluatorConfig()
        obj_def = normalize_objective_definition(cfg.objective_definition)
        con_def = normalize_constraint_definition(cfg.constraint_definition)

        # baseline_version_id 仅允许为 strategy_version_id 或 null，禁止使用 param_version_id。
        if (
            cfg.baseline_version_id is not None
            and param_version_id is not None
            and cfg.baseline_version_id == param_version_id
        ):
            raise ValueError(
                "baseline_version_id 只能为 strategy_version_id 或 null，禁止使用 param_version_id 作为基线"
            )

        # 内部：调用 MetricsCalculator.compute，禁止直接从 trade 表算指标
        metrics = await self._metrics_calculator.compute(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            period_start=period_start,
            period_end=period_end,
        )

        # 写入 metrics_snapshot 以得到 metrics_snapshot_id，但需避免同周期重复写入。
        existing_snapshots = await self._metrics_repository.get_by_strategy_period(
            strategy_id=strategy_id,
            period_start=period_start,
            period_end=period_end,
        )
        reused_snapshot: Optional[MetricsSnapshot] = None
        for s in existing_snapshots:
            if (
                s.strategy_version_id == strategy_version_id
                and s.param_version_id == param_version_id
            ):
                reused_snapshot = s
                break

        if reused_snapshot is not None:
            metrics_snapshot_id = reused_snapshot.id
        else:
            snapshot_orm = MetricsSnapshot(
                strategy_id=strategy_id,
                strategy_version_id=strategy_version_id,
                param_version_id=param_version_id,
                period_start=period_start,
                period_end=period_end,
                trade_count=metrics.trade_count,
                win_rate=metrics.win_rate,
                realized_pnl=metrics.realized_pnl,
                max_drawdown=metrics.max_drawdown,
                avg_holding_time_sec=metrics.avg_holding_time_sec,
            )
            await self._metrics_repository.write(snapshot_orm)
            await self._metrics_repository.session.flush()
            metrics_snapshot_id = snapshot_orm.id

        # 结论：仅 pass/fail，禁止「建议参数」「可写回」「供优化」
        constraint_violations = _collect_constraint_violations(metrics, con_def)
        conclusion = "pass" if len(constraint_violations) == 0 else "fail"

        # 基线对比：baseline_version_id 仅 strategy_version_id
        baseline_snapshot: Optional[MetricsSnapshot] = None
        if cfg.baseline_version_id:
            baseline_list: List[MetricsSnapshot] = await self._metrics_repository.get_by_strategy_version(
                cfg.baseline_version_id
            )
            # 同周期或最近一条
            for s in baseline_list:
                if s.period_start == period_start and s.period_end == period_end:
                    baseline_snapshot = s
                    break
            if baseline_snapshot is None and baseline_list:
                baseline_snapshot = baseline_list[-1]
        comparison_summary = _build_comparison_summary(
            metrics,
            baseline_snapshot,
            constraint_violations=constraint_violations,
        )

        evaluated_at = datetime.now(timezone.utc)
        report_orm = EvaluationReport(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            evaluated_at=evaluated_at,
            period_start=period_start,
            period_end=period_end,
            objective_definition=obj_def,
            constraint_definition=con_def,
            baseline_version_id=cfg.baseline_version_id,
            conclusion=conclusion,
            comparison_summary=comparison_summary,
            metrics_snapshot_id=metrics_snapshot_id,
        )
        await self._evaluation_report_repository.write(report_orm)

        return EvaluationReportResult(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            evaluated_at=evaluated_at,
            period_start=period_start,
            period_end=period_end,
            objective_definition=obj_def,
            constraint_definition=con_def,
            baseline_version_id=cfg.baseline_version_id,
            conclusion=conclusion,
            comparison_summary=comparison_summary,
            metrics_snapshot_id=metrics_snapshot_id,
            trade_count=metrics.trade_count,
            win_rate=metrics.win_rate,
            realized_pnl=metrics.realized_pnl,
            max_drawdown=metrics.max_drawdown,
            avg_holding_time_sec=metrics.avg_holding_time_sec,
        )
