"""
Phase2.0 C3 / B.1：评估配置（objective_definition、constraint_definition）

最小结构化字段集，禁止未文档化顶层键。蓝本 B.1。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# B.1 primary 枚举
PRIMARY_OBJECTIVES = ("pnl", "sharpe", "max_drawdown", "win_rate", "trade_count")


def default_objective_definition() -> Dict[str, Any]:
    """B.1 objective_definition 最小字段集默认值。"""
    return {
        "primary": "pnl",
        "primary_weight": 1.0,
        "secondary": [],
        "secondary_weights": [],
    }


def default_constraint_definition() -> Dict[str, Any]:
    """B.1 constraint_definition 最小字段集默认值（均不约束）。"""
    return {
        "max_drawdown_pct": None,
        "min_trade_count": None,
        "max_risk_exposure": None,
        "custom": None,
    }


def normalize_objective_definition(obj: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    规范为 B.1 仅允许的顶层键：primary, primary_weight, secondary, secondary_weights。
    禁止未文档化顶层键；缺失键用默认值补全。
    """
    base = default_objective_definition()
    if not obj:
        return base
    allowed = {"primary", "primary_weight", "secondary", "secondary_weights"}
    for k in allowed:
        if k in obj:
            base[k] = obj[k]
    return base


def normalize_constraint_definition(obj: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    规范为 B.1 仅允许的顶层键：max_drawdown_pct, min_trade_count, max_risk_exposure, custom。
    禁止未文档化顶层键；缺失键用 null 补全。
    """
    base = default_constraint_definition()
    if not obj:
        return base
    allowed = {"max_drawdown_pct", "min_trade_count", "max_risk_exposure", "custom"}
    for k in allowed:
        if k in obj:
            base[k] = obj[k]
    return base


@dataclass(frozen=True)
class EvaluatorConfig:
    """
    Evaluator.evaluate 的 config 入参。
    baseline_version_id 必须为 strategy_version_id 或 null，禁止 param_version_id。
    """
    objective_definition: Dict[str, Any] = field(default_factory=default_objective_definition)
    constraint_definition: Dict[str, Any] = field(default_factory=default_constraint_definition)
    baseline_version_id: Optional[str] = None  # 仅 strategy_version_id 或 null

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "objective_definition",
            normalize_objective_definition(self.objective_definition),
        )
        object.__setattr__(
            self,
            "constraint_definition",
            normalize_constraint_definition(self.constraint_definition),
        )
