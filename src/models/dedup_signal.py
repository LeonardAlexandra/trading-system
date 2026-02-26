"""
信号去重表模型（Phase1.0 封版：含 processed 字段，MVP 约束 4）
"""
from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.sql import func, text
from src.database.connection import Base


class DedupSignal(Base):
    """信号去重表（signal_id 唯一键保证永久去重；processed 字段存在供审计/更新，去重判定仅依赖 signal_id）"""
    
    __tablename__ = "dedup_signal"
    
    signal_id = Column(String(100), primary_key=True)  # 唯一键，保证永久去重
    first_seen_at = Column(DateTime(timezone=True), nullable=False)  # 首次接收时间（审计用）
    received_at = Column(DateTime(timezone=True), nullable=False)  # 当前接收时间（审计用）
    processed = Column(Boolean, default=False, server_default=text("0"), nullable=False)  # 是否已处理（封版要求存在，可更新）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 唯一约束：signal_id 为 PRIMARY KEY
    # 插入冲突即判定重复
