"""
Phase2.1 B.1/B.4：可学习参数白名单（唯一事实源）

所有 Optimizer/写回校验均从此模块读取白名单；
禁止在代码其他位置另维护一套白名单列表（防止文档与代码不一致）。
白名单变更须经门禁与审计（B.4 写死）。
"""
from typing import Dict, FrozenSet, Any

# ── 白名单参数键（写死；与 docs/plan/Phase2.1开发交付包.md B.1 表格一致）──
LEARNABLE_PARAM_KEYS: FrozenSet[str] = frozenset(
    [
        "max_position_size",   # 最大持仓量
        "fixed_order_size",    # 固定下单量
        "stop_loss_pct",       # 止损比例
        "take_profit_pct",     # 止盈比例
    ]
)

# ── 参数类型约束（用于校验值类型）──
LEARNABLE_PARAM_TYPES: Dict[str, type] = {
    "max_position_size": float,
    "fixed_order_size": float,
    "stop_loss_pct": float,
    "take_profit_pct": float,
}


class WhitelistViolation(Exception):
    """建议参数中含有白名单外的键，或值类型不合法。"""


def validate_params(params: Dict[str, Any]) -> None:
    """
    校验参数字典仅含白名单键且值类型合法。
    不满足时抛 WhitelistViolation（禁止静默忽略）。
    """
    illegal_keys = set(params.keys()) - LEARNABLE_PARAM_KEYS
    if illegal_keys:
        raise WhitelistViolation(
            f"参数含非白名单键，禁止写回：{sorted(illegal_keys)}"
        )
    for key, val in params.items():
        expected_type = LEARNABLE_PARAM_TYPES.get(key)
        if expected_type is not None and val is not None:
            if not isinstance(val, (int, float)):
                raise WhitelistViolation(
                    f"参数 {key!r} 值类型不合法，期望数值，实际: {type(val).__name__}"
                )
            if float(val) < 0:
                raise WhitelistViolation(
                    f"参数 {key!r} 值不能为负数，实际: {val}"
                )


def filter_to_whitelist(params: Dict[str, Any]) -> Dict[str, Any]:
    """仅保留白名单内的键，过滤掉其他键（用于防御性清洗）。"""
    return {k: v for k, v in params.items() if k in LEARNABLE_PARAM_KEYS}
