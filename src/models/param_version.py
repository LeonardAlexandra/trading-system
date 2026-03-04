"""
Phase2.1 C.1：param_version 表（Phase 2.1 自有）

记录策略参数版本，携带 release_state（发布状态机五态）。
Phase 2.1 写回路径：candidate → approved → active。
禁止写入 Phase 2.0 表（evaluation_report / metrics_snapshot）。
"""
from sqlalchemy import Column, DateTime, BigInteger, Integer, String, JSON
from sqlalchemy.sql import func

from src.database.connection import Base

# 发布状态五态（写死，不可扩展为六态或以上）
RELEASE_STATE_CANDIDATE = "candidate"
RELEASE_STATE_APPROVED = "approved"
RELEASE_STATE_ACTIVE = "active"
RELEASE_STATE_STABLE = "stable"
RELEASE_STATE_DISABLED = "disabled"

VALID_RELEASE_STATES = frozenset(
    [
        RELEASE_STATE_CANDIDATE,
        RELEASE_STATE_APPROVED,
        RELEASE_STATE_ACTIVE,
        RELEASE_STATE_STABLE,
        RELEASE_STATE_DISABLED,
    ]
)


class ParamVersion(Base):
    """
    参数版本表（Phase 2.1 自有）。

    每条记录对应一个候选/活跃/稳定的参数集合，携带 release_state 五态。
    - params 字段仅存白名单内参数（B.1/B.4 强制），写入时由 Optimizer/ReleaseGate 校验。
    - release_state 仅由 ReleaseGate 状态机更新，禁止直接越级修改。
    """

    __tablename__ = "param_version"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    # 外部引用 ID（与 evaluation_report.param_version_id 中使用的值一致）
    param_version_id = Column(String(255), nullable=False, unique=True)
    strategy_id = Column(String(255), nullable=False)
    strategy_version_id = Column(String(255), nullable=False)
    # 仅存白名单参数（max_position_size, fixed_order_size, stop_loss_pct, take_profit_pct, ...）
    params = Column(JSON(), nullable=False)
    # 发布状态机五态；默认 candidate
    release_state = Column(String(32), nullable=False, server_default="candidate")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
