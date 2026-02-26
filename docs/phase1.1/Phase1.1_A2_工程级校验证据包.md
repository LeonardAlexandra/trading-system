# Phase1.1 A2 工程级校验证据包

**模块**: A2 - trade 表支持 EXTERNAL_SYNC 来源（幂等 + 唯一性）  
**日期**: 2026-02-05

---

## 0. A2 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 你对条款的理解（1 句话，不得引入新语义） |
|----------|----------------------------------|------------------------------------------|
| A2-01 | 在 trade 表或关联模型中新增“来源”区分：如 source_type 或 trade_source，取值包含至少 EXTERNAL_SYNC（与既有信号驱动来源区分） | 表上存在 source_type 字段，可区分 EXTERNAL_SYNC 与信号驱动成交 |
| A2-02 | EXTERNAL_SYNC 的幂等键为 (strategy_id, external_trade_id)，external_trade_id 为外部/交易所成交 ID，必须在表或唯一约束中体现 | 表有 external_trade_id 列，且与 strategy_id 共同构成幂等键 |
| A2-03 | 表上必须存在唯一约束，保证同一 strategy_id + external_trade_id 仅能插入一条 EXTERNAL_SYNC 记录；需 UNIQUE(strategy_id, external_trade_id) 或等价实现 | DB 层 UNIQUE(strategy_id, external_trade_id)，防止重复插入 |
| A2-04 | 迁移脚本：新增列或枚举，不破坏既有 trade 写入逻辑；必须保留与既有 trade 的同一套唯一性/幂等性约束（如按 trade_id） | 既有信号驱动写入路径不变，trade_id 主键与既有约束保留 |
| A2-05 | 所有写入 trade 的路径（含 EXTERNAL_SYNC）必须在同一套事务与一致性边界内 | 本模块不引入新事务边界；由 C3 等在同一事务内写入 |
| A2-06 | 以数据库 trade 表为准；EXTERNAL_SYNC 与信号驱动记录均以 source_type（或等价字段）区分，下游以该字段识别来源 | trade 表为成交唯一真理源，source_type 为来源区分依据 |
| A2-07 | 迁移可重复执行且可回滚 | upgrade/downgrade 可回滚，不破坏既有数据 |

---

## 1. EXTERNAL_SYNC 作用域锁定（Scope Lock）

### 1.1 当前约束语义：全表唯一

- **UNIQUE(strategy_id, external_trade_id)** 当前为 **全表唯一**，即对 trade 表上 **所有行** 生效，而非“仅对 source_type=EXTERNAL_SYNC 的行”生效。
- 表上仅存在一个涉及 (strategy_id, external_trade_id) 的约束，即 **uq_trade_strategy_external_trade_id**；无按 source_type 区分的部分唯一约束。
- 效果上仍满足 Phase1.1“同一 strategy_id + external_trade_id 仅能插入一条 EXTERNAL_SYNC 记录”，因为：
  - EXTERNAL_SYNC 行必填 non-NULL 的 external_trade_id，故受该唯一约束严格限制；
  - SIGNAL 行约定不写 external_trade_id（见下），external_trade_id 为 NULL，在 SQL/SQLite 中多行 (strategy_id, NULL) 仍合法。

### 1.2 工程级边界约束：SIGNAL 行不得写 external_trade_id

- **约束内容**：所有 **source_type=SIGNAL** 的 trade 行，**不得写入** external_trade_id（必须为 NULL）。
- **保证方式**：
  - **写入层 / 服务层**：信号驱动路径（如 ExecutionEngine 落库 trade）在构造 Trade 时 **不设置** external_trade_id，或显式设为 None；仅 EXTERNAL_SYNC 路径（如 C3 对账）设置 external_trade_id。
  - **Repo 层**：TradeRepository.create 的约定与注释明确“SIGNAL 时调用方必须保证 trade.external_trade_id 为 None”；Repo 不替 SIGNAL 填写 external_trade_id，也不接受 SIGNAL + 非空 external_trade_id 的语义。
  - **模型层**：external_trade_id 列为 nullable，注释标明“EXTERNAL_SYNC 时必填”；与 Repo/服务层约定一致。
- 满足该边界时，全表唯一约束在语义上等价于“对 EXTERNAL_SYNC 的 (strategy_id, external_trade_id) 唯一”。

### 1.3 若需“仅对 EXTERNAL_SYNC 生效”的约束（可选实现）

