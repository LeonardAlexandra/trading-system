"""
订单表模型（表名 orders，避免 SQL 关键字冲突）
"""
from sqlalchemy import Column, String, Numeric, DateTime, Index
from sqlalchemy.sql import func
from src.database.connection import Base


class Order(Base):
    """订单表（表名 orders，避免 SQL 关键字冲突）"""
    
    __tablename__ = "orders"  # 改为 orders，避免 SQL 关键字冲突
    
    order_id = Column(String(100), primary_key=True)
    exchange_order_id = Column(String(100))  # 交易所订单 ID
    strategy_id = Column(String(50), nullable=False)
    decision_id = Column(String(100), nullable=False)  # 关联决策（用于幂等）
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # "BUY" | "SELL"
    quantity = Column(Numeric(20, 8), nullable=False)
    filled_quantity = Column(Numeric(20, 8), default=0)
    price = Column(Numeric(20, 8))
    status = Column(String(20), nullable=False)  # "PENDING" | "PARTIAL" | "FILLED" | "CANCELLED" | "REJECTED" | "TIMEOUT" | "UNKNOWN"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 索引（索引名统一为 idx_orders_*，与表名 orders 保持一致）
    __table_args__ = (
        Index('idx_orders_decision_id', 'decision_id'),
        Index('idx_orders_strategy_id', 'strategy_id'),
        Index('idx_orders_status', 'status'),
        {"comment": "订单表"}
    )
