"""PR6: decision_order_map 执行层扩展字段

Revision ID: 002
Revises: 001
Create Date: 2026-01-27

"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "decision_order_map",
        sa.Column("signal_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "decision_order_map",
        sa.Column("strategy_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "decision_order_map",
        sa.Column("symbol", sa.String(20), nullable=True),
    )
    op.add_column(
        "decision_order_map",
        sa.Column("side", sa.String(10), nullable=True),
    )
    op.add_column(
        "decision_order_map",
        sa.Column("quantity", sa.String(20), nullable=True),
    )
    op.add_column(
        "decision_order_map",
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "decision_order_map",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "decision_order_map",
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("decision_order_map", "next_run_at")
    op.drop_column("decision_order_map", "last_error")
    op.drop_column("decision_order_map", "attempt_count")
    op.drop_column("decision_order_map", "quantity")
    op.drop_column("decision_order_map", "side")
    op.drop_column("decision_order_map", "symbol")
    op.drop_column("decision_order_map", "strategy_id")
    op.drop_column("decision_order_map", "signal_id")
