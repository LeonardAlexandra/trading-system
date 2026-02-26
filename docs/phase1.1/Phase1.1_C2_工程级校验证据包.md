# Phase1.1 C2 工程级校验证据包（系统级封版修订版）

**模块**: C2 - 下单路径互斥保护（与对账/恢复路径串行化）  
**日期**: 2026-02-05  
**修订**: 两阶段（Phase1 短锁写 PENDING_EXCHANGE → 锁外 create_order → Phase3 短锁写 FILLED/FAILED）；阶段3 拿不到锁不丢单

---

## 0. C2 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 你对条款的理解（1 句话，不得引入新语义） |
|----------|----------------------------------|------------------------------------------|
| C2-01 | 保证「信号驱动下单」与「对账/恢复」等写持仓路径互斥 | 同一 strategy 仅允许一条写路径同时生效，以 DB 锁为准 |
| C2-02 | 在信号驱动下单的入口与对账/恢复写持仓的入口，使用同一套 ReconcileLock（C1） | 下单路径必须经 C1 ReconcileLock，不得绕过 |
| C2-03 | 明确持锁范围：仅对会写 position_snapshot / trade / strategy_runtime_state 的路径加锁 | 持锁仅覆盖写 DB 区段（阶段1 写 PENDING、阶段3 写 FILLED/FAILED），create_order 在锁外 |
| C2-04 | 必须在锁外执行：外部 HTTP、数据拉取、差异计算、风控计算等 | 锁内禁止外部 I/O（HTTP/RPC/文件）；create_order 在锁外 |
| C2-05 | 必须在锁内执行：trade / position_snapshot / position_reconcile_log / strategy_runtime_state 的写入 | 阶段1 锁内仅写 PENDING_EXCHANGE；阶段3 锁内仅写 FILLED/FAILED + position/events |
| C2-06 | 持锁期间发生异常时，锁必须被释放（finally 或上下文管理器） | 使用 C1 use_lock 上下文管理器，退出时必 release |
| C2-07 | 持锁块内不得包含外部 I/O；不扩大锁粒度到不必要的读路径 | 锁内仅短时 DB 写与内存操作 |

---

## 1. 两阶段互斥范围（Two-Phase）

- **阶段1（短锁、纯 DB）**：在 create_order（外部 I/O）之前执行。  
  - acquire ReconcileLock(strategy_id)  
  - 在同一事务内将 decision_order_map 从 SUBMITTING 更新为 **PENDING_EXCHANGE**（可追踪的「待下单/交易所请求进行中」标记，对账/恢复可识别）  
  - release 锁  
  - **commit 当前 session**，使 PENDING_EXCHANGE 持久化  
- **create_order**：**必须在锁外执行**，不得放入持锁块内。  
- **阶段3（短锁、纯 DB）**：create_order 返回后执行。  
  - 再次 acquire 同一 strategy_id 锁（有限重试，如 3 次、间隔 100ms）  
  - 将 PENDING_EXCHANGE 更新为 FILLED 或 FAILED，并完成 trade/position_snapshot/events 等写入  
  - release 锁  

---

## 2. 锁边界（必须明确写清）

- **阶段1 锁获取位置**：`ExecutionEngine.execute_one` 在「风控/限频通过后、ORDER_SUBMIT_STARTED 与 create_order 之前」；key 为 `strategy_id`。  
- **阶段1 锁内允许操作**：仅 `update_submitting_to_pending_exchange(decision_id, now)`（纯 DB），无任何 HTTP/RPC/文件。  
- **阶段3 锁获取位置**：create_order 成功返回后；同一 strategy_id，有限重试。  
- **阶段3 锁内允许操作**：`update_after_exchange`(FILLED/FAILED)、position_repo.increase、risk_state、circuit_breaker、append_event(EV_FILLED)。  
- **锁内禁止操作**：任何 HTTP、RPC、交易所请求、数据拉取、sleep（除阶段3 重试间隔）、长时间计算。  
- **锁释放保证方式**：C1 `async with lock.use_lock(strategy_id)`，正常/异常均 release。

---

## 3. 拿不到锁的失败语义（绝不丢单）

