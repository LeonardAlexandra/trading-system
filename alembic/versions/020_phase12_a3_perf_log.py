"""Phase1.2 A3: perf_log 表（性能日志，1.2b）

Revision ID: 020
Revises: 019
Create Date: 2026-02-07

Phase1.2 开发蓝本 C.1：性能日志独立表，与 log 语义分离；仅性能指标（延迟、吞吐等）。
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "perf_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_table("perf_log")
