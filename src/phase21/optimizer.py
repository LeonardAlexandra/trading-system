"""
Phase2.1 T2.1-1：Optimizer / Learner

职责：
- 仅读 Phase 2.0 的 evaluation_report（由调用方传入报告对象，禁止自行扫描 trade 表）。
- 基于评估结论与指标，产出白名单参数建议（ParamSuggestion）。
- 写 learning_audit 记录（strategy_id, evaluation_report_id 引用, suggested_params）。
- 禁止：写 evaluation_report / metrics_snapshot；引用 trade / decision_snapshot 表。

约束（写死）：
- B.5：输入仅为 Phase 2.0 的 evaluation_report，禁止自建第二套评估。
- B.1/B.4：建议参数仅含白名单键，通过 whitelist.validate_params 强制校验。
- B.6：禁止污染 Phase 2.0 表。
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.models.learning_audit import LearningAudit
from src.models.evaluation_report import EvaluationReport
from src.phase21.whitelist import LEARNABLE_PARAM_KEYS, validate_params, WhitelistViolation
from src.repositories.learning_audit_repository import LearningAuditRepository


@dataclass
class ParamSuggestion:
    """Optimizer 产出的参数建议（仅含白名单键）。"""
    strategy_id: str
    evaluation_report_id: str          # Phase 2.0 报告 ID（字符串引用，不含报告内容）
    param_version_id_candidate: str    # 生成的候选 param_version_id
    suggested_params: Dict[str, Any]   # 仅白名单参数
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class OptimizerError(Exception):
    pass


class Optimizer:
    """
    参数建议器：基于 Phase 2.0 评估报告产出白名单参数建议。

    ──调用方须保证──
    - 传入的 report 来自 EvaluationReportRepository（Phase 2.0 查询结果）。
    - 禁止传入 trade / execution / decision_snapshot 等 Phase 1.2 原始数据。
    """

    def __init__(self, learning_audit_repo: LearningAuditRepository) -> None:
        self._audit_repo = learning_audit_repo

    async def suggest(
        self,
        report: EvaluationReport,
        current_params: Dict[str, Any],
        *,
        param_version_id: Optional[str] = None,
    ) -> ParamSuggestion:
        """
        基于评估报告产出参数建议。

        算法（保守策略，满足 MVP 闭环需求）：
        - 若评估结论为 "fail"（存在 constraint violation），尝试保守调整止损 / 止盈。
        - 若结论为 "pass"，维持当前参数不变（稳定优先）。
        - 所有建议参数必须通过 validate_params 白名单校验。

        param_version_id：若调用方已生成 ID 则复用，否则自动生成 UUID。
        """
        # 只允许读取 report.id / report.strategy_id / report.conclusion 等已有字段
        # 禁止通过 report 反查 trade 表
        strategy_id = report.strategy_id
        report_id = str(report.id)

        candidate_id = param_version_id or f"pv-{uuid.uuid4().hex[:12]}"

        # ── 建议逻辑（保守 MVP 版本）──
        suggested = self._compute_suggestion(report, current_params)

        # 白名单强制校验（禁止静默忽略违规）
        try:
            validate_params(suggested)
        except WhitelistViolation as e:
            raise OptimizerError(f"白名单校验失败：{e}") from e

        # 写 learning_audit（仅存 ID 引用，不存报告内容）
        audit = LearningAudit(
            strategy_id=strategy_id,
            evaluation_report_id=report_id,
            param_version_id_candidate=candidate_id,
            suggested_params=suggested,
        )
        await self._audit_repo.append(audit)

        return ParamSuggestion(
            strategy_id=strategy_id,
            evaluation_report_id=report_id,
            param_version_id_candidate=candidate_id,
            suggested_params=suggested,
            created_at=datetime.now(timezone.utc),
        )

    def _compute_suggestion(
        self,
        report: EvaluationReport,
        current_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        保守参数建议算法：
        - 只调整白名单内参数。
        - fail 时按 comparison_summary 中 constraint_violations 决策。
        - pass 时不变。
        """
        # 仅保留白名单键的当前参数
        base: Dict[str, Any] = {
            k: v for k, v in current_params.items() if k in LEARNABLE_PARAM_KEYS
        }
        conclusion = (report.conclusion or "").strip().lower()
        if conclusion != "fail":
            # 结论 pass 时，维持当前参数（稳定优先）
            return dict(base)

        # 结论 fail：检查 constraint_violations
        summary = report.comparison_summary or {}
        violations = summary.get("constraint_violations", [])

        result = dict(base)

        if "max_drawdown_pct" in violations or "max_risk_exposure" in violations:
            # 回撤超标：收紧止损（减少 10%），缩减仓位（减少 10%）
            sl = float(result.get("stop_loss_pct", 0.05))
            result["stop_loss_pct"] = round(max(0.01, sl * 0.9), 6)
            pos = float(result.get("max_position_size", 1.0))
            result["max_position_size"] = round(max(0.01, pos * 0.9), 6)
            order_sz = float(result.get("fixed_order_size", 0.1))
            result["fixed_order_size"] = round(max(0.001, order_sz * 0.9), 6)

        if "min_trade_count" in violations:
            # 交易笔数不足：放宽止盈（增加 10%），提高订单量（增加 5%）
            tp = float(result.get("take_profit_pct", 0.05))
            result["take_profit_pct"] = round(tp * 1.1, 6)
            order_sz = float(result.get("fixed_order_size", 0.1))
            result["fixed_order_size"] = round(order_sz * 1.05, 6)

        return result
