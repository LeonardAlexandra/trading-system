"""Phase1.2 A2: log 表（审计/操作/错误日志）

Revision ID: 019
Revises: 018
Create Date: 2026-02-07

Phase1.2 开发蓝本 C.1：审计/操作/错误日志统一表，用 level + event_type 区分。
- level 仅允许：INFO, WARNING, ERROR, AUDIT（实现时用 VARCHAR，见 C.3）
- 索引：(created_at, component, level) 用于分页查询
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
    )
    op.create_index(
        "idx_log_created_component_level",
        "log",
        ["created_at", "component", "level"],
    )


def downgrade():
    op.drop_index("idx_log_created_component_level", table_name="log")
    op.drop_table("log")
