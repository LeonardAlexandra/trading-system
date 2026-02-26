# Phase1.2 A1 模块证据包

**模块编号**: A1  
**模块名称**: decision_snapshot 表（决策输入快照，落实 0.4）  
**交付日期**: 2026-02-07

---

## 【A】变更文件清单

| 类型 | 文件路径 | 用途 |
|------|----------|------|
| 新增 | `alembic/versions/018_phase12_a1_decision_snapshot.py` | A1 数据库迁移（建表、唯一约束、索引，upgrade/downgrade） |
| 新增 | `src/models/decision_snapshot.py` | decision_snapshot ORM 模型（仅结构定义） |
| 修改 | `src/models/__init__.py` | 导出 `DecisionSnapshot` |

---

## 【B】Alembic migration 文件全文

**文件**: `alembic/versions/018_phase12_a1_decision_snapshot.py`

```python
"""Phase1.2 A1: decision_snapshot 表（决策输入快照，落实 0.4）

Revision ID: 018
Revises: 017
Create Date: 2026-02-07

Phase1.2 开发蓝本 C.1：决策输入快照表，仅追加、不可变；无 UPDATE/DELETE。
- 唯一约束：UNIQUE(decision_id)
- 索引：(strategy_id, created_at) 用于按策略+时间范围查询
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "decision_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("signal_state", sa.JSON(), nullable=False),
        sa.Column("position_state", sa.JSON(), nullable=False),
        sa.Column("risk_check_result", sa.JSON(), nullable=False),
        sa.Column("decision_result", sa.JSON(), nullable=False),
        sa.UniqueConstraint("decision_id", name="uq_decision_snapshot_decision_id"),
    )
    op.create_index(
        "idx_decision_snapshot_strategy_created",
        "decision_snapshot",
        ["strategy_id", "created_at"],
    )


def downgrade():
    op.drop_index("idx_decision_snapshot_strategy_created", table_name="decision_snapshot")
    op.drop_table("decision_snapshot")
```

---

## 【C】decision_snapshot 模型 / schema 定义文件全文

**文件**: `src/models/decision_snapshot.py`

```python
"""
Phase1.2 A1：decision_snapshot 表（决策输入快照，落实 0.4）

仅结构定义，用于 ORM/只读层。本表仅追加、不可变；禁止提供按 decision_id 或 id 的 UPDATE/DELETE。
Repository（save / get_by_decision_id / list_by_strategy_time）由 C1 实现，本模块不实现。
"""
from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from src.database.connection import Base


class DecisionSnapshot(Base):
    """
    决策输入快照表（Phase1.2 蓝本 C.1）。
    快照内容必须为本次决策实际使用的输入状态；写入后为不可变历史记录。
    """
    __tablename__ = "decision_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(String(64), nullable=False, unique=True)
    strategy_id = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    signal_state = Column(JSON(), nullable=False)  # 本次决策实际使用的信号输入
    position_state = Column(JSON(), nullable=False)  # 本次决策时刻实际使用的持仓输入
    risk_check_result = Column(JSON(), nullable=False)  # 本次决策前风控实际结果
    decision_result = Column(JSON(), nullable=False)  # 最终决策结果

    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_decision_snapshot_decision_id"),
    )
```

---

## 【D】迁移执行命令与原始输出

### 执行命令

```bash
cd /Users/zhangkuo/TradingView\ Indicator/trading_system
export DATABASE_URL=sqlite:///./phase12_a1_evidence.db
alembic upgrade head
alembic current
alembic downgrade 017
alembic upgrade 018
```

### 原始输出

