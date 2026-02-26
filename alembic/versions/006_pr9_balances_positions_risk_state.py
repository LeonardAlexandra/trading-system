"""PR9: balances, positions, risk_state 表

Revision ID: 006
Revises: 005
Create Date: 2026-01-27

"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "balances",
        sa.Column("asset", sa.String(20), primary_key=True),
        sa.Column("available", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_table(
        "positions",
        sa.Column("symbol", sa.String(20), primary_key=True),
        sa.Column("side", sa.String(10), nullable=False, server_default=sa.text("'LONG'")),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_table(
        "risk_state",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("last_allowed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade():
    op.drop_table("risk_state")
    op.drop_table("positions")
    op.drop_table("balances")
