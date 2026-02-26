"""
Phase2.0 A1/C1：metrics_snapshot 表（指标快照，Phase 2.0 自有）

仅结构定义，用于 ORM 与 MetricsRepository。本表为 Phase 2.0 自有表；
禁止对 Phase 1.2 任何表执行写操作。字段与蓝本 B.2/C.1 一致，无未文档化列。
"""
from sqlalchemy import Column, DateTime, BigInteger, Integer, String, Numeric
from sqlalchemy.sql import func

from src.database.connection import Base


class MetricsSnapshot(Base):
    """
    指标快照表（Phase2.0 蓝本 C.1/B.2）。
    仅存 B.2/C.1 文档化字段：strategy_id、strategy_version_id、param_version_id、
    period_start、period_end、trade_count、win_rate、realized_pnl、max_drawdown、
    avg_holding_time_sec、created_at。
    """
    __tablename__ = "metrics_snapshot"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    strategy_id = Column(String(64), nullable=False)
    strategy_version_id = Column(String(64), nullable=False)
    param_version_id = Column(String(64), nullable=True)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    trade_count = Column(Integer(), nullable=False)
    win_rate = Column(Numeric(18, 6), nullable=True)
    realized_pnl = Column(Numeric(20, 8), nullable=False)
    max_drawdown = Column(Numeric(20, 8), nullable=True)
    avg_holding_time_sec = Column(Numeric(18, 6), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
