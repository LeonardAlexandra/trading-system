"""Initial schema for PR2 (dedup_signal, decision_order_map, orders)

Revision ID: 001
Revises: 
Create Date: 2026-01-27

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # dedup_signal 表（信号去重）
    op.create_table(
        'dedup_signal',
        sa.Column('signal_id', sa.String(100), primary_key=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment='信号去重表（signal_id 唯一键保证永久去重，不依赖 processed 字段）'
    )
    
    # decision_order_map 表（决策订单映射）
    op.create_table(
        'decision_order_map',
        sa.Column('decision_id', sa.String(100), primary_key=True),
        sa.Column('local_order_id', sa.String(100), nullable=True),  # 本地订单号（可空，支持先占位后下单）
        sa.Column('exchange_order_id', sa.String(100), nullable=True),  # 交易所订单号（可空）
        sa.Column('status', sa.String(20), server_default=text("'RESERVED'")),  # "RESERVED" | "PLACED" | "FILLED" | "FAILED" | "TIMEOUT" | "UNKNOWN"
        sa.Column('reserved_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        comment='决策订单映射表（decision_id 唯一键保证幂等，支持两段式幂等：先占位后下单）'
    )
    
    # orders 表（订单，避免 SQL 关键字冲突）
    op.create_table(
        'orders',
        sa.Column('order_id', sa.String(100), primary_key=True),
        sa.Column('exchange_order_id', sa.String(100)),
        sa.Column('strategy_id', sa.String(50), nullable=False),
        sa.Column('decision_id', sa.String(100), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('filled_quantity', sa.Numeric(20, 8), server_default=text('0')),
        sa.Column('price', sa.Numeric(20, 8)),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        comment='订单表'
    )
    # orders 表的索引（索引名统一为 idx_orders_*，与表名 orders 保持一致）
    op.create_index('idx_orders_decision_id', 'orders', ['decision_id'])
    op.create_index('idx_orders_strategy_id', 'orders', ['strategy_id'])
    op.create_index('idx_orders_status', 'orders', ['status'])


def downgrade():
    # 删除索引（按创建顺序反向）
    op.drop_index('idx_orders_status', table_name='orders')
    op.drop_index('idx_orders_strategy_id', table_name='orders')
    op.drop_index('idx_orders_decision_id', table_name='orders')
    
    # 删除表（按创建顺序反向）
    op.drop_table('orders')
    op.drop_table('decision_order_map')
    op.drop_table('dedup_signal')
