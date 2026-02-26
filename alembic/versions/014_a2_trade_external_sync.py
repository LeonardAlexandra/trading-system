"""A2: trade 表 EXTERNAL_SYNC 来源支持（幂等键 strategy_id + external_trade_id）

Revision ID: 014
Revises: 013
Create Date: 2026-02-05

Phase1.1 A2：新增 source_type、external_trade_id；
EXTERNAL_SYNC 幂等键 (strategy_id, external_trade_id)，DB 唯一约束保证不重复插入；
既有信号驱动写入不受影响（source_type 默认 SIGNAL）。
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    # 来源区分：至少 EXTERNAL_SYNC 与信号驱动；既有写入不传则默认 SIGNAL
    op.add_column(
        "trade",
        sa.Column(
            "source_type",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'SIGNAL'"),
            comment="成交来源：SIGNAL=信号驱动，EXTERNAL_SYNC=外部/对账同步",
        ),
    )
    op.add_column(
        "trade",
        sa.Column(
            "external_trade_id",
            sa.String(200),
            nullable=True,
            comment="外部/交易所成交 ID，EXTERNAL_SYNC 时必填；幂等键 (strategy_id, external_trade_id)",
        ),
    )
    # EXTERNAL_SYNC 场景下无 signal/decision/execution，故允许可空（Phase1.1 可空或默认规则）
    # 唯一约束：同一 strategy_id + external_trade_id 仅能一条；SQLite 需在 batch 内建约束
    with op.batch_alter_table("trade", schema=None) as batch_op:
        batch_op.alter_column(
            "signal_id",
            existing_type=sa.String(100),
            nullable=True,
        )
        batch_op.alter_column(
            "decision_id",
            existing_type=sa.String(100),
            nullable=True,
        )
        batch_op.alter_column(
            "execution_id",
            existing_type=sa.String(100),
            nullable=True,
        )
        batch_op.create_unique_constraint(
            "uq_trade_strategy_external_trade_id",
            ["strategy_id", "external_trade_id"],
        )


def downgrade():
    with op.batch_alter_table("trade", schema=None) as batch_op:
        batch_op.drop_constraint("uq_trade_strategy_external_trade_id", type_="unique")
    op.drop_column("trade", "external_trade_id")
    op.drop_column("trade", "source_type")
    # 不恢复 signal_id/decision_id/execution_id 为 NOT NULL，避免存在 NULL 时 downgrade 失败
