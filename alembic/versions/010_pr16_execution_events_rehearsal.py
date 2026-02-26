"""PR16: execution_events.rehearsal（演练模式追溯）

DEMO_LIVE_REHEARSAL 时 event message 可含 rehearsal=true。
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "execution_events",
        sa.Column("rehearsal", sa.Boolean(), nullable=True, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("execution_events", "rehearsal")
