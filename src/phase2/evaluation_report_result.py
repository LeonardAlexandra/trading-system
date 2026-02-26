"""
Phase2.0 C3：评估报告内存类型（0.2 Evaluator Contract）

必含：objective_definition、constraint_definition、baseline_version_id、conclusion、
comparison_summary，及关联的 metrics 摘要或 metrics_snapshot_id。
禁止出现「建议参数」「可写回」「供优化」等语义。
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class EvaluationReportResult:
    """
    评估报告内存结果（0.2 五项 + 关联字段）。
    baseline_version_id 仅 strategy_version_id 或 null；禁止 param_version_id。
    """
    strategy_id: str
    strategy_version_id: str
    param_version_id: Optional[str]
    evaluated_at: datetime
    period_start: datetime
    period_end: datetime
    objective_definition: Dict[str, Any]
    constraint_definition: Dict[str, Any]
    baseline_version_id: Optional[str]
    conclusion: str  # pass / fail / grade，禁止「建议参数」等
    comparison_summary: Optional[Dict[str, Any]]  # 与基线对比摘要，禁止「可写回」「供优化」
    metrics_snapshot_id: Optional[int]
    # 可选：当前周期指标摘要（便于调用方使用，不持久化到 report 的未文档化键）
    trade_count: int = 0
    win_rate: Optional[Any] = None
    realized_pnl: Any = None
    max_drawdown: Optional[Any] = None
    avg_holding_time_sec: Optional[Any] = None
