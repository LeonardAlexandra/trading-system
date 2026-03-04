"""Phase2.1 A4: param_version 表创建

Revision ID: 026
Revises: 025
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa


class JSONBType(sa.types.UserDefinedType):
    def get_col_spec(self, **kw):
        return "JSONB"


revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None

TABLE_NAME = "param_version"
IDX_STRATEGY_ID = "idx_param_version_strategy_id"
IDX_RELEASE_STATE = "idx_param_version_release_state"
IDX_STRATEGY_STATE = "idx_param_version_strategy_release_state"
IDX_STRATEGY_VERSION = "idx_param_version_strategy_version_id"
CHECK_NAME = "ck_param_version_release_state"
ALLOWED_STATES = ("candidate", "approved", "active", "stable", "disabled")


def upgrade() -> None:
    # Phase2.1 A4 自有扩展：创建 param_version 表，不修改 Phase2.0 语义。
    op.create_table(
        TABLE_NAME,
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("param_version_id", sa.String(255), nullable=False, unique=True),
        sa.Column("strategy_id", sa.String(255), nullable=False),
        sa.Column("strategy_version_id", sa.String(255), nullable=False),
        # 仅存白名单参数（B.1/B.4）
        sa.Column("params", JSONBType(), nullable=False),
        # 发布状态机五态，默认 candidate
        sa.Column(
            "release_state",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'candidate'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "release_state IN ('candidate','approved','active','stable','disabled')",
            name=CHECK_NAME,
        ),
    )
    op.create_index(IDX_STRATEGY_ID, TABLE_NAME, ["strategy_id"], unique=False)
    op.create_index(IDX_RELEASE_STATE, TABLE_NAME, ["release_state"], unique=False)
    op.create_index(
        IDX_STRATEGY_STATE, TABLE_NAME, ["strategy_id", "release_state"], unique=False
    )
    op.create_index(
        IDX_STRATEGY_VERSION, TABLE_NAME, ["strategy_version_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(IDX_STRATEGY_VERSION, table_name=TABLE_NAME)
    op.drop_index(IDX_STRATEGY_STATE, table_name=TABLE_NAME)
    op.drop_index(IDX_RELEASE_STATE, table_name=TABLE_NAME)
    op.drop_index(IDX_STRATEGY_ID, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
