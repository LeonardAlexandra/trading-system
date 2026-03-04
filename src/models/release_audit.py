"""
Phase2.1 A2/C.2：release_audit 表 ORM（Phase 2.1 自有）

对应 migration 024 创建的 release_audit 表。
记录每次发布门禁操作的审计日志：APPLY / ROLLBACK / AUTO_DISABLE / SUBMIT_CANDIDATE / REJECT。
禁止写入 Phase 2.0 表。
"""
from sqlalchemy import Column, DateTime, BigInteger, Integer, String, Boolean, JSON
from sqlalchemy.sql import func

from src.database.connection import Base

# 操作类型（写死）
ACTION_APPLY = "APPLY"
ACTION_ROLLBACK = "ROLLBACK"
ACTION_AUTO_DISABLE = "AUTO_DISABLE"
ACTION_SUBMIT_CANDIDATE = "SUBMIT_CANDIDATE"
ACTION_REJECT = "REJECT"

VALID_ACTIONS = frozenset(
    [ACTION_APPLY, ACTION_ROLLBACK, ACTION_AUTO_DISABLE, ACTION_SUBMIT_CANDIDATE, ACTION_REJECT]
)

# 门禁类型（写死）
GATE_TYPE_MANUAL = "MANUAL"
GATE_TYPE_RISK_GUARD = "RISK_GUARD"

VALID_GATE_TYPES = frozenset([GATE_TYPE_MANUAL, GATE_TYPE_RISK_GUARD])


class ReleaseAudit(Base):
    """
    发布审计表（Phase 2.1 自有）。

    每次发布门禁状态迁移均写一条审计记录；禁止删改（仅追加）。
    payload 字段存放操作上下文（触发条件、阈值、回滚目标等），格式为 JSON。
    """

    __tablename__ = "release_audit"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    strategy_id = Column(String(255), nullable=False)
    param_version_id = Column(String(255), nullable=True)
    # APPLY | ROLLBACK | AUTO_DISABLE | SUBMIT_CANDIDATE | REJECT
    action = Column(String(64), nullable=False)
    # MANUAL | RISK_GUARD（AUTO_DISABLE 时可为 None）
    gate_type = Column(String(32), nullable=True)
    # 门禁是否通过
    passed = Column(Boolean(), nullable=False)
    # 操作人员 ID 或自动规则 ID
    operator_or_rule_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # 操作上下文：触发条件、阈值、回滚目标等
    payload = Column(JSON(), nullable=True)
