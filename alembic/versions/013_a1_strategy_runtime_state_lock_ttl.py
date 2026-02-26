"""A1: strategy_runtime_state 互斥锁字段 + TTL 支撑

Revision ID: 013
Revises: 012
Create Date: 2026-02-05

Phase1.1 A1：新增表 strategy_runtime_state，包含锁与 TTL 字段。
锁语义由 C1 基于单条原子 UPDATE 实现；本迁移仅提供 schema。
TTL 默认 30 秒，锁过期判定：now() > locked_at + lock_ttl_seconds。
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    # 当前项目中无 strategy_runtime_state 表，故创建整表（仅含锁与 TTL 所需字段）
    op.create_table(
        "strategy_runtime_state",
        sa.Column("strategy_id", sa.String(100), primary_key=True),
        sa.Column(
            "lock_holder_id",
            sa.String(200),
            nullable=True,
            comment="锁持有者标识，NULL 表示无锁；与 locked_at 共同用于租约锁",
        ),
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="锁获取时间；过期判定：now() > locked_at + lock_ttl_seconds",
        ),
        sa.Column(
            "lock_ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
            comment="锁 TTL（秒），默认 30；超过 TTL 未续期视为失效，可被抢占",
        ),
    )


def downgrade():
    op.drop_table("strategy_runtime_state")
