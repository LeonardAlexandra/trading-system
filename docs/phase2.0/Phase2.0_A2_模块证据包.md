# Phase2.0 A2 模块证据包：evaluation_report 表（评估报告，Phase 2.0 自有）

## 模块名称与目标

- **模块**：A2. evaluation_report 表（评估报告，满足 0.2，Phase 2.0 自有）
- **目标**：为 Evaluator 产出的评估报告提供持久化存储；满足 0.2 Evaluator Contract；表为 Phase 2.0 自有，禁止对 Phase 1.2 任何表执行写操作。

---

## 本模块涉及的变更文件清单

| 类型 | 路径 |
|------|------|
| 新增 | `src/models/evaluation_report.py` |
| 新增 | `alembic/versions/022_phase20_a2_evaluation_report.py` |
| 新增 | `docs/runlogs/phase20_a2_migration_20260214.txt` |
| 新增 | `docs/runlogs/phase20_a2_fk_insert_verify_20260214.txt` |
| 新增 | `docs/Phase2.0_A2_模块证据包.md`（本文件） |
| 修改 | `src/models/__init__.py`（导出 EvaluationReport） |

无删除；未修改任何 Phase 1.2 表或迁移。

---

## 【B】迁移脚本全文（与仓库一致）

以下为 `alembic/versions/022_phase20_a2_evaluation_report.py` 的完整内容，与仓库一致，供审查对照。

```python
"""Phase2.0 A2: evaluation_report 表（评估报告，满足 0.2，Phase 2.0 自有）

Revision ID: 022
Revises: 021
Create Date: 2026-02-14

Phase2.0 开发蓝本 C.2：评估报告表，为 Evaluator 产出提供持久化存储。
- 本表为 Phase 2.0 自有表；禁止对 Phase 1.2 任何表执行写操作。
- baseline_version_id 仅存 strategy_version_id，禁止存 param_version_id。
- 索引：(strategy_id, evaluated_at)、(strategy_version_id, evaluated_at)、(param_version_id, evaluated_at)。
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_report",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("strategy_version_id", sa.String(64), nullable=False),
        sa.Column("param_version_id", sa.String(64), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("objective_definition", sa.JSON(), nullable=False),
        sa.Column("constraint_definition", sa.JSON(), nullable=False),
        sa.Column(
            "baseline_version_id",
            sa.String(64),
            nullable=True,
            comment="仅存 strategy_version_id，禁止存 param_version_id",
        ),
        sa.Column("conclusion", sa.String(2048), nullable=False),
        sa.Column("comparison_summary", sa.JSON(), nullable=True),
        sa.Column(
            "metrics_snapshot_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("metrics_snapshot.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Phase2.0 自有表，评估报告；baseline_version_id 仅存 strategy_version_id，禁止「建议参数/写回/优化」语义。",
    )
    op.create_index(
        "idx_evaluation_report_strategy_evaluated",
        "evaluation_report",
        ["strategy_id", "evaluated_at"],
    )
    op.create_index(
        "idx_evaluation_report_version_evaluated",
        "evaluation_report",
        ["strategy_version_id", "evaluated_at"],
    )
    op.create_index(
        "idx_evaluation_report_param_evaluated",
        "evaluation_report",
        ["param_version_id", "evaluated_at"],
    )


def downgrade():
    op.drop_index("idx_evaluation_report_param_evaluated", table_name="evaluation_report")
    op.drop_index("idx_evaluation_report_version_evaluated", table_name="evaluation_report")
    op.drop_index("idx_evaluation_report_strategy_evaluated", table_name="evaluation_report")
    op.drop_table("evaluation_report")
```

---

## 核心实现代码（ORM 模型摘要）

- `src/models/evaluation_report.py`：表 `evaluation_report`，字段与 C.2 一致；id 与 metrics_snapshot_id 使用 `BigInteger().with_variant(Integer(), "sqlite")`；baseline_version_id 列 comment 明确仅存 strategy_version_id；metrics_snapshot_id 为 ForeignKey("metrics_snapshot.id")。完整代码见仓库。

---

## 【E】原始命令输出摘录（自包含）

