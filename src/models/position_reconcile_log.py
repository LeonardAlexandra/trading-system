"""
Phase1.1 A3：position_reconcile_log 表（对账与审计可追溯日志）

external_trade_id 关联外部成交；event_type 为封闭枚举，以 Phase1.1 文档为唯一真理源，不得新增或改名。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, CheckConstraint
from sqlalchemy.sql import func

from src.database.connection import Base

# Phase1.1 event_type 枚举（唯一真理源），与文档表完全一致，不得新增或改名
RECONCILE_START = "RECONCILE_START"
RECONCILE_END = "RECONCILE_END"
SYNC_TRADE = "SYNC_TRADE"
OVER_POSITION = "OVER_POSITION"
STRATEGY_PAUSED = "STRATEGY_PAUSED"
STRATEGY_RESUMED = "STRATEGY_RESUMED"
RECONCILE_FAILED = "RECONCILE_FAILED"

EVENT_TYPES = frozenset({
    RECONCILE_START,
    RECONCILE_END,
    SYNC_TRADE,
    OVER_POSITION,
    STRATEGY_PAUSED,
    STRATEGY_RESUMED,
    RECONCILE_FAILED,
})


def validate_event_type(value: str) -> bool:
    """仅允许 Phase1.1 封闭枚举值。"""
    return value in EVENT_TYPES


class PositionReconcileLog(Base):
    """
    对账与状态变更审计日志（A3）。
    写入须与对账/挂起/恢复关键步骤在同一事务或一致性边界内。
    """
    __tablename__ = "position_reconcile_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(String(100), nullable=False, index=True)
    external_trade_id = Column(
        String(200),
        nullable=True,
        comment="关联外部/交易所成交 ID，非 EXTERNAL_SYNC 场景可空",
    )
    event_type = Column(
        String(50),
        nullable=False,
        comment="对账事件类型，仅允许 Phase1.1 封闭枚举",
    )
    price_tier = Column(
        String(50),
        nullable=True,
        comment="C3 定价档位：EXCHANGE/LOCAL_REF/FALLBACK，仅 SYNC_TRADE 时非空",
    )
    diff_snapshot = Column(
        Text(),
        nullable=True,
        comment="C6：STRATEGY_PAUSED 时差异快照（JSON 文本），与 B1 diff 可复用结构",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('RECONCILE_START', 'RECONCILE_END', 'SYNC_TRADE', "
            "'OVER_POSITION', 'STRATEGY_PAUSED', 'STRATEGY_RESUMED', 'RECONCILE_FAILED')",
            name="ck_position_reconcile_log_event_type",
        ),
    )
