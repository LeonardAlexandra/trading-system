"""PR11: positions 表增加 strategy_id，主键改为 (strategy_id, symbol)，按策略隔离

多策略 position_snapshot 不可逆性：downgrade 会丢弃非 strategy_id='default' 的数据。
执行 downgrade 必须显式设置环境变量 ALLOW_DATA_LOSS=true。
MULTI_STRATEGY_SCHEMA_VERSION = 2（positions 表多策略 schema）
"""
from alembic import op
import os
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

# 多策略 position schema 版本；downgrade 需显式 ALLOW_DATA_LOSS=true
MULTI_STRATEGY_SCHEMA_VERSION = 2


def upgrade():
    # SQLite 无法直接修改主键，采用：建新表 -> 迁移数据（strategy_id='default'）-> 删旧表 -> 重命名
    op.create_table(
        "positions_new",
        sa.Column("strategy_id", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False, server_default=sa.text("'LONG'")),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("strategy_id", "symbol", name="pk_positions_new"),
    )
    op.execute(
        """
        INSERT INTO positions_new (strategy_id, symbol, side, quantity, avg_price, updated_at)
        SELECT 'default', symbol, side, quantity, avg_price, updated_at FROM positions
        """
    )
    op.drop_table("positions")
    op.rename_table("positions_new", "positions")


def downgrade():
    # 多策略 position 不可逆：downgrade 会丢失非 default 策略的持仓数据，必须显式 ALLOW_DATA_LOSS=true
    if os.environ.get("ALLOW_DATA_LOSS") != "true":
        raise RuntimeError(
            "downgrade 007 requires ALLOW_DATA_LOSS=true; "
            "non-default strategy position data will be lost (MULTI_STRATEGY_SCHEMA_VERSION=2)"
        )
    # 当前表为 positions(strategy_id, symbol PK)，先重命名再建回仅 symbol PK 的表
    op.rename_table("positions", "positions_old")
    op.create_table(
        "positions",
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False, server_default=sa.text("'LONG'")),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.execute(
        """
        INSERT INTO positions (symbol, side, quantity, avg_price, updated_at)
        SELECT symbol, side, quantity, avg_price, updated_at FROM positions_old WHERE strategy_id = 'default'
        """
    )
    op.drop_table("positions_old")
