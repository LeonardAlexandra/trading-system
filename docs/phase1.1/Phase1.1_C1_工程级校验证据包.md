# Phase1.1 C1 工程级校验证据包（封版标准修订版）

**模块**: C1 - ReconcileLock（DB 原子租约锁 + TTL）  
**日期**: 2026-02-05  
**修订**: TTL 真理源改为 lock_ttl_seconds 列；锁行不存在责任边界明确为 B（调用方前置条件）

---

## 0. C1 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 你对条款的理解（1 句话，不得引入新语义） |
|----------|----------------------------------|------------------------------------------|
| C1-01 | 只允许一种实现范式——基于数据库的租约锁（lease lock），使用单条原子 UPDATE | 锁状态完全由 DB 字段决定，仅用单条 UPDATE 抢占/续期/释放 |
| C1-02 | acquire：单条 UPDATE ... SET lock_holder_id=?, locked_at=NOW() WHERE strategy_id=? AND (lock_holder_id IS NULL OR locked_at + TTL < NOW())，affected rows=1 则成功 | 禁止 SELECT FOR UPDATE；仅允许该单条原子 UPDATE |
| C1-03 | renew：单条 UPDATE ... SET locked_at=NOW() WHERE strategy_id=? AND lock_holder_id=? AND locked_at + TTL > NOW()，affected rows=1 则续期成功 | 仅锁持有者且未过期可续期 |
| C1-04 | release：单条 UPDATE ... SET lock_holder_id=NULL, locked_at=NULL WHERE strategy_id=? AND lock_holder_id=?，affected rows=1 则释放成功 | 仅锁持有者可释放 |
| C1-05 | TTL 默认 30 秒，超时未续期则锁失效 | locked_at + TTL 判定过期；TTL 真理源为行上 lock_ttl_seconds 列（C1-10） |
| C1-06 | 锁超过 TTL 未续期后，其他会话可成功获取锁 | 过期可被抢占，不需显式释放 |
| C1-07 | 抢占失败时仅允许：（1）立即失败返回，或（2）有限重试（如最多 3 次、间隔 100ms）；禁止无限等待或自旋 | 仅允许立即失败或有限重试，禁止 while true / 自旋 / 无限 sleep |
| C1-08 | 禁止在持锁期间发起外部 HTTP、外部 IO 或长时间计算；持锁内仅允许短时 DB 写与内存操作 | 锁内禁止外部 I/O；由调用方遵守，C1 不持长事务 |
| C1-09 | 通过 DB 原子锁 + TTL 保证崩溃后可恢复且无无限占锁 | 崩溃恢复仅依赖 DB 状态与 TTL |
| C1-10 | 以数据库 strategy_runtime_state 中锁相关字段为准 | 使用 A1 schema；lock_holder_id、locked_at、**lock_ttl_seconds 列为 TTL 真理源**，过期/续期判定必须使用该列 |

---

## 2. 锁行不存在的责任边界（工程前置条件，选项 B）

- **选择**：**B）明确写为工程前置条件**：调用方在 acquire 前必须确保存在 strategy_runtime_state 行；在证据包 Acceptance Criteria 与风险声明中写死该边界。
- **落实**：
  - 不在 C1 内实现 ensure_row；调用方（或 A1/业务初始化）负责行的创建与存在性。
  - 无行时 UPDATE 影响 0 行，acquire 返回 False。
- **无行时返回 False 的语义区分**：
  - acquire 返回 False 时，**在 API 层面不区分**「锁被他人占用」与「行不存在」；二者均为 affected_rows==0。
  - **调用约定区分**：调用方在调用 acquire 前必须已保证该 strategy_id 对应行存在（例如通过策略初始化、A1 迁移或业务逻辑先插入/确保行）。若需区分，调用方可先调用 `StrategyRuntimeStateRepository.get_by_strategy_id(strategy_id)`，若为 None 则视为行不存在，不应再尝试 acquire；若存在再 acquire，此时 False 仅表示锁被占用或抢占失败。
  - **日志**：C1 仅打 debug 日志 "ReconcileLock acquire failed strategy_id=... holder=..."，不区分原因；排查时结合「是否已确保行存在」判断。
- **风险声明**：若未遵守前置条件（无行即调用 acquire），会得到 False，易被误判为「锁被占用」；因此**必须在文档与验收中写死「调用方须先确保行存在」**，避免误判。

---

