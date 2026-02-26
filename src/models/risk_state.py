"""
风控状态表（PR9：冷却时间等，key = strategy_id|symbol|side）
"""
from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from src.database.connection import Base


class RiskState(Base):
    """风控状态（如冷却 last_allowed_at）"""
    __tablename__ = "risk_state"

    key = Column(String(200), primary_key=True)  # e.g. strat|BTCUSDT|BUY
    last_allowed_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
