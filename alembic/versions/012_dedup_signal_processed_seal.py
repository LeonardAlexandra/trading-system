"""PR2/MVP 封版补齐：dedup_signal.processed 字段

Revision ID: 012
Revises: 011
Create Date: 2026-02-03

BLOCKER-2: MVP实现计划 约束4 要求 processed BOOLEAN DEFAULT FALSE。
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "dedup_signal",
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("dedup_signal", "processed")
