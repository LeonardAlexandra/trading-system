"""Phase2.1 A2: release_audit 表创建（Phase2.1 自有，按 C.2）

Revision ID: 024
Revises: 023
Create Date: 2026-02-26
"""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None

TABLE_NAME = "release_audit"
IDX_STRATEGY_ID = "idx_release_audit_strategy_id"
IDX_PARAM_VERSION_ID = "idx_release_audit_param_version_id"
IDX_CREATED_AT = "idx_release_audit_created_at"


def upgrade() -> None:
    # Phase2.1 自有扩展：仅新增 release_audit 审计表与索引，不修改 Phase2.0 语义。
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(255), nullable=False),
        sa.Column("param_version_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("gate_type", sa.String(32), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("operator_or_rule_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "action IN ('APPLY','ROLLBACK','AUTO_DISABLE','SUBMIT_CANDIDATE','REJECT')",
            name="ck_release_audit_action",
        ),
        sa.CheckConstraint(
            "gate_type IS NULL OR gate_type IN ('MANUAL','RISK_GUARD')",
            name="ck_release_audit_gate_type",
        ),
    )
    op.create_index(IDX_STRATEGY_ID, TABLE_NAME, ["strategy_id"], unique=False)
    op.create_index(IDX_PARAM_VERSION_ID, TABLE_NAME, ["param_version_id"], unique=False)
    op.create_index(IDX_CREATED_AT, TABLE_NAME, ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(IDX_CREATED_AT, table_name=TABLE_NAME)
    op.drop_index(IDX_PARAM_VERSION_ID, table_name=TABLE_NAME)
    op.drop_index(IDX_STRATEGY_ID, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
