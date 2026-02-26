"""C3: position_reconcile_log 增加 price_tier 列（定价档位落盘可追溯）

Revision ID: 016
Revises: 015
Create Date: 2026-02-05

Phase1.1 封版：price_tier 必须持久化，SYNC_TRADE 时写入 EXCHANGE/LOCAL_REF/FALLBACK。
"""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "position_reconcile_log",
        sa.Column(
            "price_tier",
            sa.String(50),
            nullable=True,
            comment="C3 定价档位：EXCHANGE/LOCAL_REF/FALLBACK，仅 SYNC_TRADE 时非空",
        ),
    )


def downgrade():
    op.drop_column("position_reconcile_log", "price_tier")
