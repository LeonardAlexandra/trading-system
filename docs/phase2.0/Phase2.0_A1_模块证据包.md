# Phase2.0 A1 模块证据包：metrics_snapshot 表（指标快照，Phase 2.0 自有）

## 模块名称与目标

- **模块**：A1. metrics_snapshot 表（指标快照，Phase 2.0 自有）
- **目标**：为 Phase 2.0 指标计算产出提供持久化存储；表为 Phase 2.0 自有，禁止对 Phase 1.2 任何表执行写操作。

---

## 本次修改/新增的文件清单

| 类型 | 路径 |
|------|------|
| 新增 | `alembic/versions/021_phase20_a1_metrics_snapshot.py` |
| 新增 | `docs/runlogs/phase20_a1_alembic_upgrade_downgrade_20260214.txt` |
| 新增 | `docs/Phase2.0_A1_模块证据包.md`（本文件） |

无删除、无对 Phase 1.2 表或非 A1 范围文件的修改。

---

## 【B】迁移脚本全文（与仓库一致）

以下为 `alembic/versions/021_phase20_a1_metrics_snapshot.py` 的完整内容，与仓库一致，供审查对照。id 列在 SQLite 下使用 `Integer`（rowid 自增语义），在 PostgreSQL 下使用 `BigInteger`，通过 `with_variant` 实现。

```python
"""Phase2.0 A1: metrics_snapshot 表（指标快照，Phase 2.0 自有）

Revision ID: 021
Revises: 020
Create Date: 2026-02-14

Phase2.0 开发蓝本 C.1：指标快照表，为 Phase 2.0 指标计算产出提供持久化存储。
- 本表为 Phase 2.0 自有表；禁止对 Phase 1.2 任何表执行写操作。
- 表中仅存在 B.2/C.1 文档化字段，无未文档化列。
- 索引：(strategy_id, period_start, period_end)；(strategy_id, strategy_version_id)；
  (strategy_version_id, param_version_id, period_start)。
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "metrics_snapshot",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("strategy_version_id", sa.String(64), nullable=False),
        sa.Column("param_version_id", sa.String(64), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Numeric(18, 6), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("max_drawdown", sa.Numeric(20, 8), nullable=True),
        sa.Column("avg_holding_time_sec", sa.Numeric(18, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Phase2.0 自有表，仅存 B.2/C.1 文档化指标字段，无未文档化列；禁止对 Phase 1.2 表写操作。",
    )
    op.create_index(
        "idx_metrics_snapshot_strategy_period",
        "metrics_snapshot",
        ["strategy_id", "period_start", "period_end"],
    )
    op.create_index(
        "idx_metrics_snapshot_strategy_version",
        "metrics_snapshot",
        ["strategy_id", "strategy_version_id"],
    )
    op.create_index(
        "idx_metrics_snapshot_version_param_period",
        "metrics_snapshot",
        ["strategy_version_id", "param_version_id", "period_start"],
    )


def downgrade():
    op.drop_index("idx_metrics_snapshot_version_param_period", table_name="metrics_snapshot")
    op.drop_index("idx_metrics_snapshot_strategy_version", table_name="metrics_snapshot")
    op.drop_index("idx_metrics_snapshot_strategy_period", table_name="metrics_snapshot")
    op.drop_table("metrics_snapshot")
```

---

## 本模块核心实现代码（摘要）

- 建表 `metrics_snapshot`：字段 id（PostgreSQL 为 BIGINT、SQLite 为 INTEGER 自增，PK）、strategy_id、strategy_version_id、param_version_id、period_start、period_end、trade_count、win_rate、realized_pnl、max_drawdown、avg_holding_time_sec、created_at，与 C.1 一致；无未文档化列。
- 表注释：`Phase2.0 自有表，仅存 B.2/C.1 文档化指标字段，无未文档化列；禁止对 Phase 1.2 表写操作。`
- 三组索引：`(strategy_id, period_start, period_end)`、`(strategy_id, strategy_version_id)`、`(strategy_version_id, param_version_id, period_start)`。
- `downgrade()`：先删三索引，再删表；未修改 Phase 1.2 任何表。

---

## 【D】环境与执行命令（原文）

以下为【E】输出所对应的环境与命令原文，便于复现与审计。

### DATABASE_URL 真实取值

执行时在每条 alembic 命令前内联传入，未使用 `export`。取值为（与 runlog 一致）：

