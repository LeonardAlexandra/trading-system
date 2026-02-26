"""
PR14a：限频状态表（按 account_id 维度，多实例共享）
"""
from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.sql import func
from src.database.connection import Base


class RateLimitState(Base):
    """限频状态：account_id 维度，窗口内计数。"""
    __tablename__ = "rate_limit_state"

    account_id = Column(String(80), primary_key=True)
    window_start_utc = Column(DateTime(timezone=True), nullable=False)
    count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
