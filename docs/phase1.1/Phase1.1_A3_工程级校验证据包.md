# Phase1.1 A3 工程级校验证据包

**模块**: A3 - position_reconcile_log 支持 external_trade_id + event_type  
**日期**: 2026-02-05

---

## 0. A3 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 你对条款的理解（1 句话，不得引入新语义） |
|----------|----------------------------------|------------------------------------------|
| A3-01 | 在 position_reconcile_log 表中新增或确认存在 external_trade_id：关联外部/交易所成交 ID（可空，非 EXTERNAL_SYNC 场景可空） | 表上有 external_trade_id 列，可空，用于关联外部成交 |
| A3-02 | 在 position_reconcile_log 表中新增或确认存在 event_type：对账事件类型，取值仅允许下述封闭枚举 | 表上有 event_type 列，且仅允许文档列出的 7 个枚举值 |
| A3-03 | event_type 取值仅允许上表枚举值，禁止自由文本或未列出的值 | DB/ORM 层约束保证仅可写入预定义 event_type |
| A3-04 | 本文档为 event_type 的唯一真理源；实现阶段不允许自行新增或改名 | 枚举常量与文档表完全一致，无新增、无改名 |
| A3-05 | 写入 position_reconcile_log 的操作必须与对账/挂起/恢复的关键步骤在同一事务或明确定义的一致性边界内 | **硬契约**：任何 position_reconcile_log 写入必须发生在**事务内**；否则 Repo 拒绝并抛 **PositionReconcileLogNotInTransactionError**（_require_transaction 强制 + 单测/复现证据） |
| A3-06 | 迁移可重复执行且可回滚 | upgrade/downgrade 可回滚，不删除既有关键列（本表为新建，无既有列） |

---

## 1. A3-05 一致性边界：工程可执行契约（B 文档契约）

### 1.1 硬契约条文

- **任何 position_reconcile_log 的写入必须发生在事务内。**
- 若当前 session 不在事务内即调用 `create()` 或 `log_event_in_txn()`，Repository **必须拒绝写入**并抛出 **PositionReconcileLogNotInTransactionError**。
- 本契约由 Repo 在写入路径上**强制校验**（_require_transaction），可测试、可复现；不依赖注释或约定。

### 1.2 “事务”的工程定义

- **事务**：指当前 `AsyncSession` 已开启且未结束的**显式事务**。
- **判定方式**：以 SQLAlchemy 的 **session.in_transaction()** 为准；为 `True` 表示 session 已 begin 且未 commit/rollback，处于“事务内”。
- **推荐用法**：调用方在**同一 session** 上先开启事务（如 `async with session.begin():` 或 `await session.begin()`），在**该代码块内**调用 `log_event_in_txn(...)` 或 `create(...)`；Repo 内部不负责 begin/commit/rollback，仅在同一事务内写 log。

### 1.3 对 C3 / C5 / C7 的验收硬条件引用

- **C3、C5、C7 的工程级验收必须复用本条**：
  - “写入 position_reconcile_log 必须在**已开启的事务内**通过 PositionReconcileLogRepository.create 或 log_event_in_txn 完成；不得在无事务或跨事务的 session 上写入。”
- 各模块证据包中须引用本 A3 证据包 **§1 硬契约** 与 **§3 防呆拒绝（A）**，并给出“在事务内调用 Repo 写入”的实现位置与校验方式。

---

## 2. 推荐主路径：Helper log_event_in_txn（C）

- **入口**：`PositionReconcileLogRepository.log_event_in_txn(strategy_id, event_type, external_trade_id=None)`。
- **要求**：调用方传入的 repo 必须由**当前正在使用的同一 session/transaction** 构造；即在同一 `async with session.begin():` 块内先执行业务再调用本方法。
- **行为**：内部仅构造一条 `PositionReconcileLog`、做 event_type 校验、`session.add(log)`，不执行 commit/rollback，不实现任何业务流程。
- **最省事即正确**：在已有事务块内调用 `await repo.log_event_in_txn("S1", RECONCILE_START)` 即满足 A3-05。

---

## 3. 防呆拒绝：事务存在性检查（A）