```
sqlite:////Users/zhangkuo/TradingView Indicator/trading_system/phase20_a1_test.db
```

复现时可用 `echo` 核验后传入，例如：`export DATABASE_URL='sqlite:////Users/zhangkuo/TradingView Indicator/trading_system/phase20_a1_test.db'` 再执行下述 alembic 命令；或直接在下述命令中保留 `DATABASE_URL="..."` 前缀。

### 三条 alembic 命令原文（与【E】a) 输出一一对应）

1. **upgrade head（首次）**  
   ```bash
   DATABASE_URL="sqlite:////Users/zhangkuo/TradingView Indicator/trading_system/phase20_a1_test.db" alembic upgrade head
   ```  
   → 对应【E】a) 第 1 段 stdout（含 001→…→021）。

2. **downgrade 020**  
   ```bash
   DATABASE_URL="sqlite:////Users/zhangkuo/TradingView Indicator/trading_system/phase20_a1_test.db" alembic downgrade 020
   ```  
   → 对应【E】a) 第 2 段 stdout。

3. **upgrade head（再次）**  
   ```bash
   DATABASE_URL="sqlite:////Users/zhangkuo/TradingView Indicator/trading_system/phase20_a1_test.db" alembic upgrade head
   ```  
   → 对应【E】a) 第 3 段 stdout。

### sqlite3 操作的 db 与 DATABASE_URL 指向同一文件

- **DATABASE_URL** 中 SQLite 路径为：`/Users/zhangkuo/TradingView Indicator/trading_system/phase20_a1_test.db`（`sqlite:///` 后的绝对路径，四斜杠表示绝对路径）。
- **sqlite3** 命令在项目根目录（`trading_system`）下执行，使用相对路径 `phase20_a1_test.db`，即同一文件。  
  完整路径等价：`/Users/zhangkuo/TradingView Indicator/trading_system/phase20_a1_test.db`。

复现时若使用相对路径，可统一在项目根执行：  
`sqlite3 phase20_a1_test.db ".schema metrics_snapshot"` 与  
`DATABASE_URL="sqlite:///./phase20_a1_test.db" alembic upgrade head`（或使用上述绝对路径），确保指向同一 db 文件。

---

## 【E】原始命令输出摘录（来自 runlog）

以下为 `docs/runlogs/phase20_a1_alembic_upgrade_downgrade_20260214.txt` 中的关键原始输出，证据包自包含以便不依赖外部文件即可核验。完整逐条输出见该 runlog 文件。

### a) 3 次 alembic 完整 stdout

