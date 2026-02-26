"""Phase1.2 A1: decision_snapshot 表（决策输入快照，落实 0.4）

Revision ID: 018
Revises: 017
Create Date: 2026-02-07

Phase1.2 开发蓝本 C.1：决策输入快照表，仅追加、不可变；无 UPDATE/DELETE。
- 唯一约束：UNIQUE(decision_id)
- 索引：(strategy_id, created_at) 用于按策略+时间范围查询
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "decision_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("signal_state", sa.JSON(), nullable=False),
        sa.Column("position_state", sa.JSON(), nullable=False),
        sa.Column("risk_check_result", sa.JSON(), nullable=False),
        sa.Column("decision_result", sa.JSON(), nullable=False),
        sa.UniqueConstraint("decision_id", name="uq_decision_snapshot_decision_id"),
    )
    op.create_index(
        "idx_decision_snapshot_strategy_created",
        "decision_snapshot",
        ["strategy_id", "created_at"],
    )


def downgrade():
    op.drop_index("idx_decision_snapshot_strategy_created", table_name="decision_snapshot")
    op.drop_table("decision_snapshot")