- 在 Repo 的**所有写入路径**（`create`、`log_event_in_txn`）入口处，先执行 **session.in_transaction()** 检查。
- 若为 `False`，**拒绝写入**并抛出 **PositionReconcileLogNotInTransactionError**，异常信息中明确要求使用 `async with session.begin():` 或等价方式。
- 该检查可测试、可复现：见 **§5.2** 与单测 `test_create_without_transaction_raises`、`test_log_event_in_txn_without_transaction_raises`。

---

## 4. 目标校验矩阵（逐条覆盖 A3 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式 | 结果 |
|----------|-------------------|------------------------|----------|------|
| A3-01 | external_trade_id 可空，关联外部成交 | 015_a3_*.py:36-41；position_reconcile_log.py:58-62 | 迁移与模型列定义 | PASS |
| A3-02 | event_type 封闭枚举 | 015:43-50 + CheckConstraint；position_reconcile_log.py 常量与 CheckConstraint | 插入非法 event_type 报错 | PASS |
| A3-03 | 仅允许预定义 event_type | 015 ck_position_reconcile_log_event_type；ORM CheckConstraint + validate_event_type | DB CHECK + Repo 校验 | PASS |
| A3-04 | 枚举以文档为唯一真理源，不新增不改名 | 015 EVENT_TYPE_VALUES；position_reconcile_log.py EVENT_TYPES / 常量 | 与 Phase1.1 表逐项对照 | PASS |
| A3-05 | 日志与业务同一一致性边界（事务内写入） | position_reconcile_log_repo.py：_require_transaction、log_event_in_txn、create | 硬契约（§1）+ 防呆（§3）+ §5.2 无事务拒绝证据 + 单测 | PASS |
| A3-06 | 迁移可回滚 | 015 upgrade/downgrade | alembic downgrade -1 / upgrade head | PASS |

---

## 5. 关键实现与证据（单一叙事）

### 5.1 关键实现快照

- **迁移**：`alembic/versions/015_a3_position_reconcile_log.py` — create_table position_reconcile_log，含 external_trade_id、event_type、CheckConstraint（name=`ck_position_reconcile_log_event_type`）封闭 7 值，索引 (strategy_id, created_at)；downgrade 删索引与表。
- **ORM**：`src/models/position_reconcile_log.py` — 常量、EVENT_TYPES、validate_event_type、CheckConstraint 与迁移一致。
- **Repo**：`src/repositories/position_reconcile_log_repo.py` — PositionReconcileLogNotInTransactionError；_require_transaction()（A）；log_event_in_txn（C）；create 入口均先 _require_transaction() 再校验 event_type 再 add。

### 5.2 两类最小复现原始输出（唯一证据）

**（1）非法 event_type 写入触发 DB CHECK 失败（IntegrityError）**

- 复现：在事务内用 raw SQL 向 position_reconcile_log 插入 `event_type='INVALID'`，由 DB 约束拒绝。
- 原始报错（来自约束 **ck_position_reconcile_log_event_type**）：

```
IntegrityError: (sqlite3.IntegrityError) CHECK constraint failed: ck_position_reconcile_log_event_type
[SQL: INSERT INTO position_reconcile_log (strategy_id, event_type) VALUES (?, ?)]
[parameters: ('S1', 'INVALID')]
(Background on this error at: https://sqlalche.me/e/20/gkpj)
```

**（2）无事务条件下调用写入触发事务检查失败**

- 复现：未调用 session.begin() 的 session 上直接调用 create(log) 或 log_event_in_txn(...)。
- 原始报错（PositionReconcileLogNotInTransactionError）：

```
PositionReconcileLogNotInTransactionError: position_reconcile_log write must run inside an active transaction. Use 'async with session.begin():' (or session.begin() before write) and call create/log_event_in_txn within that block.
```

### 5.3 A3 单测路径与 pytest 输出（唯一测试证据）

- **路径**：`tests/unit/repositories/test_position_reconcile_log_repo.py`
- **4 个用例**：无事务时 create 抛 PositionReconcileLogNotInTransactionError；无事务时 log_event_in_txn 抛同上；事务内 log_event_in_txn 成功；非法 event_type 触发 DB CHECK 抛 IntegrityError。

