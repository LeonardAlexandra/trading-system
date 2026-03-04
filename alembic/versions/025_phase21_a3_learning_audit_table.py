"""Phase2.1 A3: learning_audit 表创建（Phase2.1 自有）

Revision ID: 025
Revises: 024
Create Date: 2026-02-26
"""
from alembic import op
import sqlalchemy as sa


class JSONBType(sa.types.UserDefinedType):
    def get_col_spec(self, **kw):
        return "JSONB"

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None

TABLE_NAME = "learning_audit"
IDX_STRATEGY_ID = "idx_learning_audit_strategy_id"
IDX_CREATED_AT = "idx_learning_audit_created_at"
IDX_EVAL_REPORT_ID = "idx_learning_audit_evaluation_report_id"
IDX_PARAM_VERSION_CAND = "idx_learning_audit_param_version_id_candidate"


def upgrade() -> None:
    # Phase2.1 自有扩展：仅新增 learning_audit 审计表与索引，不修改 Phase2.0 语义。
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(255), nullable=False),
        sa.Column("evaluation_report_id", sa.String(255), nullable=True),
        sa.Column("param_version_id_candidate", sa.String(255), nullable=True),
        sa.Column("suggested_params", JSONBType(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(IDX_STRATEGY_ID, TABLE_NAME, ["strategy_id"], unique=False)
    op.create_index(IDX_CREATED_AT, TABLE_NAME, ["created_at"], unique=False)
    op.create_index(IDX_EVAL_REPORT_ID, TABLE_NAME, ["evaluation_report_id"], unique=False)
    op.create_index(IDX_PARAM_VERSION_CAND, TABLE_NAME, ["param_version_id_candidate"], unique=False)


def downgrade() -> None:
    op.drop_index(IDX_PARAM_VERSION_CAND, table_name=TABLE_NAME)
    op.drop_index(IDX_EVAL_REPORT_ID, table_name=TABLE_NAME)
    op.drop_index(IDX_CREATED_AT, table_name=TABLE_NAME)
    op.drop_index(IDX_STRATEGY_ID, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