**1) upgrade head（首次，完整）：**
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
INFO  [alembic.runtime.migration] Running upgrade 019 -> 020, Phase1.2 A3: perf_log 表（性能日志，1.2b）
INFO  [alembic.runtime.migration] Running upgrade 020 -> 021, Phase2.0 A1: metrics_snapshot 表（指标快照，Phase 2.0 自有）
```
（stderr 无；Exit code: 0）

**2) downgrade 020：**
```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 021 -> 020, Phase2.0 A1: metrics_snapshot 表（指标快照，Phase 2.0 自有）
```
（stderr 无；Exit code: 0）

**3) upgrade head（再次，幂等）：**
```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 020 -> 021, Phase2.0 A1: metrics_snapshot 表（指标快照，Phase 2.0 自有）
```
（stderr 无；Exit code: 0）

### b) sqlite3 .schema metrics_snapshot 完整输出（修 id 自增后：SQLite 下 id 为 INTEGER）

```
CREATE TABLE metrics_snapshot (
	id INTEGER NOT NULL, 
	strategy_id VARCHAR(64) NOT NULL, 
	strategy_version_id VARCHAR(64) NOT NULL, 
	param_version_id VARCHAR(64), 
	period_start DATETIME NOT NULL, 
	period_end DATETIME NOT NULL, 
	trade_count INTEGER NOT NULL, 
	win_rate NUMERIC(18, 6), 
	realized_pnl NUMERIC(20, 8) NOT NULL, 
	max_drawdown NUMERIC(20, 8), 
	avg_holding_time_sec NUMERIC(18, 6), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX idx_metrics_snapshot_strategy_period ON metrics_snapshot (strategy_id, period_start, period_end);
CREATE INDEX idx_metrics_snapshot_strategy_version ON metrics_snapshot (strategy_id, strategy_version_id);
CREATE INDEX idx_metrics_snapshot_version_param_period ON metrics_snapshot (strategy_version_id, param_version_id, period_start);
```

### c) sqlite3 查询 metrics_snapshot 索引列表完整输出

```
sqlite_autoindex_metrics_snapshot_1
idx_metrics_snapshot_strategy_period
idx_metrics_snapshot_strategy_version
idx_metrics_snapshot_version_param_period
```

**runlog 定位**：上述 a)b)c) 与 `docs/runlogs/phase20_a1_alembic_upgrade_downgrade_20260214.txt` 中「1) 首次 upgrade head」「2) downgrade」「3) 再次 upgrade head」「4) .schema metrics_snapshot」「5) 索引列表」一一对应。

**命名歧义说明**：日志中较早出现的 “A1”“A2”“A3”（如 012→013 的 “A1: strategy_runtime_state”、013→014 的 “A2: trade 表”、017→018 的 “Phase1.2 A1: decision_snapshot” 等）属于历史阶段或 Phase1.2 的迁移命名，非本模块。**本模块以 revision 021 的 docstring 为准**：“Phase2.0 A1: metrics_snapshot 表（指标快照，Phase 2.0 自有）”；即仅 020→021 这一条为 Phase2.0 A1 的迁移输出。

---

## 【F】禁止对 Phase1.2 表写操作的反证式校验

执行以下命令，证明迁移脚本中仅出现对 `metrics_snapshot` 的建表/删表，无对 Phase1.2 表（decision_snapshot、trade、execution、log 等）的 create_table/drop_table/add_column/drop_column/execute。

**命令：**
```bash
rg -n "op\.(create_table|drop_table|add_column|drop_column|execute)\(" alembic/versions/021_phase20_a1_metrics_snapshot.py
```

**原始输出：**
```
23:    op.create_table(
65:    op.drop_table("metrics_snapshot")
```

**结论**：仅命中两处——第 23 行 `op.create_table(`（脚本中表名为 `"metrics_snapshot"`）、第 65 行 `op.drop_table("metrics_snapshot")`。无 `add_column`、`drop_column`、`execute`；无任何 Phase1.2 表名。可证明本迁移仅触及 `metrics_snapshot` 表，未对 Phase1.2 表执行写操作。

---

## 【G】SQLite 最小插入验证（自增主键）

在 upgrade 到 head 后，向 `metrics_snapshot` 插入 2 行（**不传 id 字段**），再 SELECT 证明 id 自动生成且第二行 id > 第一行 id。downgrade 020 → upgrade head 后重复一次，证明幂等后自增行为一致。

### 第一次验证（upgrade head 后）

**命令（不传 id）：**
```bash
sqlite3 phase20_a1_test.db "
INSERT INTO metrics_snapshot (strategy_id, strategy_version_id, period_start, period_end, trade_count, realized_pnl) VALUES ('s1', 'v1', '2026-01-01 00:00:00', '2026-01-02 00:00:00', 1, 100.5);
INSERT INTO metrics_snapshot (strategy_id, strategy_version_id, period_start, period_end, trade_count, realized_pnl) VALUES ('s1', 'v1', '2026-01-02 00:00:00', '2026-01-03 00:00:00', 2, 200.0);
SELECT id, strategy_id, period_start, period_end, trade_count, realized_pnl FROM metrics_snapshot ORDER BY id;
"
```

**原始 stdout：**
```
1|s1|2026-01-01 00:00:00|2026-01-02 00:00:00|1|100.5
2|s1|2026-01-02 00:00:00|2026-01-03 00:00:00|2|200
```

**结论**：id 未传入，自动生成为 1、2；第二行 id(2) > 第一行 id(1)。

### 第二次验证（downgrade 020 → upgrade head 后）

执行 `alembic downgrade 020` 与 `alembic upgrade head` 后，表被重建，再次插入 2 行（不传 id）。

**命令：**
```bash
sqlite3 phase20_a1_test.db "
INSERT INTO metrics_snapshot (strategy_id, strategy_version_id, period_start, period_end, trade_count, realized_pnl) VALUES ('s2', 'v2', '2026-02-01 00:00:00', '2026-02-02 00:00:00', 0, 0);
INSERT INTO metrics_snapshot (strategy_id, strategy_version_id, period_start, period_end, trade_count, realized_pnl) VALUES ('s2', 'v2', '2026-02-02 00:00:00', '2026-02-03 00:00:00', 3, -50.25);
SELECT id, strategy_id, period_start, period_end, trade_count, realized_pnl FROM metrics_snapshot ORDER BY id;
"
```

**原始 stdout：**
```
1|s2|2026-02-01 00:00:00|2026-02-02 00:00:00|0|0
2|s2|2026-02-02 00:00:00|2026-02-03 00:00:00|3|-50.25
```

**结论**：幂等（downgrade/upgrade）后 id 仍自动生成，第二行 id(2) > 第一行 id(1)，行为与第一次一致。

**说明**：初版迁移使用 `sa.BigInteger()` 时，SQLite 下插入不传 id 会触发 NOT NULL 约束失败（id 未自增）。已改为 `sa.BigInteger().with_variant(sa.Integer(), "sqlite")`，使 SQLite 使用 INTEGER PRIMARY KEY（rowid 自增语义），自增可靠。

---

## SQLite 验收范围声明（P2 口径收敛）

**本阶段（A1）仅提供 SQLite 审计证据；PostgreSQL 不在 A1 验收范围内。**

- 所有实跑命令与原始输出均在 SQLite 下执行并记录；证据包与 runlog 不依赖 PostgreSQL 环境。
- 迁移脚本使用 `with_variant(sa.Integer(), "sqlite")` 保证 SQLite 下 id 自增可靠；PostgreSQL 下仍为 BIGINT，行为由后续阶段或 PG 环境验收时另行验证。
- 避免 SQLite/PostgreSQL 口径漂移：A1 验收以本证据包内 SQLite 证据为准，不声称 PG 等价结论。

---

## 本模块对应的测试用例 / 可复现实跑步骤

- 无独立测试代码（A1 为纯迁移模块）。
- 可复现步骤（A1 仅验收 SQLite）：
  1. 设置 `DATABASE_URL` 为 SQLite（如 `sqlite:///./trading_system.db` 或绝对路径）。
  2. `alembic upgrade head` → 应执行 020 -> 021 无报错。
  3. `alembic downgrade 020` → 应执行 021 -> 020 无报错。
  4. `alembic upgrade head` → 应再次执行 020 -> 021 无报错（幂等）。
  5. 使用 `sqlite3` 查看 `metrics_snapshot` 表结构及三组索引（见【E】b)c)）。
  6. 不传 id 插入 2 行并 SELECT，验证 id 自增且第二行 id > 第一行（见【G】）。

---

## 测试命令与原始输出结果

完整原始输出已写入 `docs/runlogs/phase20_a1_alembic_upgrade_downgrade_20260214.txt`，证据包【E】中已摘录关键片段以便自包含核验。runlog 与证据包引用关系见【E】末尾「runlog 定位」。

---

## 与本模块 Acceptance Criteria 的逐条对照说明

| 验收口径 | 结果 | 证据定位 |
|----------|------|----------|
| 迁移可重复执行（upgrade/downgrade 无报错，幂等） | YES | 【E】a) 三次 alembic 完整 stdout；runlog 第 1–3 节 |
| 表中存在上述三组索引及 C.1 全部字段 | YES | 【E】b)c) schema 与索引列表完整输出；【B】迁移脚本全文字段与索引定义 |
| 文档或注释明确本表为 Phase 2.0 自有、仅存 B.2 指标，无未文档化列 | YES | 【B】迁移脚本全文 docstring 与 create_table comment |
| 迁移仅触及 metrics_snapshot、禁止对 Phase1.2 表写操作 | YES | 【F】rg 反证原始输出与结论 |
| SQLite 下 id 自增可靠（不传 id 插入、downgrade/upgrade 后仍成立） | YES | 【G】两次插入验证原始 stdout |

---

## 验收结论

- 是否满足模块目标：**是**。
- A1 范围内：仅新增 `metrics_snapshot` 表及三组索引，未对 Phase 1.2 任何表执行写操作（【F】可证）；迁移支持 alembic upgrade/downgrade，不破坏已有表；字段与索引符合蓝本 C.1；文档/注释已明确 Phase 2.0 自有与无未文档化列。SQLite 下主键 id 自增已通过【G】实跑验证（含 downgrade/upgrade 后重复验证）。本阶段仅提供 SQLite 审计证据，PG 不在 A1 验收范围（口径收敛）。证据包已具备可审计性/可复现性：迁移脚本全文【B】、原始命令输出【E】、反证【F】、自增验证【G】及 SQLite 范围声明均已包含，可仅凭本证据包与 runlog 完成复核。
