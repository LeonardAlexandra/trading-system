"""PR14a: rate_limit_state, circuit_breaker_state 表 + execution_events.live_enabled

限频/断路器状态外置，多实例共享。downgrade 会删除两表数据，需 ALLOW_DATA_LOSS=true。
"""
from alembic import op
import os
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rate_limit_state",
        sa.Column("account_id", sa.String(80), nullable=False),
        sa.Column("window_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("account_id", name="pk_rate_limit_state"),
    )
    op.create_table(
        "circuit_breaker_state",
        sa.Column("account_id", sa.String(80), nullable=False),
        sa.Column("failures_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("opened_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("account_id", name="pk_circuit_breaker_state"),
    )
    op.add_column(
        "execution_events",
        sa.Column("live_enabled", sa.Boolean(), nullable=True, server_default=sa.false()),
    )


def downgrade():
    if (os.environ.get("ALLOW_DATA_LOSS") or "").strip().lower() != "true":
        raise RuntimeError(
            "downgrade drops rate_limit_state and circuit_breaker_state (data loss). "
            "Set ALLOW_DATA_LOSS=true to allow."
        )
    op.drop_column("execution_events", "live_enabled")
    op.drop_table("circuit_breaker_state")
    op.drop_table("rate_limit_state")
