"""Phase2.0 A2: evaluation_report 表（评估报告，满足 0.2，Phase 2.0 自有）

Revision ID: 022
Revises: 021
Create Date: 2026-02-14

Phase2.0 开发蓝本 C.2：评估报告表，为 Evaluator 产出提供持久化存储。
- 本表为 Phase 2.0 自有表；禁止对 Phase 1.2 任何表执行写操作。
- baseline_version_id 仅存 strategy_version_id，禁止存 param_version_id。
- 索引：(strategy_id, evaluated_at)、(strategy_version_id, evaluated_at)、(param_version_id, evaluated_at)。
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_report",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("strategy_version_id", sa.String(64), nullable=False),
        sa.Column("param_version_id", sa.String(64), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("objective_definition", sa.JSON(), nullable=False),
        sa.Column("constraint_definition", sa.JSON(), nullable=False),
        sa.Column(
            "baseline_version_id",
            sa.String(64),
            nullable=True,
            comment="仅存 strategy_version_id，禁止存 param_version_id",
        ),
        sa.Column("conclusion", sa.String(2048), nullable=False),
        sa.Column("comparison_summary", sa.JSON(), nullable=True),
        sa.Column(
            "metrics_snapshot_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("metrics_snapshot.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Phase2.0 自有表，评估报告；baseline_version_id 仅存 strategy_version_id，禁止「建议参数/写回/优化」语义。",
    )
    op.create_index(
        "idx_evaluation_report_strategy_evaluated",
        "evaluation_report",
        ["strategy_id", "evaluated_at"],
    )
    op.create_index(
        "idx_evaluation_report_version_evaluated",
        "evaluation_report",
        ["strategy_version_id", "evaluated_at"],
    )
    op.create_index(
        "idx_evaluation_report_param_evaluated",
        "evaluation_report",
        ["param_version_id", "evaluated_at"],
    )


def downgrade():
    op.drop_index("idx_evaluation_report_param_evaluated", table_name="evaluation_report")
    op.drop_index("idx_evaluation_report_version_evaluated", table_name="evaluation_report")
    op.drop_index("idx_evaluation_report_strategy_evaluated", table_name="evaluation_report")
    op.drop_table("evaluation_report")
