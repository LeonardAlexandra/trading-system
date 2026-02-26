"""
PR14a：断路器状态表（按 account_id 维度，多实例共享）
"""
from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.sql import func
from src.database.connection import Base


class CircuitBreakerState(Base):
    """断路器状态：account_id 维度，失败计数与熔断 until。"""
    __tablename__ = "circuit_breaker_state"

    account_id = Column(String(80), primary_key=True)
    failures_count = Column(Integer, nullable=False, default=0)
    opened_at_utc = Column(DateTime(timezone=True), nullable=True)  # 熔断打开时间
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
