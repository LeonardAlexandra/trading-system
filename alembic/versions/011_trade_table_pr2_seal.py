"""PR2 封版补齐：trade 表（交易记录表）

Revision ID: 011
Revises: 010
Create Date: 2026-02-03

BLOCKER-1: Phase1.0 开发交付包 PR2 要求 trade 表存在，包含所有必要字段。
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trade",
        sa.Column("trade_id", sa.String(100), primary_key=True),
        sa.Column("strategy_id", sa.String(50), nullable=False),
        sa.Column("signal_id", sa.String(100), nullable=False),
        sa.Column("decision_id", sa.String(100), nullable=False),
        sa.Column("execution_id", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("slippage", sa.Numeric(20, 8), server_default=sa.text("0")),
        sa.Column("realized_pnl", sa.Numeric(20, 8), server_default=sa.text("0")),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment="交易记录表（Active + Shadow）",
    )
    op.create_index("idx_trade_signal_id", "trade", ["signal_id"])
    op.create_index("idx_trade_decision_id", "trade", ["decision_id"])
    op.create_index("idx_trade_strategy_id", "trade", ["strategy_id"])


def downgrade():
    op.drop_index("idx_trade_strategy_id", table_name="trade")
    op.drop_index("idx_trade_decision_id", table_name="trade")
    op.drop_index("idx_trade_signal_id", table_name="trade")
    op.drop_table("trade")
