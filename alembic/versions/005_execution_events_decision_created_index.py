"""PR8 审阅：execution_events (decision_id, created_at) 复合索引

Revision ID: 005
Revises: 004
Create Date: 2026-01-27

"""
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_execution_events_decision_created",
        "execution_events",
        ["decision_id", "created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_execution_events_decision_created",
        table_name="execution_events",
    )