**alembic upgrade head**

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001, Initial schema for PR2 (dedup_signal, decision_order_map, orders)
INFO  [alembic.runtime.migration] Running upgrade 001 -> 002, PR6: decision_order_map 执行层扩展字段
INFO  [alembic.runtime.migration] Running upgrade 002 -> 003, decision_order_map.quantity 改为 Numeric(20, 8)
INFO  [alembic.runtime.migration] Running upgrade 003 -> 004, PR8: execution_events 表
INFO  [alembic.runtime.migration] Running upgrade 004 -> 005, PR8 审阅：execution_events (decision_id, created_at) 复合索引
INFO  [alembic.runtime.migration] Running upgrade 005 -> 006, PR9: balances, positions, risk_state 表
INFO  [alembic.runtime.migration] Running upgrade 006 -> 007, PR11: positions 表增加 strategy_id，主键改为 (strategy_id, symbol)，按策略隔离
INFO  [alembic.runtime.migration] Running upgrade 007 -> 008, PR13: execution_events 增加 account_id / exchange_profile / dry_run
INFO  [alembic.runtime.migration] Running upgrade 008 -> 009, PR14a: rate_limit_state, circuit_breaker_state 表 + execution_events.live_enabled
INFO  [alembic.runtime.migration] Running upgrade 009 -> 010, PR16: execution_events.rehearsal（演练模式追溯）
INFO  [alembic.runtime.migration] Running upgrade 010 -> 011, PR2 封版补齐：trade 表（交易记录表）
INFO  [alembic.runtime.migration] Running upgrade 011 -> 012, PR2/MVP 封版补齐：dedup_signal.processed 字段
INFO  [alembic.runtime.migration] Running upgrade 012 -> 013, A1: strategy_runtime_state 互斥锁字段 + TTL 支撑
INFO  [alembic.runtime.migration] Running upgrade 013 -> 014, A2: trade 表 EXTERNAL_SYNC 来源支持（幂等键 strategy_id + external_trade_id）
INFO  [alembic.runtime.migration] Running upgrade 014 -> 015, A3: position_reconcile_log 表（external_trade_id + event_type 封闭枚举）
INFO  [alembic.runtime.migration] Running upgrade 015 -> 016, C3: position_reconcile_log 增加 price_tier 列（定价档位落盘可追溯）
INFO  [alembic.runtime.migration] Running upgrade 016 -> 017, C5: strategy_runtime_state.status, position_reconcile_log.diff_snapshot, signal_rejection 表
INFO  [alembic.runtime.migration] Running upgrade 017 -> 018, Phase1.2 A1: decision_snapshot 表（决策输入快照，落实 0.4）
```

**alembic current**

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
018 (head)
```

**alembic downgrade 017**

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 018 -> 017, Phase1.2 A1: decision_snapshot 表（决策输入快照，落实 0.4）
```

**alembic upgrade 018**

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 017 -> 018, Phase1.2 A1: decision_snapshot 表（决策输入快照，落实 0.4）
```

**表结构验证（sqlite3 .schema decision_snapshot）**

```
CREATE TABLE decision_snapshot (
	id INTEGER NOT NULL, 
	decision_id VARCHAR(64) NOT NULL, 
	strategy_id VARCHAR(64) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	signal_state JSON NOT NULL, 
	position_state JSON NOT NULL, 
	risk_check_result JSON NOT NULL, 
	decision_result JSON NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_decision_snapshot_decision_id UNIQUE (decision_id)
);
CREATE INDEX idx_decision_snapshot_strategy_created ON decision_snapshot (strategy_id, created_at);
```

---

## 【E】Acceptance Criteria 逐条对照（YES / NO + 证据）

| # | 验收口径 | 结论 | 证据 |
|---|----------|------|------|
| 1 | 迁移可重复执行（upgrade/downgrade 无报错，幂等） | YES | 已执行 `alembic upgrade head`、`alembic downgrade 017`、`alembic upgrade 018`，均无报错；见【D】原始输出。 |
| 2 | 表中存在 decision_id 唯一约束及 (strategy_id, created_at) 索引 | YES | 迁移中定义 `UniqueConstraint("decision_id", name="uq_decision_snapshot_decision_id")` 与 `create_index("idx_decision_snapshot_strategy_created", ..., ["strategy_id", "created_at"])`；sqlite3 `.schema` 输出中可见 `CONSTRAINT uq_decision_snapshot_decision_id UNIQUE (decision_id)` 与 `CREATE INDEX idx_decision_snapshot_strategy_created ON decision_snapshot (strategy_id, created_at)`。 |
| 3 | 文档或注释明确本表仅追加、不可变，无 update/delete 接口 | YES | 迁移文件注释写明「仅追加、不可变；无 UPDATE/DELETE」；模型文件注释写明「本表仅追加、不可变；禁止提供按 decision_id 或 id 的 UPDATE/DELETE」「Repository 由 C1 实现，本模块不实现」。未实现任何 update/delete 接口。 |
| 4 | 表结构与蓝本 C.1 完全一致（id, decision_id, strategy_id, created_at, signal_state, position_state, risk_check_result, decision_result） | YES | 迁移与模型均包含上述 8 字段；类型对应：id 主键自增、decision_id String(64) 唯一、strategy_id String(64)、created_at 带 server_default、四列 JSON 必填。与蓝本 C.1 一致（SQLite 使用 INTEGER/JSON 等价实现）。 |
| 5 | 未提供 update / delete | YES | 仅建表与索引；未实现 DecisionSnapshotRepository；无 update/delete 方法或接口。 |
| 6 | 未修改其他表 | YES | 迁移仅对 `decision_snapshot` 执行 create_table、create_index、drop_index、drop_table，未改动 decision、trade、log、perf_log 等既有表。 |
| 7 | migration 可 rollback | YES | `alembic downgrade 017` 执行成功，表与索引已删除；见【D】原始输出。 |

---

**文档结束**