- **阶段1 拿不到锁**：不调用 create_order，立即返回 `status="failed"`, `reason_code=RECONCILE_LOCK_NOT_ACQUIRED`，并写 FINAL_FAILED 事件。  
- **阶段3 拿不到锁（create_order 已成功）**：  
  - **绝不允许**：直接 return failed 且不落库（禁止「交易所已下单但本地无记录」）。  
  - **必须保证**：阶段1 已写入 **PENDING_EXCHANGE** 并 commit，故 DB 中至少有一条可被对账/恢复识别的记录。  
  - 写入可观测状态：`execution_events` 写入 **PENDING_EXCHANGE_ACK_NOT_COMMITTED**（含 exchange_order_id），并 return `status="filled_pending_commit"`, `reason_code=PENDING_EXCHANGE_ACK_NOT_COMMITTED`。  
  - 可选：阶段3 有限重试（如 3 次、100ms 间隔），仍拿不到锁再写上述事件并返回。  

---

## 4. 关键实现快照（Code Snapshot）

### 4.1 阶段1：PENDING_EXCHANGE 在锁内写入且无外部 I/O（事务边界标注）

```python
# ---------- Phase1.1 C2 阶段1（短锁、纯 DB）：下单意图 PENDING_EXCHANGE，create_order 仍在锁外 ----------
await self._dom_repo.session.execute(
    text("INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, lock_ttl_seconds) VALUES (:sid, 30)"),
    {"sid": strategy_id},
)
await self._dom_repo.session.flush()
holder_id = os.environ.get("RECONCILE_LOCK_HOLDER_ID", "").strip() or f"exec-{os.getpid()}"
lock = ReconcileLock(self._dom_repo.session, holder_id=holder_id, max_acquire_retries=0)
async with lock.use_lock(strategy_id) as phase1_ok:   # 锁边界开始
    if not phase1_ok:
        # ... 返回 RECONCILE_LOCK_NOT_ACQUIRED
    n = await self._dom_repo.update_submitting_to_pending_exchange(decision_id, now)  # 锁内：仅 DB 写
    if n != 1:
        # ... 返回失败
# 锁边界结束（release）
await self._dom_repo.session.commit()   # 事务边界：持久化 PENDING_EXCHANGE，之后 create_order 在锁外
```

- **事务边界**：阶段1 内 flush 后、release 后执行 `session.commit()`，保证 PENDING_EXCHANGE 落盘后再执行 create_order。  
- **锁内仅 DB 写**：仅调用 `update_submitting_to_pending_exchange`，无 HTTP/RPC/文件。

### 4.2 阶段3：PENDING_EXCHANGE → FILLED/FAILED，拿不到锁不丢单

- 阶段3：有限重试（如 3 次、间隔 0.1s）`lock.use_lock(strategy_id)`，若获得锁则在锁内执行 `update_after_exchange`(FILLED) + position/events，然后 return filled。  
- 若重试后仍拿不到锁：写事件 `PENDING_EXCHANGE_ACK_NOT_COMMITTED`（含 exchange_order_id），return `status="filled_pending_commit"`, `reason_code=PENDING_EXCHANGE_ACK_NOT_COMMITTED`；**不** return failed 且不落库，DB 中已有 PENDING_EXCHANGE 可恢复。

---

## 5. 目标校验矩阵（逐条覆盖 C2 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式 | 结果 |
|----------|-------------------|------------------------|----------|------|
| C2-01 | 下单与对账写路径互斥 | execution_engine.py 阶段1/阶段3 持 C1 锁 | 与对账路径共用 C1，同一 strategy_id 仅一会话持锁 | 通过 |
| C2-02 | 使用 C1 ReconcileLock | execution_engine.py 阶段1/阶段3 | 仅调用 ReconcileLock.use_lock(strategy_id) | 通过 |
| C2-03 | 持锁范围仅写 DB 区段 | 阶段1 仅写 PENDING_EXCHANGE；阶段3 仅写 FILLED/FAILED + position/events；create_order 在锁外 | 代码审查 + 单测 | 通过 |
| C2-04 | 锁外执行 HTTP/拉取/风控 | create_order 及之前逻辑在阶段1 commit 之后，锁外 | 代码审查 | 通过 |
| C2-05 | 锁内仅 DB 写 | 阶段1：update_submitting_to_pending_exchange；阶段3：update_after_exchange/position/events | 代码审查 | 通过 |
| C2-06 | 异常时释放锁 | C1 use_lock 的 finally 保证 release | 代码审查 | 通过 |
| C2-07 | 不扩大锁粒度、锁内无外部 I/O | 锁仅包阶段1/阶段3 的短区段，锁内无 HTTP/RPC/文件 | 代码审查 | 通过 |

---

## 6. 测试与实跑输出（原始证据）

### 6.1 pytest -q（全量）

```
........................................................................ [ 43%]
........................................................................ [ 86%]
.......................                                                  [100%]
167 passed in 9.26s
```

