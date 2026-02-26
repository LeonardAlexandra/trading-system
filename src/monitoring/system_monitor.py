"""
Phase1.2 C4：SystemMonitor（蓝本 D.4）

get_metrics() 返回至少 signals_received_count, orders_executed_count, error_count, error_rate。
数据来源：真实 DB 查询（dedup_signal / trade / log 表），禁止硬编码。
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.dedup_signal import DedupSignal
from src.models.log_entry import LogEntry
from src.models.trade import Trade

# 默认统计窗口（秒），可配置
DEFAULT_METRICS_WINDOW_SECONDS = 3600


class SystemMonitor:
    """
    系统指标采集。数据来自 DB 表在时间窗口内的计数，禁止假数据。
    """

    def __init__(self, default_window_seconds: int = DEFAULT_METRICS_WINDOW_SECONDS):
        self._default_window_seconds = default_window_seconds

    async def get_metrics(
        self,
        session: AsyncSession,
        window_seconds: int | None = None,
    ) -> Dict[str, Any]:
        """
        返回至少 signals_received_count, orders_executed_count, error_count, error_rate。
        窗口内计数；返回中带 window_seconds 便于复现。
        """
        window = window_seconds if window_seconds is not None else self._default_window_seconds
        now = datetime.now(timezone.utc)
        since = now - timedelta(seconds=window)

        # 信号数：dedup_signal 表 created_at 在窗口内
        stmt_sig = select(func.count()).select_from(DedupSignal).where(DedupSignal.created_at >= since)
        r_sig = await session.execute(stmt_sig)
        signals_received_count = r_sig.scalar() or 0

        # 成交订单数：trade 表 created_at 在窗口内（SIGNAL 来源视为执行成交）
        stmt_ord = select(func.count()).select_from(Trade).where(Trade.created_at >= since)
        r_ord = await session.execute(stmt_ord)
        orders_executed_count = r_ord.scalar() or 0

        # 错误数：log 表 level=ERROR 且 created_at 在窗口内
        stmt_err = (
            select(func.count())
            .select_from(LogEntry)
            .where(
                LogEntry.created_at >= since,
                LogEntry.created_at <= now,
                LogEntry.level == "ERROR",
            )
        )
        r_err = await session.execute(stmt_err)
        error_count = r_err.scalar() or 0

        # error_rate：每小时错误数（窗口按小时折算）
        hours = max(window / 3600.0, 1.0 / 3600.0)
        error_rate = (error_count / hours) if hours else 0.0

        return {
            "signals_received_count": signals_received_count,
            "orders_executed_count": orders_executed_count,
            "error_count": error_count,
            "error_rate": round(error_rate, 6),
            "window_seconds": window,
            "since": since.isoformat(),
            "until": now.isoformat(),
        }
