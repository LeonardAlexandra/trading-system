"""
Phase1.1 C5：signal_rejection 表（因 PAUSED 拒绝信号的可审计记录）

每次因 PAUSED 拒绝信号时写入一条记录，字段至少包含：策略 ID、signal_id（若有）、
拒绝原因 STRATEGY_PAUSED、时间戳。与「不重复处理同一 signal」语义一致。
"""
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from src.database.connection import Base

REASON_STRATEGY_PAUSED = "STRATEGY_PAUSED"


class SignalRejection(Base):
    """因策略 PAUSED 拒绝信号的可审计记录（C5）。"""

    __tablename__ = "signal_rejection"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(String(100), nullable=False, index=True)
    signal_id = Column(String(200), nullable=True)
    reason = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
