"""
Phase2.1 A3/C.3：learning_audit 表 ORM（Phase 2.1 自有）

对应 migration 025 创建的 learning_audit 表。
记录每次 Optimizer 产出参数建议的审计日志。
仅存 evaluation_report_id（ID 引用），禁止存 Phase 2.0 报告内容（B.6）。
"""
from sqlalchemy import Column, DateTime, BigInteger, Integer, String, JSON
from sqlalchemy.sql import func

from src.database.connection import Base


class LearningAudit(Base):
    """
    学习审计表（Phase 2.1 自有）。

    每次 Optimizer 产出建议写一条记录。
    - evaluation_report_id：仅存 Phase 2.0 报告的 ID，禁止内联报告内容（B.5/B.6）。
    - suggested_params：只含白名单参数键（B.1/B.4）。
    - param_version_id_candidate：产出的候选 param_version_id，可空（提交门禁前）。
    """

    __tablename__ = "learning_audit"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    strategy_id = Column(String(255), nullable=False)
    # 仅存 ID，不存报告内容（B.5/B.6）
    evaluation_report_id = Column(String(255), nullable=True)
    param_version_id_candidate = Column(String(255), nullable=True)
    # 仅含白名单参数（由 Optimizer 校验）
    suggested_params = Column(JSON(), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