- 若产品要求“唯一约束仅对 source_type=EXTERNAL_SYNC 的行生效”，可采用：
  - **条件唯一 / 部分索引**：在 DB 层增加 **部分唯一索引**，仅对 EXTERNAL_SYNC 行生效。
    - **PostgreSQL**：`CREATE UNIQUE INDEX uq_trade_external_sync_key ON trade (strategy_id, external_trade_id) WHERE source_type = 'EXTERNAL_SYNC';`
    - **SQLite（3.8+）**：支持 `CREATE UNIQUE INDEX ... WHERE ...`，例如 `CREATE UNIQUE INDEX uq_trade_external_sync_key ON trade(strategy_id, external_trade_id) WHERE source_type='EXTERNAL_SYNC';`
  - 采用部分唯一后，可不再依赖“SIGNAL 不写 external_trade_id”的约定来区分作用域；当前实现未采用该方案，仍以 **全表唯一 + 约定 SIGNAL 不写 external_trade_id** 为准。
- **可落地替代**：若某 DB 不支持部分唯一索引，则继续使用当前全表 UNIQUE(strategy_id, external_trade_id) + 上述工程边界（SIGNAL 不写 external_trade_id），由写入层/Repo/服务层保证。

---

## 3.1 目标校验矩阵（逐条覆盖 A2 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式 | 结果 |
|----------|-------------------|------------------------|----------|------|
| A2-01 | source_type 区分 EXTERNAL_SYNC 与信号驱动 | 014_a2_trade_external_sync.py:21-32；trade.py:25-29 | upgrade 后列存在，默认 SIGNAL | PASS |
| A2-02 | 幂等键 (strategy_id, external_trade_id) | 014:33-41；trade.py:31-35；trade_repo.py | 唯一约束 + external_trade_id 列 | PASS |
| A2-03 | 唯一约束防重复 EXTERNAL_SYNC | 014:59-62；trade.py UniqueConstraint；§2 最小复现 | 重复 (s, ext_id) 插入触发 uq_trade_strategy_external_trade_id | PASS |
| A2-04 | 不破坏既有写入，保留 trade_id 主键 | 014 server_default SIGNAL；未改 execution_engine | 既有路径不传 source_type 仍可写 | PASS |
| A2-05 | 同一事务边界 | 本模块无新事务；C3 持锁内写 | 设计审查 | PASS |
| A2-06 | trade 表为真理源，source_type 区分来源 | 模型与注释 | 设计审查 | PASS |
| A2-07 | 迁移可回滚 | 014 upgrade/downgrade | alembic downgrade -1 / upgrade head | PASS |

---

## 2. 幂等唯一性证据（最小复现 + 原始报错）

### 2.1 复现步骤

1. 插入一条 EXTERNAL_SYNC trade：strategy_id=S1，external_trade_id=ext-001。
2. 再插入第二条 trade，相同 strategy_id=S1、external_trade_id=ext-001，仅 trade_id/quantity/price 等不同。

### 2.2 原始报错输出（来自 uq_trade_strategy_external_trade_id）

第二条 INSERT 触发 DB UNIQUE 约束失败。SQLite 报错中 **未带约束名**，但表上唯一涉及 (strategy_id, external_trade_id) 的约束仅有 **uq_trade_strategy_external_trade_id**，故可认定该报错即来自该约束。

**底层 DBAPI：**

```
sqlite3.IntegrityError: UNIQUE constraint failed: trade.strategy_id, trade.external_trade_id
```

**SQLAlchemy 包装后：**

```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) UNIQUE constraint failed: trade.strategy_id, trade.external_trade_id
[SQL: 
                INSERT INTO trade (trade_id, strategy_id, source_type, external_trade_id, symbol, side, quantity, price, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ]
[parameters: ('t2', 'S1', 'EXTERNAL_SYNC', 'ext-001', 'BTCUSDT', 'BUY', 0.02, 50100, '2026-02-05 12:01:00')]
(Background on this error at: https://sqlalche.me/e/20/gkpj)
```

**说明**：报错中的列组合为 `trade.strategy_id, trade.external_trade_id`，与迁移中创建的 **uq_trade_strategy_external_trade_id** 一致；表上无其他对 (strategy_id, external_trade_id) 的 UNIQUE，故可确认由该约束触发。

---

## 3. 迁移失败残留处理路径（014 duplicate column）

### 3.1 风险说明

