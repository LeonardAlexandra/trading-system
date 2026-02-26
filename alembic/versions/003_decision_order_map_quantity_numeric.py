"""decision_order_map.quantity 改为 Numeric(20, 8)

Revision ID: 003
Revises: 002
Create Date: 2026-01-27

"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    # quantity: String(20) -> Numeric(20, 8)，server_default=1
    with op.batch_alter_table("decision_order_map", schema=None) as batch_op:
        batch_op.alter_column(
            "quantity",
            existing_type=sa.String(20),
            type_=sa.Numeric(20, 8),
            existing_nullable=True,
            server_default=sa.text("1"),
            postgresql_using="quantity::numeric(20,8)",
        )


def downgrade():
    with op.batch_alter_table("decision_order_map", schema=None) as batch_op:
        batch_op.alter_column(
            "quantity",
            existing_type=sa.Numeric(20, 8),
            type_=sa.String(20),
            existing_nullable=True,
        )