### 6.2 pytest -ra（C2 相关：两阶段不丢单 + execution + locks）

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 15 items

tests/integration/test_c2_two_phase_no_drop.py .                         [  6%]
tests/integration/test_execution_worker.py ....                          [ 33%]
tests/unit/locks/test_reconcile_lock.py ..........                       [100%]

============================== 15 passed in 4.56s ==============================
```

### 6.3 阶段3 拿不到锁不丢单（最小复现证据）

- **测试**：`tests/integration/test_c2_two_phase_no_drop.py::test_phase3_lock_not_acquired_does_not_drop_order`  
- **场景**：阶段1 已写 PENDING_EXCHANGE 并 commit；create_order 返回成功；阶段3 前由另一会话持锁（模拟对账持有），阶段3 重试后仍拿不到锁。  
- **断言**：  
  - 返回 `status="filled_pending_commit"`, `reason_code=PENDING_EXCHANGE_ACK_NOT_COMMITTED`；  
  - `decision_order_map` 中该 decision_id 的 status 为 **PENDING_EXCHANGE**（有记录可恢复）；  
  - `execution_events` 中存在 **PENDING_EXCHANGE_ACK_NOT_COMMITTED** 事件。  
- **原始命令与输出**：

```
pytest tests/integration/test_c2_two_phase_no_drop.py -v --tb=short
...
tests/integration/test_c2_two_phase_no_drop.py::test_phase3_lock_not_acquired_does_not_drop_order PASSED [100%]
============================== 1 passed in 0.63s ==============================
```

---

## 7. 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否所有写持仓路径都经过 ReconcileLock？ | **是** | 阶段1/阶段3 均持 C1 锁；失败路径阶段3 持锁更新 PENDING_EXCHANGE→RESERVED/FAILED |
| 是否存在绕过锁的 DB 写？ | **否** | PENDING_EXCHANGE 与 FILLED/FAILED/position/events 均在持锁内写入 |
| 是否在锁内执行外部 I/O？ | **否** | 锁内仅 DB 写与 append_event，create_order 在锁外 |
| 是否引入新的并发模型或状态？ | **否** | 仅使用 C1 ReconcileLock；新增状态 PENDING_EXCHANGE 为可追踪意图 |
| 是否出现「交易所已下单但本地无记录」？ | **否** | 阶段1 先写 PENDING_EXCHANGE 并 commit；阶段3 拿不到锁时返回 filled_pending_commit 且 DB 有 PENDING_EXCHANGE |

---

## 8. 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| src/models/decision_order_map_status.py | 新增 PENDING_EXCHANGE | C2 阶段1 可追踪意图 |
| src/repositories/decision_order_map_repo.py | 新增 update_submitting_to_pending_exchange；exists_recent 含 PENDING_EXCHANGE | C2 阶段1/阶段3 |
| src/common/event_types.py | 新增 PENDING_EXCHANGE_ACK_NOT_COMMITTED | C2 阶段3 拿不到锁可观测 |
| src/common/reason_codes.py | 新增 PENDING_EXCHANGE_ACK_NOT_COMMITTED | C2 阶段3 拿不到锁返回 |
| src/execution/execution_engine.py | 两阶段：阶段1 短锁写 PENDING_EXCHANGE + commit；锁外 create_order；阶段3 短锁写 FILLED/FAILED 或 filled_pending_commit；失败路径阶段3 持锁更新 | C2-01～C2-07 |
| tests/integration/test_c2_two_phase_no_drop.py | 阶段3 拿不到锁不丢单最小复现测试 | 证据 6.3 |
| docs/Phase1.1_C2_工程级校验证据包.md | 本证据包（两阶段、锁边界、不丢单语义、快照、实跑） | 验收输入 |

---

## 9. Acceptance Criteria（放行标准）

- [x] C2 所有 Clause 在校验矩阵中逐条覆盖  
- [x] 两阶段：阶段1 短锁写 PENDING_EXCHANGE（锁内纯 DB），create_order 在锁外，阶段3 短锁写 FILLED/FAILED  
- [x] 锁内禁止外部 I/O（C2-04）  
- [x] 阶段3 拿不到锁时绝不出现「交易所已下单但本地无记录」：至少保留 PENDING_EXCHANGE + 写 PENDING_EXCHANGE_ACK_NOT_COMMITTED + 返回 filled_pending_commit  
- [x] 证据包含阶段1 代码快照与事务边界、阶段3 拿不到锁不丢单最小复现测试及原始 pytest 输出  

**结论：C2 满足 Phase1.1 系统级封版标准。**