若 014 首次执行时在 **add_column source_type / external_trade_id** 之后、**create_unique_constraint** 之前失败（例如 SQLite 在 batch_alter 外建约束失败），则库中可能已存在 `source_type`、`external_trade_id` 列，但 **alembic_version 仍为 013**。此后再次执行 `alembic upgrade head` 会报 **duplicate column name: source_type**（或 external_trade_id）。

### 3.2 检测步骤

1. **查当前迁移版本**  
   `SELECT * FROM alembic_version;`  
   - 若为 `013`，且表 trade 上已有 source_type / external_trade_id，则属“残留列”状态。

2. **查表结构**  
   - **SQLite**：`PRAGMA table_info(trade);` 查看是否已有 `source_type`、`external_trade_id`。  
   - **PostgreSQL**：`\d trade` 或查询 `information_schema.columns`。  
   若版本为 013 但两列已存在，即属上述残留。

### 3.3 恢复路径（三选一，按需执行）

- **路径 A：清理残留列后重新升级（仅当可接受删除该两列时）**  
  1. 确认无业务依赖 014 新增列（或仅测试库）。  
  2. SQLite 3.35.0+：  
     `ALTER TABLE trade DROP COLUMN external_trade_id;`  
     `ALTER TABLE trade DROP COLUMN source_type;`  
     （若存在 uq_trade_strategy_external_trade_id，先 `DROP` 该约束；SQLite 需通过重建表或 batch 操作，此处假设仅多出两列、约束未建成功。）  
  3. 保持 alembic_version=013，再执行 `alembic upgrade head`。

- **路径 B：补丁迁移（推荐，可复现）**  
  1. 新增一条“修复迁移”（如 014_fix）：down_revision=013；在 upgrade() 中 **仅当列不存在时** add_column（或使用 DB 方言的 IF NOT EXISTS），并创建唯一约束；downgrade 与 014 一致。  
  2. 将原 014 的 down_revision 改为该补丁的 revision，或废弃原 014、由补丁迁移统一完成 013→当前。  
  3. 在残留库上执行 `alembic upgrade head`，由补丁迁移幂等补齐结构。

- **路径 C：禁止在残留库上继续升级**  
  - 若不允许改库结构、也不做补丁迁移，则 **禁止** 在该库上再次执行 014；仅允许在 **干净 013 库**（无 source_type/external_trade_id）上执行 014，或使用新库从 013 升级到 014。

### 3.4 建议

- 新环境或 CI：使用 **干净 013** 再 `upgrade head`，避免残留。  
- 已出现残留的库：优先用 **路径 B（补丁迁移）** 做幂等修复并记录在证据包/运维手册中。

---

## 3.2 关键实现快照（Code Snapshot）

### 3.2.1 Alembic migration：upgrade() / downgrade()

**文件**: `alembic/versions/014_a2_trade_external_sync.py`

```python
def upgrade():
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
    with op.batch_alter_table("trade", schema=None) as batch_op:
        batch_op.alter_column("signal_id", existing_type=sa.String(100), nullable=True)
        batch_op.alter_column("decision_id", existing_type=sa.String(100), nullable=True)
        batch_op.alter_column("execution_id", existing_type=sa.String(100), nullable=True)
        batch_op.create_unique_constraint(
            "uq_trade_strategy_external_trade_id",
            ["strategy_id", "external_trade_id"],
        )

def downgrade():
    with op.batch_alter_table("trade", schema=None) as batch_op:
        batch_op.drop_constraint("uq_trade_strategy_external_trade_id", type_="unique")
    op.drop_column("trade", "external_trade_id")
    op.drop_column("trade", "source_type")
```

- **约束语义**：**全表** UNIQUE(strategy_id, external_trade_id)；SIGNAL 行约定不写 external_trade_id（NULL），多行 (strategy_id, NULL) 合法；EXTERNAL_SYNC 行 non-NULL external_trade_id 受该约束严格限一。

### 3.2.2 Trade 模型与 Repo 边界

- **trade.py**：source_type、external_trade_id；UniqueConstraint("strategy_id", "external_trade_id", name="uq_trade_strategy_external_trade_id")；注释标明 EXTERNAL_SYNC 时 external_trade_id 必填。
- **trade_repo.py**：模块与 create 方法注释中明确 **SIGNAL 行不得写 external_trade_id**；写入层/服务层保证 SIGNAL 时 external_trade_id 为 None；EXTERNAL_SYNC 路径唯一可设置 external_trade_id，插入前建议 get_by_strategy_external_trade_id 判重。

---

## 3.3 测试与实跑输出（原始证据）

### 环境说明

