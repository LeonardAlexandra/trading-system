"""
Phase2.0 C2 / B.2：MetricsResult（指标计算结果）

仅含 B.2/C.1 五指标；不包含 conclusion、comparison_summary、baseline 或「建议」。
MetricsCalculator.compute 的返回值类型。
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class MetricsResult:
    """
    B.2 五指标（与 C.1 metrics_snapshot 字段一致）。
    禁止包含 conclusion、comparison_summary、baseline 或未文档化字段。
    """
    trade_count: int
    win_rate: Optional[Decimal]
    realized_pnl: Decimal
    # max_drawdown：基于逐笔累计权益曲线的最大回撤；无 trade 或仅一笔 trade 时固定为 Decimal("0")。
    max_drawdown: Decimal
    avg_holding_time_sec: Optional[Decimal]
