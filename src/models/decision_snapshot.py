"""
Phase1.2 A1：decision_snapshot 表（决策输入快照，落实 0.4）

仅结构定义，用于 ORM/只读层。本表仅追加、不可变；禁止提供按 decision_id 或 id 的 UPDATE/DELETE。
Repository（save / get_by_decision_id / list_by_strategy_time）由 C1 实现，本模块不实现。
"""
from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from src.database.connection import Base


class DecisionSnapshot(Base):
    """
    决策输入快照表（Phase1.2 蓝本 C.1）。
    快照内容必须为本次决策实际使用的输入状态；写入后为不可变历史记录。
    """
    __tablename__ = "decision_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(String(64), nullable=False, unique=True)
    strategy_id = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    signal_state = Column(JSON(), nullable=False)  # 本次决策实际使用的信号输入
    position_state = Column(JSON(), nullable=False)  # 本次决策时刻实际使用的持仓输入
    risk_check_result = Column(JSON(), nullable=False)  # 本次决策前风控实际结果
    decision_result = Column(JSON(), nullable=False)  # 最终决策结果

    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_decision_snapshot_decision_id"),
    )
