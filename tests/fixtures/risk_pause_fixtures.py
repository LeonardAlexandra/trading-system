"""
Phase1.1 D3：可控风控失败场景 fixture

构造使 RiskManager full_check 必然不通过的参数（不绕过 RiskManager），
用于 C4 → C5 → C6 全链路集成测试。不依赖真实超仓业务数据。
"""
from decimal import Decimal

from src.execution.position_manager import ReconcileItem
from src.execution.risk_config import RiskConfig


# D3 策略 ID，与 test_risk_pause_flow 及 webhook 请求一致
D3_STRATEGY_ID = "D3_RISK_PAUSE_STRAT"

# 风控上限：max_position_qty=0.01，同步数量 1 → full_check 必然不通过
D3_RISK_MAX_POSITION_QTY = Decimal("0.01")
D3_RECONCILE_QUANTITY = Decimal("1")


def risk_config_that_fails() -> RiskConfig:
    """返回会使 full_check 不通过的 RiskConfig（仓位超限）。"""
    return RiskConfig(max_position_qty=D3_RISK_MAX_POSITION_QTY)


def reconcile_item_that_triggers_risk_fail() -> ReconcileItem:
    """返回一条会使同步后持仓超限的 ReconcileItem（mock 数据）。"""
    return ReconcileItem(
        external_trade_id="d3-risk-pause-001",
        symbol="BTCUSDT",
        side="BUY",
        quantity=D3_RECONCILE_QUANTITY,
        fallback_price=Decimal("50000"),
    )
