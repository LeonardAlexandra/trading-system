"""
交易记录表模型（Phase1.0 封版 PR2；Phase1.1 A2 EXTERNAL_SYNC 支持）
"""
from sqlalchemy import Boolean, Column, DateTime, Numeric, String, UniqueConstraint, text
from sqlalchemy.sql import func

from src.database.connection import Base

# Phase1.1 A2：来源类型，下游以 source_type 识别；EXTERNAL_SYNC 用于对账路径
SOURCE_TYPE_SIGNAL = "SIGNAL"
SOURCE_TYPE_EXTERNAL_SYNC = "EXTERNAL_SYNC"


class Trade(Base):
    """
    交易记录表（Active + Shadow）。
    Phase 1.0 不实现 Shadow，is_simulated 恒 False；paper 模式均为 False，实盘 Active 交易也为 False。
    Phase1.1 A2：source_type 区分信号驱动(SIGNAL)与外部同步(EXTERNAL_SYNC)；EXTERNAL_SYNC 幂等键 (strategy_id, external_trade_id)。
    """
    __tablename__ = "trade"

    trade_id = Column(String(100), primary_key=True)
    strategy_id = Column(String(50), nullable=False)
    source_type = Column(
        String(50),
        nullable=False,
        server_default=text("'SIGNAL'"),
        comment="SIGNAL=信号驱动，EXTERNAL_SYNC=对账/外部同步",
    )
    external_trade_id = Column(
        String(200),
        nullable=True,
        comment="外部成交 ID；EXTERNAL_SYNC 时必填，与 strategy_id 构成幂等键",
    )
    signal_id = Column(String(100), nullable=True)  # 信号驱动时必填；EXTERNAL_SYNC 可空
    decision_id = Column(String(100), nullable=True)  # 信号驱动时必填；EXTERNAL_SYNC 可空
    execution_id = Column(String(100), nullable=True)  # 信号驱动时必填；EXTERNAL_SYNC 可空
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # "BUY" | "SELL"
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    slippage = Column(Numeric(20, 8), default=0)
    realized_pnl = Column(Numeric(20, 8), default=0)
    executed_at = Column(DateTime(timezone=True), nullable=False)
    is_simulated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "strategy_id",
            "external_trade_id",
            name="uq_trade_strategy_external_trade_id",
        ),
        {"comment": "交易记录表（Active + Shadow）"},
    )
