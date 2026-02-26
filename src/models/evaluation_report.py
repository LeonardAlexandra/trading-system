"""
Phase2.0 A2：evaluation_report 表（评估报告，满足 0.2，Phase 2.0 自有）

仅结构定义，用于 ORM/只读层。本表为 Phase 2.0 自有表；禁止对 Phase 1.2 任何表执行写操作。
baseline_version_id 仅存 strategy_version_id，禁止存 param_version_id。
"""
from sqlalchemy import Column, DateTime, ForeignKey, BigInteger, Integer, String, JSON
from sqlalchemy.sql import func

from src.database.connection import Base


class EvaluationReport(Base):
    """
    评估报告表（Phase2.0 蓝本 C.2，0.2 Evaluator Contract）。
    用于持久化 Evaluator 产出的评估报告；baseline_version_id 仅指向 strategy_version_id。
    """
    __tablename__ = "evaluation_report"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    strategy_id = Column(String(64), nullable=False)
    strategy_version_id = Column(String(64), nullable=False)
    param_version_id = Column(String(64), nullable=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    objective_definition = Column(JSON(), nullable=False)
    constraint_definition = Column(JSON(), nullable=False)
    baseline_version_id = Column(
        String(64),
        nullable=True,
        comment="仅存 strategy_version_id，禁止存 param_version_id",
    )
    conclusion = Column(String(2048), nullable=False)
    comparison_summary = Column(JSON(), nullable=True)
    metrics_snapshot_id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        ForeignKey("metrics_snapshot.id"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
