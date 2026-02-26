"""A3: position_reconcile_log 表（external_trade_id + event_type 封闭枚举）

Revision ID: 015
Revises: 014
Create Date: 2026-02-05

Phase1.1 A3：对账与审计可追溯日志；event_type 为封闭枚举，以 Phase1.1 文档为唯一真理源。
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

# Phase1.1 文档 event_type 枚举（唯一真理源），不得新增或改名
EVENT_TYPE_VALUES = (
    "RECONCILE_START",
    "RECONCILE_END",
    "SYNC_TRADE",
    "OVER_POSITION",
    "STRATEGY_PAUSED",
    "STRATEGY_RESUMED",
    "RECONCILE_FAILED",
)
EVENT_TYPE_CHECK = ", ".join(repr(v) for v in EVENT_TYPE_VALUES)


def upgrade():
    op.create_table(
        "position_reconcile_log",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("strategy_id", sa.String(100), nullable=False, index=True),
        sa.Column(
            "external_trade_id",
            sa.String(200),
            nullable=True,
            comment="关联外部/交易所成交 ID，非 EXTERNAL_SYNC 场景可空",
        ),
        sa.Column(
            "event_type",
            sa.String(50),
            nullable=False,
            comment="对账事件类型，仅允许 Phase1.1 封闭枚举",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            f"event_type IN ({EVENT_TYPE_CHECK})",
            name="ck_position_reconcile_log_event_type",
        ),
    )
    op.create_index(
        "idx_position_reconcile_log_strategy_created",
        "position_reconcile_log",
        ["strategy_id", "created_at"],
    )


def downgrade():
    op.drop_index("idx_position_reconcile_log_strategy_created", table_name="position_reconcile_log")
    op.drop_table("position_reconcile_log")
