"""PR8: execution_events 表

Revision ID: 004
Revises: 003
Create Date: 2026-01-27

"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "execution_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("decision_id", sa.String(100), nullable=False, index=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("reason_code", sa.String(40), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("exchange_order_id", sa.String(100), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("execution_events")