## 3.1 目标校验矩阵（逐条覆盖 C1 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式 | 结果 |
|----------|-------------------|------------------------|----------|------|
| C1-01 | 仅允许 DB 租约锁、单条原子 UPDATE | src/locks/reconcile_lock.py 全模块 | 代码审查：acquire/renew/release 均为单条 UPDATE，无 SELECT FOR UPDATE | 通过 |
| C1-02 | acquire 单条 UPDATE，条件无锁或过期，affected_rows=1 成功 | reconcile_lock.py:78-108 | 单测 test_acquire_release_success、test_acquire_fails_when_held_by_other | 通过 |
| C1-03 | renew 单条 UPDATE，持有者且未过期可续期 | reconcile_lock.py:110-132 | 单测 test_renew_success | 通过 |
| C1-04 | release 单条 UPDATE，仅持有者可释放 | reconcile_lock.py:134-154 | 单测 test_release_only_by_holder | 通过 |
| C1-05 | TTL 默认 30 秒，locked_at + TTL 判定过期；TTL 取自行上列 | reconcile_lock.py:86-87（WHERE 使用 lock_ttl_seconds） | 表默认 server_default=30；过期判定用列 lock_ttl_seconds | 通过 |
| C1-06 | 锁过期可被抢占 | reconcile_lock.py:84-88（WHERE 含过期条件，列参与） | 单测 test_ttl_expiry_allow_steal | 通过 |
| C1-07 | 仅允许立即失败或有限重试，禁止无限等待 | reconcile_lock.py:97-106 | max_acquire_retries 循环有上界，test_acquire_immediate_fail_no_retry | 通过 |
| C1-08 | 锁内禁止外部 I/O；C1 不持长事务 | 文档与调用约定 | 实现不包含 HTTP/RPC/文件；use_lock 仅 acquire/release，事务由调用方管理 | 通过 |
| C1-09 | 崩溃后可恢复，仅依赖 DB 状态 | strategy_runtime_state 表为唯一真理源 | 无内存锁、无外部协调器；锁状态仅由 DB 字段决定 | 通过 |
| C1-10 | strategy_runtime_state 为真理源；**TTL 为 lock_ttl_seconds 列** | reconcile_lock.py:86-87, 120-122 | acquire/renew 的 WHERE 使用 `lock_ttl_seconds` 列做 datetime 加秒；test_ttl_expiry_allow_steal、test_ttl_from_column_30s_not_expired | 通过 |

---

## 3.2 关键实现快照（Code Snapshot）

### TTL 真理源（C1-10）：过期/续期判定使用 lock_ttl_seconds 列

- **acquire 过期条件**（SQL 中必须使用列，不得用绑定参数绕过）：
  - SQLite：`datetime(locked_at, '+' || cast(lock_ttl_seconds as text) || ' seconds') < datetime('now')`
  - 即 TTL 来自行上 `lock_ttl_seconds` 列，不来自 ReconcileLock 构造参数或环境变量。
- **renew 未过期条件**：
  - SQLite：`datetime(locked_at, '+' || cast(lock_ttl_seconds as text) || ' seconds') > datetime('now')`
- 环境变量 `RECONCILE_LOCK_TTL_SECONDS` 与构造参数 `ttl_seconds` 仅作**默认值/回填**（如插入新行时写入 lock_ttl_seconds），**不参与** acquire/renew 的 WHERE 条件。

### ReconcileLock 核心 SQL（acquire / renew / release）

- **acquire**（C1-02）：
```sql
UPDATE strategy_runtime_state
SET lock_holder_id = :holder_id,
    locked_at = datetime('now')
WHERE strategy_id = :strategy_id
  AND (
        lock_holder_id IS NULL
        OR datetime(locked_at, '+' || cast(lock_ttl_seconds as text) || ' seconds') < datetime('now')
      )
```
  rowcount==1 成功；支持有限重试（C1-07）。

- **renew**（C1-03）：
```sql
UPDATE strategy_runtime_state
SET locked_at = datetime('now')
WHERE strategy_id = :strategy_id
  AND lock_holder_id = :holder_id
  AND datetime(locked_at, '+' || cast(lock_ttl_seconds as text) || ' seconds') > datetime('now')
```
  rowcount==1 成功。

- **release**（C1-04）：单条 `UPDATE ... SET lock_holder_id=NULL, locked_at=NULL WHERE strategy_id=:strategy_id AND lock_holder_id=:holder_id`，rowcount==1 成功。

### 重试逻辑（C1-07）

- `max_acquire_retries` 默认 0（立即失败）；可设为正整数，重试间隔 `retry_interval_seconds`（默认 0.1）。
- 循环 `for attempt in range(self._max_acquire_retries + 1)`，无 `while True`、无无限 sleep。

