"""C5: strategy_runtime_state.status, position_reconcile_log.diff_snapshot, signal_rejection 表

Revision ID: 017
Revises: 016
Create Date: 2026-02-05

Phase1.1 C5：超仓挂起（PAUSED 状态 + STRATEGY_PAUSED 终态日志含差异快照 + 因 PAUSED 拒绝信号可审计）。
- strategy_runtime_state 增加 status（RUNNING/PAUSED），默认 RUNNING。
- position_reconcile_log 增加 diff_snapshot（STRATEGY_PAUSED 时差异快照，见 C6）。
- signal_rejection 表：因 PAUSED 拒绝信号的可审计记录。
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "strategy_runtime_state",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'RUNNING'"),
            comment="C5：策略运行时状态 RUNNING/PAUSED；仅 B1 resume 可恢复为 RUNNING",
        ),
    )
    op.add_column(
        "position_reconcile_log",
        sa.Column(
            "diff_snapshot",
            sa.Text(),
            nullable=True,
            comment="C6：STRATEGY_PAUSED 时差异快照（JSON 文本），与 B1 diff 可复用结构",
        ),
    )
    op.create_table(
        "signal_rejection",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(100), nullable=False, index=True),
        sa.Column("signal_id", sa.String(200), nullable=True),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("signal_rejection")
    op.drop_column("position_reconcile_log", "diff_snapshot")
    op.drop_column("strategy_runtime_state", "status")
