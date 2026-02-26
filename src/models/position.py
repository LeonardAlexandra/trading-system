"""
Paper 持仓表（PR9：风控上下文，LONG-only；PR11：按 strategy_id 隔离）
"""
from sqlalchemy import Column, String, DateTime, Numeric, text, UniqueConstraint
from sqlalchemy.sql import func
from src.database.connection import Base


class Position(Base):
    """Paper 持仓（strategy_id + symbol 唯一，本阶段 LONG-only，按策略隔离）"""
    __tablename__ = "positions"

    strategy_id = Column(String(100), primary_key=True)
    symbol = Column(String(20), primary_key=True)
    side = Column(String(10), nullable=False, server_default=text("'LONG'"))
    quantity = Column(Numeric(20, 8), nullable=False, server_default=text("0"))
    avg_price = Column(Numeric(20, 8), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
