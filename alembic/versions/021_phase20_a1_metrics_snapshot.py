"""Phase2.0 A1: metrics_snapshot 表（指标快照，Phase 2.0 自有）

Revision ID: 021
Revises: 020
Create Date: 2026-02-14

Phase2.0 开发蓝本 C.1：指标快照表，为 Phase 2.0 指标计算产出提供持久化存储。
- 本表为 Phase 2.0 自有表；禁止对 Phase 1.2 任何表执行写操作。
- 表中仅存在 B.2/C.1 文档化字段，无未文档化列。
- 索引：(strategy_id, period_start, period_end)；(strategy_id, strategy_version_id)；
  (strategy_version_id, param_version_id, period_start)。
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "metrics_snapshot",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("strategy_version_id", sa.String(64), nullable=False),
        sa.Column("param_version_id", sa.String(64), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Numeric(18, 6), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("max_drawdown", sa.Numeric(20, 8), nullable=True),
        sa.Column("avg_holding_time_sec", sa.Numeric(18, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Phase2.0 自有表，仅存 B.2/C.1 文档化指标字段，无未文档化列；禁止对 Phase 1.2 表写操作。",
    )
    op.create_index(
        "idx_metrics_snapshot_strategy_period",
        "metrics_snapshot",
        ["strategy_id", "period_start", "period_end"],
    )
    op.create_index(
        "idx_metrics_snapshot_strategy_version",
        "metrics_snapshot",
        ["strategy_id", "strategy_version_id"],
    )
    op.create_index(
        "idx_metrics_snapshot_version_param_period",
        "metrics_snapshot",
        ["strategy_version_id", "param_version_id", "period_start"],
    )


def downgrade():
    op.drop_index("idx_metrics_snapshot_version_param_period", table_name="metrics_snapshot")
    op.drop_index("idx_metrics_snapshot_strategy_version", table_name="metrics_snapshot")
    op.drop_index("idx_metrics_snapshot_strategy_period", table_name="metrics_snapshot")
    op.drop_table("metrics_snapshot")