以下为证据包自包含的关键原始输出，不依赖外部 runlog 即可核验。完整逐条见 `docs/runlogs/phase20_a2_migration_20260214.txt`。

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
INFO  [alembic.runtime.migration] Running upgrade 021 -> 022, Phase2.0 A2: evaluation_report 表（评估报告，满足 0.2，Phase 2.0 自有）
```
（stderr 无；Exit code: 0）

**2) downgrade 021：**
```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 022 -> 021, Phase2.0 A2: evaluation_report 表（评估报告，满足 0.2，Phase 2.0 自有）
```
（stderr 无；Exit code: 0）

**3) upgrade head（再次）：**
```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 021 -> 022, Phase2.0 A2: evaluation_report 表（评估报告，满足 0.2，Phase 2.0 自有）
```
（stderr 无；Exit code: 0）

### b) sqlite3 .schema evaluation_report 完整输出（含 FK 与索引 DDL）

```
CREATE TABLE evaluation_report (
	id INTEGER NOT NULL, 
	strategy_id VARCHAR(64) NOT NULL, 
	strategy_version_id VARCHAR(64) NOT NULL, 
	param_version_id VARCHAR(64), 
	evaluated_at DATETIME NOT NULL, 
	period_start DATETIME NOT NULL, 
	period_end DATETIME NOT NULL, 
	objective_definition JSON NOT NULL, 
	constraint_definition JSON NOT NULL, 
	baseline_version_id VARCHAR(64), 
	conclusion VARCHAR(2048) NOT NULL, 
	comparison_summary JSON, 
	metrics_snapshot_id INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(metrics_snapshot_id) REFERENCES metrics_snapshot (id)
);
CREATE INDEX idx_evaluation_report_strategy_evaluated ON evaluation_report (strategy_id, evaluated_at);
CREATE INDEX idx_evaluation_report_version_evaluated ON evaluation_report (strategy_version_id, evaluated_at);
CREATE INDEX idx_evaluation_report_param_evaluated ON evaluation_report (param_version_id, evaluated_at);
```

### c) evaluation_report 索引列表完整输出

命令：`sqlite3 phase20_a2_test.db "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='evaluation_report';"`

```
idx_evaluation_report_strategy_evaluated
idx_evaluation_report_version_evaluated
idx_evaluation_report_param_evaluated
```

---

## 【G】SQLite 自增主键验证（与 A1 同口径）

upgrade 到 head 后不传 id 插入 2 行 evaluation_report，SELECT 验证 id 自动生成且第二行 id > 第一行；downgrade 021 → upgrade head 后重复一次，证明幂等后行为一致。

### 第一次验证（upgrade head 后）

**命令（不传 id，仅必填列）：**
```bash
sqlite3 phase20_a2_test.db "
INSERT INTO evaluation_report (strategy_id, strategy_version_id, evaluated_at, period_start, period_end, objective_definition, constraint_definition, conclusion) VALUES ('s1', 'v1', '2026-01-01 12:00:00', '2026-01-01 00:00:00', '2026-01-02 00:00:00', '{}', '{}', 'ok');
INSERT INTO evaluation_report (strategy_id, strategy_version_id, evaluated_at, period_start, period_end, objective_definition, constraint_definition, conclusion) VALUES ('s1', 'v1', '2026-01-02 12:00:00', '2026-01-02 00:00:00', '2026-01-03 00:00:00', '{}', '{}', 'ok2');
SELECT id, strategy_id, evaluated_at, conclusion FROM evaluation_report ORDER BY id;
"
```

**原始 stdout：**
```
1|s1|2026-01-01 12:00:00|ok
2|s1|2026-01-02 12:00:00|ok2
```

结论：id 未传入，自动生成为 1、2；第二行 id(2) > 第一行 id(1)。

### 第二次验证（downgrade 021 → upgrade head 后）

执行 `alembic downgrade 021` 与 `alembic upgrade head` 后，表被重建，再次不传 id 插入 2 行。

**原始 stdout：**
```
1|s2|2026-02-01 12:00:00|a
2|s2|2026-02-02 12:00:00|b
```

结论：幂等后 id 仍自动生成且递增，行为与第一次一致。

---

## 【H】FK 行为正反两条实跑反证（PRAGMA foreign_keys=ON）

SQLite 默认 foreign_keys 关闭；开启后须验证：引用有效 metrics_snapshot.id 可插入，引用不存在的 id 须失败。

### 正向：引用有效 metrics_snapshot_id 插入成功

**命令：**
```bash
sqlite3 phase20_a2_test.db "
PRAGMA foreign_keys = ON;
INSERT INTO metrics_snapshot (strategy_id, strategy_version_id, period_start, period_end, trade_count, realized_pnl) VALUES ('fk_s', 'fk_v', '2026-01-01 00:00:00', '2026-01-02 00:00:00', 0, 0);
INSERT INTO evaluation_report (strategy_id, strategy_version_id, evaluated_at, period_start, period_end, objective_definition, constraint_definition, conclusion, metrics_snapshot_id) VALUES ('s1','v1','2026-01-01 12:00:00','2026-01-01 00:00:00','2026-01-02 00:00:00','{}','{}','ok', last_insert_rowid());
SELECT id, strategy_id, metrics_snapshot_id FROM evaluation_report WHERE conclusion='ok';
"
```

**原始 stdout：**
```
3|s1|2
```
Exit code: 0。结论：引用有效 id 的插入成功。

### 反向：引用不存在的 metrics_snapshot_id 插入失败

**命令：**
```bash
sqlite3 phase20_a2_test.db "
PRAGMA foreign_keys = ON;
INSERT INTO evaluation_report (strategy_id, strategy_version_id, evaluated_at, period_start, period_end, objective_definition, constraint_definition, conclusion, metrics_snapshot_id) VALUES ('s1','v1','2026-01-03 12:00:00','2026-01-03 00:00:00','2026-01-04 00:00:00','{}','{}','should_fail', 99999);
"
```

**原始 stderr：**
```
Error: stepping, FOREIGN KEY constraint failed (19)
```
Exit code: 19。结论：引用不存在的 metrics_snapshot_id 时，SQLite 在 foreign_keys=ON 下拒绝插入。

完整记录见 `docs/runlogs/phase20_a2_fk_insert_verify_20260214.txt`。

---

## baseline_version_id 口径说明（验收表对应）

**本模块采用“注释/文档明确、不做 DB 强制约束”的口径。**

- **含义**：baseline_version_id 在语义上仅允许存 strategy_version_id，禁止存 param_version_id；该约束由**写入层/应用层（如 C3 Evaluator）**保证，不在本迁移中增加 CHECK 或触发器。
- **理由**：在库内无法仅凭“字符串是否来自 strategy_version 表”做 CHECK（需依赖 strategy_version 表存在且可查）；蓝本 C.2 要求“仅存 strategy_version_id”为语义约束，由 0.2 写入方遵守。
- **证据包内已落实**：迁移脚本与 ORM 中 baseline_version_id 的 comment 均写明“仅存 strategy_version_id，禁止存 param_version_id”；表级 comment 禁止「建议参数/写回/优化」语义。若后续需 DB 级强制（如 FK 至 strategy_version 表），由后续模块扩展。

验收表中“文档明确 baseline_version_id 仅存 strategy_version_id、禁止「建议参数/写回/优化」语义”以**文档/注释口径**为准，本模块不做 DB 强制约束，强制校验留给写入层/后续模块。

---

## 与本模块 Acceptance Criteria 的逐条对照说明

| 验收口径 | 结果 | 证据定位 |
|----------|------|----------|
| 迁移可重复执行且可回滚 | YES | 【E】a) 三次 alembic 完整 stdout；runlog 第 1–3 节 |
| 表中存在上述索引及 C.2 全部字段；metrics_snapshot_id 可 FK 至 metrics_snapshot.id | YES | 【E】b)c) schema 与索引列表完整输出；【B】迁移脚本；【H】FK 正反验证 |
| 文档明确 baseline_version_id 仅存 strategy_version_id、禁止「建议参数/写回/优化」语义 | YES | 【B】表/列 comment；上文 baseline_version_id 口径说明（文档/注释口径，不做 DB 强制） |
| 未修改任何 Phase 1.2 表 | YES | runlog 第 6 节 rg 反证：仅 create_table/drop_table("evaluation_report") |
| SQLite 下 id 自增可靠（不传 id 插入、downgrade/upgrade 后仍成立） | YES | 【G】两次插入验证原始 stdout |
| metrics_snapshot_id FK 在 PRAGMA foreign_keys=ON 下有效且拒绝非法引用 | YES | 【H】正向插入成功、反向插入失败及原始输出 |

---

## 验收结论

- 是否满足模块目标：**是**。
- A2 范围内：仅新增 `evaluation_report` 表及三组索引、ORM 模型与迁移 022；未对 Phase 1.2 任何表执行写操作；迁移支持 alembic upgrade/downgrade，不破坏已有表；字段与索引符合蓝本 C.2；baseline_version_id 以文档/注释明确“仅存 strategy_version_id”，本模块不做 DB 强制约束。证据包已具备与 A1 同等的可审计性：迁移脚本全文【B】、原始命令输出【E】、自增验证【G】、FK 正反验证【H】及 baseline_version_id 口径说明均已自包含或可定位至 runlog。