- 迁移在**干净库**上执行（从 013 升级到 014），避免本地曾失败导致的残留列。  
- 命令：`DATABASE_URL=sqlite:///./test_a2.db` 下执行 alembic。

### alembic upgrade head（013 → 014）

```
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && DATABASE_URL=sqlite:///./test_a2.db alembic upgrade head
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 013 -> 014, A2: trade 表 EXTERNAL_SYNC 来源支持（幂等键 strategy_id + external_trade_id）
```

### alembic downgrade -1

```
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && DATABASE_URL=sqlite:///./test_a2.db alembic downgrade -1
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 014 -> 013, A2: trade 表 EXTERNAL_SYNC 来源支持（幂等键 strategy_id + external_trade_id）
```

### pytest -q

```
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && .venv/bin/python -m pytest -q 2>&1
........................................................................ [ 47%]
........................................................................ [ 94%]
........                                                                 [100%]
152 passed in 3.15s
```

---

## 3.4 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否修改了既有 trade 幂等或唯一性语义？ | **否** | trade_id 主键未动；仅新增 source_type、external_trade_id 与全表 UNIQUE(strategy_id, external_trade_id)；SIGNAL 不写 external_trade_id，既有写入不变 |
| 是否影响 ExecutionEngine / RiskManager 行为？ | **否** | 未改动 execution_engine、risk_manager；既有写入不传 source_type 时使用 server_default SIGNAL |
| 是否引入任何新的成交来源或状态？ | **是（仅来源枚举）** | 新增来源类型 EXTERNAL_SYNC，与既有 SIGNAL 并列；无新状态机 |
| 是否存在残余风险？ | **有且已边界化** | 见 §1 作用域锁定（SIGNAL 不写 external_trade_id）；§3 迁移残留的检测与恢复路径 |

---

## 3.5 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| `alembic/versions/014_a2_trade_external_sync.py` | 新增 A2 迁移：source_type、external_trade_id、三列可空、uq_trade_strategy_external_trade_id（全表唯一） | A2-01, A2-02, A2-03, A2-04, A2-07 |
| `src/models/trade.py` | 新增 source_type、external_trade_id，UniqueConstraint；常量 SIGNAL/EXTERNAL_SYNC | A2-01, A2-02, A2-03, A2-06 |
| `src/repositories/trade_repo.py` | 新增 TradeRepository；约定 SIGNAL 不写 external_trade_id，EXTERNAL_SYNC 判重与 create | A2-01, A2-02, §1 边界 |
| `docs/Phase1.1_A2_工程级校验证据包.md` | A2 工程级校验证据包（本文件）；含作用域锁定、幂等证据、迁移残留处理 | — |

---

## 4. Acceptance Criteria（放行标准）

- [x] A2 所有 Clause 在校验矩阵中逐条覆盖
- [x] DB 唯一约束 uq_trade_strategy_external_trade_id 正确防止重复 (strategy_id, external_trade_id) 写入；§2 提供最小复现与原始 IntegrityError 输出
- [x] 既有信号成交逻辑完全不受影响（source_type 默认 SIGNAL；SIGNAL 不写 external_trade_id 已约定并注释）
- [x] migration 可 upgrade / downgrade（已在干净库上验证）
- [x] EXTERNAL_SYNC 作用域锁定已说明（全表唯一 + SIGNAL 不写 external_trade_id）；可选“仅 EXTERNAL_SYNC”方案已记录
- [x] 迁移失败残留的处理路径（检测 + 恢复/禁止）已写入 §3，可执行

---

## 附录：EXTERNAL_SYNC 语义与使用边界（交付物说明）

- **适用场景**：对账路径（C3 PositionManager.reconcile）；将外部/交易所成交以可追溯、幂等方式落库为 trade。
- **写入时机**：在对账流程中，对“需同步的差异”生成 EXTERNAL_SYNC 类型 trade 写入 trade 表，并与 position_snapshot、position_reconcile_log 在同一事务或明确定义的一致性边界内更新。
- **使用边界**：EXTERNAL_SYNC 行必须填写 `external_trade_id`；`signal_id`/`decision_id`/`execution_id` 可为 NULL。**SIGNAL 行不得填写 external_trade_id**（必须为 NULL），由写入层/Repo/服务层保证。同一 `(strategy_id, external_trade_id)` 仅能插入一条，由 DB 约束 uq_trade_strategy_external_trade_id 与插入前判重（如 get_by_strategy_external_trade_id）保证。