```
$ .venv/bin/python -m pytest tests/unit/repositories/test_position_reconcile_log_repo.py -v
============================= test session starts ==============================
...
tests/unit/repositories/test_position_reconcile_log_repo.py::test_create_without_transaction_raises PASSED
tests/unit/repositories/test_position_reconcile_log_repo.py::test_log_event_in_txn_without_transaction_raises PASSED
tests/unit/repositories/test_position_reconcile_log_repo.py::test_log_event_in_txn_inside_transaction_succeeds PASSED
tests/unit/repositories/test_position_reconcile_log_repo.py::test_invalid_event_type_db_check_constraint_fails PASSED
============================== 4 passed in 0.12s ===============================
```

- 全量 pytest：`pytest -q` → **156 passed**（含上述 4 个 A3 用例）。

---

## 6. 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否新增或修改任何 event_type？ | **否（仅实现文档 7 个）** | 未新增、未改名；与 Phase1.1 表逐项一致 |
| 是否影响既有日志或审计语义？ | **否** | 新建表 position_reconcile_log，未改其他日志表或业务表 |
| 是否影响 ExecutionEngine / RiskManager 行为？ | **否** | 未改动 execution_engine、risk_manager |
| **残余风险** | **风险已知且边界明确** | ① Repo 已强制“事务内写入”（_require_transaction）；② 调用方若无事务会被显式拒绝并抛出 PositionReconcileLogNotInTransactionError，此为**预期保护**，非残余风险。迁移可回滚；event_type 封闭由 DB CHECK + Repo 双层保证。 |

---

## 7. 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| `alembic/versions/015_a3_position_reconcile_log.py` | 新建 position_reconcile_log 表：external_trade_id、event_type、CheckConstraint、索引 | A3-01, A3-02, A3-03, A3-04, A3-06 |
| `src/models/position_reconcile_log.py` | ORM；event_type 常量与 EVENT_TYPES、validate_event_type；CheckConstraint | A3-01, A3-02, A3-03, A3-04 |
| `src/repositories/position_reconcile_log_repo.py` | _require_transaction（A）；log_event_in_txn（C）；create 内事务检查；PositionReconcileLogNotInTransactionError | A3-02, A3-03, A3-05 |
| `tests/unit/repositories/test_position_reconcile_log_repo.py` | 无事务拒绝、非法 event_type DB CHECK、事务内 log_event_in_txn 成功 | A3-05, A3-03 |
| `src/models/__init__.py` | 导出 PositionReconcileLog | A3 |
| `docs/Phase1.1_A3_工程级校验证据包.md` | A3 工程级校验证据包（本文件）；单一叙事：硬契约 + 防呆 + 两类复现证据 + 单测 | — |

---

## 8. Acceptance Criteria（放行标准）

- [x] A3 所有 Clause 在校验矩阵中逐条覆盖
- [x] event_type 枚举严格封闭（DB CheckConstraint ck_position_reconcile_log_event_type + Repo validate_event_type）；§5.2(1) 提供非法 event_type 的 IntegrityError 原始输出
- [x] A3-05 仅以硬契约口径成立：事务内写入 + Repo 强制 _require_transaction + 无事务时显式拒绝（§1、§3、§5.2(2)、§5.3 单测）
- [x] 推荐主路径 log_event_in_txn 已实现并单测通过
- [x] migration 可 upgrade / downgrade
- [x] 未影响任何既有业务或日志语义
- [x] 残余风险表述为“风险已知且边界明确”（Repo 强制 + 无事务拒绝为预期保护）

---

## 附录：日志写入与一致性边界（交付物说明）

- **一致性边界（可执行契约）**：任何 position_reconcile_log 写入**必须**在**事务内**完成；Repo 通过 `session.in_transaction()` 在写入路径上强制校验，不满足则抛出 **PositionReconcileLogNotInTransactionError**。推荐在 C3/C5/C7 中于 `async with session.begin():` 块内调用 **log_event_in_txn** 或 **create**。
- **external_trade_id**：SYNC_TRADE 等关联外部成交时必填；其余 event_type 可空。
- **event_type**：仅允许 Phase1.1 文档表中 7 个值；DB 约束 ck_position_reconcile_log_event_type 与 Repo 双层校验。
