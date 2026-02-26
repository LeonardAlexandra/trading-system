"""
Paper 账户余额表（PR9：风控上下文）
"""
from sqlalchemy import Column, String, DateTime, Numeric, text
from sqlalchemy.sql import func
from src.database.connection import Base


class Balance(Base):
    """Paper 账户余额（asset 唯一）"""
    __tablename__ = "balances"

    asset = Column(String(20), primary_key=True)
    available = Column(Numeric(20, 8), nullable=False, server_default=text("0"))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
