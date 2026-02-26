"""
执行事件表模型（PR8：audit/events 落库）
严禁存 raw payload、secret、签名；message 仅人类可读、不含敏感信息。
id 由 append_event 应用层统一生成 uuid，nullable=False。
"""
from sqlalchemy import Boolean, Column, String, DateTime, Integer, Text, Index
from sqlalchemy.sql import func
from src.database.connection import Base


class ExecutionEvent(Base):
    """
    执行事件表（按 decision_id 查询，按 created_at 顺序审计）。
    事件类型与 reason_code 使用稳定枚举常量。
    """
    __tablename__ = "execution_events"
    __table_args__ = (
        Index("ix_execution_events_decision_created", "decision_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, nullable=False)  # 由 append_event 统一生成
    decision_id = Column(String(100), nullable=False, index=True)
    event_type = Column(String(40), nullable=False)
    status = Column(String(20), nullable=True)  # 与 decision_order_map.status 对齐快照
    reason_code = Column(String(40), nullable=True)
    message = Column(Text, nullable=True)  # 人类可读，不含敏感信息
    exchange_order_id = Column(String(100), nullable=True)
    attempt_count = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # PR13：账户/交易所追溯、Dry-run 标记
    account_id = Column(String(80), nullable=True)
    exchange_profile = Column(String(80), nullable=True)
    dry_run = Column(Boolean, nullable=True, default=False)
    # PR14a：实盘门禁追溯（live_enabled 时配置，可区分 live vs dry_run）
    live_enabled = Column(Boolean, nullable=True, default=False)
    # PR16/PR16c：演练模式追溯；唯一权威来源为本列，message 不再含 "rehearsal=" 字样
    rehearsal = Column(Boolean, nullable=True, default=False)