### 上下文管理器

- `async with lock.use_lock(strategy_id)`：acquire 成功 yield True，finally 中 release；acquire 失败 yield False，不 release。

---

## 3.3 测试与实跑输出（原始证据）

### pytest -q（C1 单测）

```
..........                                                               [100%]
10 passed in 3.74s
```

### pytest -ra（C1 单测）

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 10 items

tests/unit/locks/test_reconcile_lock.py ..........                       [100%]

============================= 10 passed in 4.12s ==============================
```

### 覆盖场景摘要（含 TTL 取自列值）

- test_acquire_release_success：加锁、释放、再次加锁
- test_acquire_fails_when_held_by_other：他人持锁时 acquire 失败
- test_release_only_by_holder：仅持有者可 release
- test_renew_success：持锁未过期时 renew 成功
- **test_ttl_expiry_allow_steal**：行上 lock_ttl_seconds=1，不传 ttl 给 ReconcileLock，过期后其他会话可获取锁（**证明 TTL 真理源为列**）
- **test_ttl_from_column_30s_not_expired**：行上 lock_ttl_seconds=30，1.5 秒内其他会话无法抢占（**证明按列值生效**）
- test_is_held_by_me：持有时 True，释放后 False
- test_use_lock_context_manager：上下文管理器持锁与释放
- test_acquire_immediate_fail_no_retry：max_retries=0 立即失败
- test_acquire_no_row_returns_false：无行时 acquire 返回 False（与「锁被占用」在返回值上不可区分，见 §2）

---

## 3.4 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否引入任何非 DB 锁？ | **否** | 仅使用 strategy_runtime_state 表的原子 UPDATE，无 Redis/内存锁 |
| 是否使用 SELECT FOR UPDATE？ | **否** | 全文无 SELECT FOR UPDATE，仅 is_held_by_me 使用只读 SELECT |
| 是否存在无限等待或自旋？ | **否** | 重试次数为 max_acquire_retries+1 的有限循环，无 while True |
| 是否在锁内执行外部 I/O？ | **否** | C1 模块内无 HTTP/RPC/文件；持锁边界由调用方遵守 |
| 是否影响既有业务逻辑？ | **否** | 仅修订 locks 与单测，未修改 execution/repositories 业务路径 |
| TTL 过期计算是否使用 DB 列？ | **是** | acquire/renew 的 WHERE 使用 lock_ttl_seconds 列，未用环境变量绕过 |

---

## 3.5 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| src/locks/reconcile_lock.py | TTL 真理源改为行上 lock_ttl_seconds 列（acquire/renew WHERE）；锁行不存在责任边界文档 | C1-10、责任边界 B |
| tests/unit/locks/test_reconcile_lock.py | test_ttl_expiry_allow_steal 改为行 lock_ttl_seconds=1；新增 test_ttl_from_column_30s_not_expired | C1-10、TTL 列值验证 |
| docs/Phase1.1_C1_工程级校验证据包.md | 本证据包：§2 责任边界 B、§3.2 SQL 使用列、§3.3 实跑、§4 放行与风险声明 | 封版标准 |

---

## 4. Acceptance Criteria（放行标准）与风险声明

- [x] C1 所有 Clause 在校验矩阵中逐条覆盖
- [x] acquire / renew / release 严格符合 Phase1.1 范式（单条原子 UPDATE，无 SELECT FOR UPDATE）
- [x] 无 SELECT FOR UPDATE、无无限等待
- [x] **TTL 真理源为 strategy_runtime_state.lock_ttl_seconds 列**；acquire/renew 的 WHERE 已使用该列进行 datetime 加秒计算；单测证明 1 秒列值过期可抢占、30 秒列值 1.5s 内不可抢占
- [x] **锁行不存在责任边界**：采用选项 B；调用方在 acquire 前必须确保存在 strategy_runtime_state 行；无行时返回 False 的语义与「锁被占用」不可区分，通过调用约定（先确保行存在或先 get_by_strategy_id）区分
- [x] 工程级校验证据包完整、可复现（pytest tests/unit/locks/ -q / -ra 可复现）

**风险声明（写死）**：若调用方在未确保 strategy_runtime_state 行存在的情况下调用 acquire，将得到 False，可能被误判为「锁被占用」。因此**调用方必须在 acquire 前保证行存在**（A1/业务初始化或显式插入），否则「无行=拿不到锁」会造成误判。

**结论：C1 满足 Phase1.1 工程级封版标准。**
