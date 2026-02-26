# Phase1.2 A2 模块证据包

**模块编号**: A2  
**模块名称**: log 表（审计/操作/错误日志）  
**交付日期**: 2026-02-07

---

## 【A】变更文件清单

| 类型 | 文件路径 | 用途 |
|------|----------|------|
| 新增 | `alembic/versions/019_phase12_a2_log.py` | A2 数据库迁移（建表、索引，upgrade/downgrade） |
| 新增 | `src/models/log_entry.py` | log 表 ORM 模型（仅结构定义） |
| 修改 | `src/models/__init__.py` | 导出 `LogEntry` |

---

## 【B】Alembic migration 文件全文

**文件**: `alembic/versions/019_phase12_a2_log.py`

```python
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
```

---

## 【C】log ORM / schema 文件全文

**文件**: `src/models/log_entry.py`

```python
"""
Phase1.2 A2：log 表（审计/操作/错误日志）

仅结构定义，用于 ORM/只读层。蓝本 C.1。
- level 仅允许：INFO, WARNING, ERROR, AUDIT（C.3）
- 脱敏、LogRepository、写入与查询由 C3 实现，本模块不实现。
"""
from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.sql import func

from src.database.connection import Base


class LogEntry(Base):
    """
    审计/操作/错误日志表（Phase1.2 蓝本 C.1）。
    level 枚举：INFO, WARNING, ERROR, AUDIT。分页查询须带 limit/offset，单次上限由接口约定（如 1000 条）。
    """
    __tablename__ = "log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    component = Column(String(64), nullable=False)
    level = Column(String(16), nullable=False)  # INFO | WARNING | ERROR | AUDIT
    message = Column(Text(), nullable=False)
    event_type = Column(String(32), nullable=True)
    payload = Column(JSON(), nullable=True)
```

---

## 【D】迁移执行命令与原始输出

### 执行命令

```bash
cd /Users/zhangkuo/TradingView\ Indicator/trading_system
export DATABASE_URL=sqlite:///./phase12_a2_evidence.db
alembic upgrade head
alembic current
alembic downgrade 018
alembic upgrade 019
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
INFO  [alembic.runtime.migration] Running upgrade 018 -> 019, Phase1.2 A2: log 表（审计/操作/错误日志）
```

**alembic current**

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
019 (head)
```

**alembic downgrade 018**

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 019 -> 018, Phase1.2 A2: log 表（审计/操作/错误日志）
```

**alembic upgrade 019**

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 018 -> 019, Phase1.2 A2: log 表（审计/操作/错误日志）
```

**表结构验证（sqlite3 .schema log）**

```
CREATE TABLE log (
	id INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	component VARCHAR(64) NOT NULL, 
	level VARCHAR(16) NOT NULL, 
	message TEXT NOT NULL, 
	event_type VARCHAR(32), 
	payload JSON, 
	PRIMARY KEY (id)
);
CREATE INDEX idx_log_created_component_level ON log (created_at, component, level);
```

---

## 【E】Acceptance Criteria 逐条对照（YES / NO + 证据）

| # | 验收口径 | 结论 | 证据 |
|---|----------|------|------|
| 1 | 迁移可重复执行且可回滚 | YES | 已执行 `alembic upgrade head`、`alembic downgrade 018`、`alembic upgrade 019`，均无报错；见【D】原始输出。 |
| 2 | 表中存在 (created_at, component, level) 索引 | YES | 迁移中定义 `create_index("idx_log_created_component_level", "log", ["created_at", "component", "level"])`；sqlite3 `.schema log` 输出中可见 `CREATE INDEX idx_log_created_component_level ON log (created_at, component, level)`。 |
| 3 | 文档明确 level 枚举与分页要求 | YES | 迁移文件注释写明「level 仅允许：INFO, WARNING, ERROR, AUDIT」；模型文件注释写明「level 枚举：INFO, WARNING, ERROR, AUDIT」「分页查询须带 limit/offset，单次上限由接口约定（如 1000 条）」。 |

---

## 【F】系统级最小可用性验证（写入 / 查询）

### 新增文件清单

| 文件路径 | 用途 |
|----------|------|
| `scripts/phase12_a2_log_smoke_test.py` | 临时验证脚本：向 log 表插入 1 条记录并立即按 id 查询回显，证明表可被系统写入与读取。 |

### 验证脚本全文

**文件**: `scripts/phase12_a2_log_smoke_test.py`

```python
#!/usr/bin/env python3
"""
Phase1.2 A2 系统级最小可用性验证：向 log 表写入 1 条记录并查询回显。
临时验证脚本，不实现 LogRepository；仅证明 log 表可被系统写入与读取。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.models.log_entry import LogEntry


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        url = "sqlite+aiosqlite:///./phase12_a2_evidence.db"
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        url = "sqlite+aiosqlite://" + url[len("sqlite://"):]
    return url


async def main() -> None:
    db_url = _get_db_url()
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        entry = LogEntry(
            component="test_smoke",
            level="INFO",
            message="phase1.2 A2 smoke test",
            event_type="SMOKE_TEST",
            payload={"ok": True},
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        row_id = entry.id

        result = await session.execute(select(LogEntry).where(LogEntry.id == row_id))
        row = result.scalar_one()

    print("--- phase1.2 A2 log smoke test: inserted and queried ---")
    print(f"id: {row.id}")
    print(f"created_at: {row.created_at}")
    print(f"component: {row.component}")
    print(f"level: {row.level}")
    print(f"message: {row.message}")
    print(f"event_type: {row.event_type}")
    print(f"payload: {row.payload}")
    print("--- end ---")


if __name__ == "__main__":
    asyncio.run(main())
```

### 执行命令

```bash
cd /Users/zhangkuo/TradingView\ Indicator/trading_system
DATABASE_URL=sqlite:///./phase12_a2_evidence.db python scripts/phase12_a2_log_smoke_test.py
```

### 数据库说明

- 使用 SQLite 时，数据库文件路径：项目根目录下 `phase12_a2_evidence.db`（即 `trading_system/phase12_a2_evidence.db`）。执行前需已对该库执行 `alembic upgrade head` 或至少 `alembic upgrade 019`。

### 原始输出

```
--- phase1.2 A2 log smoke test: inserted and queried ---
id: 1
created_at: 2026-02-07 10:37:28
component: test_smoke
level: INFO
message: phase1.2 A2 smoke test
event_type: SMOKE_TEST
payload: {'ok': True}
--- end ---
```

### 结论

已证明 log 表可被系统写入与查询，满足 Phase1.2 A2 的系统可用性要求。

---

**文档结束**
