"""
Phase2.0 C2：MetricsCalculator（T2.0-2）

按 B.2 写死的口径从 Phase 1.2 只读数据计算指标。
不知道 baseline、不产出结论、不写 evaluation_report；禁止对 Phase 1.2 任何表执行写操作。
This API MUST NOT mutate any Phase 1.2 data.
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from src.models.trade import Trade
from src.phase2.metrics_result import MetricsResult
from src.repositories.trade_repo import TradeRepository


class MetricsCalculator:
    """
    按 B.2 口径从 trade 表只读计算五指标。
    仅依赖 TradeRepository 只读接口；不写 Phase 1.2 表；不输出 conclusion、comparison_summary、baseline 或「建议」。
    """

    def __init__(self, trade_repository: TradeRepository) -> None:
        self._trade_repo = trade_repository

    async def compute(
        self,
        strategy_id: str,
        strategy_version_id: str,
        param_version_id: Optional[str],
        period_start: datetime,
        period_end: datetime,
    ) -> MetricsResult:
        """
        计算 B.2 五指标：仅只读 trade 表，不写任何表。
        strategy_version_id / param_version_id 为入参（当前 trade 表无此列，仅按 strategy_id + 时间范围取 trade）。
        """
        trades = await self._trade_repo.list_by_strategy_and_executed_time_range(
            strategy_id, period_start, period_end
        )
        return _compute_b2_metrics(trades)


def _compute_b2_metrics(trades: List[Trade]) -> MetricsResult:
    """
    B.2 口径（写死）：
    - trade_count = COUNT(trade_id)，无 trade 时为 0
    - win_rate = 盈利笔数/总笔数，无 trade 时为 None
    - realized_pnl = SUM(realized_pnl)，无 trade 时为 0
    - max_drawdown = 基于逐笔成交后累计权益曲线；无 trade 或仅一笔时固定为 Decimal("0")
    - avg_holding_time_sec = AVG(close_time - open_time) 秒，无 trade 或缺少时间字段时为 None
    """
    n = len(trades)
    if n == 0:
        return MetricsResult(
            trade_count=0,
            win_rate=None,
            realized_pnl=Decimal("0"),
            max_drawdown=Decimal("0"),
            avg_holding_time_sec=None,
        )

    realized_pnl = sum(
        (t.realized_pnl if t.realized_pnl is not None else Decimal("0")) for t in trades
    )
    winning = sum(1 for t in trades if (t.realized_pnl or Decimal("0")) > 0)
    win_rate = (Decimal(winning) / Decimal(n)) if n else None

    # 权益曲线：按 executed_at 已排序，equity[i] = sum(realized_pnl[0..i])
    peak = Decimal("0")
    max_dd = Decimal("0")
    running = Decimal("0")
    for t in trades:
        running += t.realized_pnl if t.realized_pnl is not None else Decimal("0")
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    # avg_holding_time_sec：Trade 表无 open_time/close_time，按 B.2 缺少时间字段时为 NULL
    avg_holding_time_sec: Optional[Decimal] = None

    return MetricsResult(
        trade_count=n,
        win_rate=win_rate,
        realized_pnl=realized_pnl,
        max_drawdown=max_dd,
        avg_holding_time_sec=avg_holding_time_sec,
    )
