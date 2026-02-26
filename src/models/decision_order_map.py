"""
决策订单映射表模型（PR5 占位 + PR6 执行扩展）
"""
from sqlalchemy import Column, String, DateTime, Integer, Text, Numeric, text
from sqlalchemy.sql import func
from src.database.connection import Base
from src.models.decision_order_map_status import DEFAULT_STATUS


class DecisionOrderMap(Base):
    """
    决策订单映射表（decision_id 唯一键保证幂等，支持两段式幂等：先占位后下单）
    
    状态流转（PR6 最小状态机）：RESERVED → SUBMITTING → FILLED / FAILED
    """
    
    __tablename__ = "decision_order_map"
    
    decision_id = Column(String(100), primary_key=True)
    local_order_id = Column(String(100), nullable=True)
    exchange_order_id = Column(String(100), nullable=True)
    status = Column(
        String(20),
        default=DEFAULT_STATUS,
        server_default=text("'RESERVED'"),
        nullable=False,
    )
    reserved_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # PR6 执行所需：执行层读取 symbol/side/qty/strategy_id
    signal_id = Column(String(100), nullable=True)
    strategy_id = Column(String(100), nullable=True)
    symbol = Column(String(20), nullable=True)
    side = Column(String(10), nullable=True)
    quantity = Column(Numeric(20, 8), nullable=True, server_default=text("1"))  # 执行数量，数值型便于风控/计算
    
    # PR6 重试与退避
    attempt_count = Column(Integer, server_default=text("0"))
    last_error = Column(Text, nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
