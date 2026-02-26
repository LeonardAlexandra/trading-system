"""PR13: execution_events 增加 account_id / exchange_profile / dry_run

Revision ID: 008
Revises: 007
Create Date: 2026-01-27

"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("execution_events", sa.Column("account_id", sa.String(80), nullable=True))
    op.add_column("execution_events", sa.Column("exchange_profile", sa.String(80), nullable=True))
    op.add_column("execution_events", sa.Column("dry_run", sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade():
    op.drop_column("execution_events", "dry_run")
    op.drop_column("execution_events", "exchange_profile")
    op.drop_column("execution_events", "account_id")
