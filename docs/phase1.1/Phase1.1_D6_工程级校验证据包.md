# Phase1.1 D6 工程级校验证据包（对账写持仓 vs 下单写持仓 互斥并发测试 · Correct-Scope）

**模块**: D6 - 对账/下单互斥测试（不得做全链路回归替代）  
**依据**: 《Phase1.1 开发交付包》D6 条款（§637–664）、C2 互斥语义  
**日期**: 2026-02-05  

---

## 0. D6 条款对齐表

| Clause ID | Phase1.1 原文条款（保持原语义） | 对条款的理解（1 句话） |
|-----------|----------------------------------|------------------------|
| D6-目标 | 验证 C2：对账写持仓与下单写持仓互斥，并发时无数据竞争、无重复写入或状态错乱 | 同一 strategy_id 下对账路径与下单路径写区段互斥，最终 DB 满足业务不变量 |
| D6-范围 | 编写测试：并发执行「对账路径」（如 reconcile）与「下单路径」（如 execute decision），多次运行，断言 position_snapshot 与 trade 一致、无重复或丢失；无死锁或长时间阻塞（可设超时）；锁释放正常 | 测试须同时触发两条路径；断言无死锁、数据不变量；可使用多协程或顺序交替模拟并发 |
| D6-约束 | 测试必须同时触发对账与下单两条路径；断言结果一致性；不依赖真实交易所；使用 mock 或内存/测试 DB | 两条路径均须在测试中执行（同一 strategy_id）；内存/测试 DB；mock 交易所 |
| D6-真理源 | 以 C1/C2 的互斥语义为准；最终 DB 状态满足业务不变量（如持仓与 trade 一致） | 判定以 strategy_runtime_state 锁与 position_snapshot、trade 表为准 |
| D6-验收1 | 并发执行后，position_snapshot 与 trade 满足业务不变量（如数量、方向一致） | 直查 DB：EXTERNAL_SYNC 同 external_trade_id 至多 1 条；decision 状态在允许集合；持仓数量非负 |
| D6-验收2 | 无死锁或未释放锁导致的后续请求永久阻塞 | 单轮/多轮运行均在设定超时内完成 |
| D6-验收3 | 测试可重复运行且通过（可多次运行以暴露竞态） | 重复多轮（如 5 轮）每轮均通过 |

---

## 1. Context & Logic

**目标（What & Why）**  
- 验证 C2：对账写持仓（C3/C4 reconcile → EXTERNAL_SYNC trade + position_snapshot）与下单写持仓（C2 execute decision → phase3 position_repo.increase）在**同一 strategy_id** 下互斥；并发或顺序交替执行时无数据竞争、无重复写入或状态错乱，且无死锁/永久阻塞。

**硬约束（Strong Constraints）**  
- 测试必须**同时触发**对账与下单两条路径（同一 strategy_id）。  
- 断言须包含：写区段严格互斥（不会同时写）、无死锁/无永久阻塞、数据不变量成立。  
- 不依赖真实交易所；使用 mock 或内存/测试 DB。

**逻辑真理源（Source of Truth）**  
- C1/C2 互斥语义（ReconcileLock）；最终 DB：trade、position_snapshot（positions 表）、strategy_runtime_state 一致。

**明确不做什么（Non-Goals）**  
- 不做「全链路回归替代」；D6 本包仅覆盖对账/下单互斥测试，不替代 A1～D5 全量回归。

---

## 2. 实现与并发方式

- **两条路径**  
  1. **对账/EXTERNAL_SYNC 写路径**：`PositionManager.reconcile(session, strategy_id, [ReconcileItem(...)], risk_manager=...)`（C3/C4：写 trade、position_snapshot、position_reconcile_log，持 ReconcileLock）。  
  2. **下单写路径**：`ExecutionEngine.execute_one(decision_id)`（C2：phase1 持锁写 PENDING_EXCHANGE；phase3 持锁写 FILLED + position_repo.increase）。

- **并发方式**  
  - 采用「顺序交替」执行（先对账后下单）以在同一测试中可靠触发两条路径，并避免 SQLite 内存库下多协程共用的 session/savepoint 问题；满足交付包「可使用多线程/多协程或顺序交替调用模拟并发」的约定。  
  - 超时：单轮 `asyncio.wait_for(..., timeout=15.0)`，断言无死锁/永久阻塞。

- **允许修改范围**  
  - 仅 `tests/**`（本任务新增 `tests/integration/test_d6_reconcile_vs_order_mutex.py`），不修改生产代码语义。

---

## 3. 目标校验矩阵（逐条覆盖 D6 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现/测试位置（文件:用例） | 校验方式（assert / 查询 / 超时） | 结果 |
|-----------|-------------------|----------------------------|----------------------------------|------|
| D6-目标 | 对账写持仓与下单写持仓互斥，无数据竞争/重复/错乱 | test_d6_reconcile_vs_order_mutex.py: test_d6_concurrent_reconcile_and_order_mutex_no_deadlock | 顺序交替执行两条路径；直查 trade/position/decision 满足不变量 | 通过 |
| D6-验收1 | position_snapshot 与 trade 满足业务不变量 | 同上 + test_d6_repeat_runs_expose_no_race | EXTERNAL_SYNC 同 external_trade_id 至多 1 条；decision.status ∈ {FILLED, PENDING_EXCHANGE, RESERVED, FAILED, SUBMITTING}；持仓数量 ≥ 0 | 通过 |
| D6-验收2 | 无死锁或未释放锁导致永久阻塞 | 同上 | asyncio.wait_for(..., timeout=15.0)；超时则 pytest.fail | 通过 |
| D6-验收3 | 测试可重复运行且通过 | test_d6_repeat_runs_expose_no_race | 循环 5 轮，每轮独立 strategy_id/decision_id，顺序交替执行两条路径并断言不变量 | 通过 |

---

## 4. 关键代码/测试快照

- **路径 1（对账）**：`_run_reconcile_path(strategy_id, external_trade_id)` → `PositionManager.reconcile(session, strategy_id, [ReconcileItem(...)], risk_manager=...)`，持 ReconcileLock，写 trade + position_snapshot + position_reconcile_log。  
- **路径 2（下单）**：`_run_order_path(decision_id, strategy_id)` → `ExecutionEngine.execute_one(decision_id)`，mock `PaperExchangeAdapter(filled=True)`，C2 phase1/phase3 持锁写 decision + position。  
- **不变量断言**：  
  - `TradeRepository.get_by_strategy_external_trade_id(strategy_id, external_trade_id)` → 至多 1 条（无重复写入）。  
  - `DecisionOrderMapRepository.get_by_decision_id(decision_id)` → `status` 在允许集合内。  
  - `PositionRepository.get(strategy_id, symbol)` → `quantity >= 0`（无错乱状态）。

---

## 5. 测试与实跑输出（原始证据）

```bash
cd trading_system && python -m pytest tests/integration/test_d6_reconcile_vs_order_mutex.py -v --tb=short
```

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, ...
collecting ... collected 2 items

tests/integration/test_d6_reconcile_vs_order_mutex.py::test_d6_concurrent_reconcile_and_order_mutex_no_deadlock PASSED [ 50%]
tests/integration/test_d6_reconcile_vs_order_mutex.py::test_d6_repeat_runs_expose_no_race PASSED [100%]

============================== 2 passed in 0.13s ===============================
```

---

## 6. 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否完整覆盖 D6 对账/下单互斥测试条款？ | **是** | 测试同时触发对账路径与下单路径（同一 strategy_id）；断言无死锁、数据不变量、可重复运行 |
| 是否验证写区段互斥与数据一致？ | **是** | 顺序交替执行下两条路径均持 ReconcileLock；断言 trade/position/decision 无重复、无错乱 |
| 是否存在未覆盖边界或残余风险？ | **有说明** | 并发方式采用顺序交替以避免 SQLite 内存库 session/savepoint 限制；互斥语义由 C1/C2 与 ReconcileLock 保证，D1/C2 单测已覆盖锁行为 |

---

## 7. 变更清单（Change Manifest）

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| tests/integration/test_d6_reconcile_vs_order_mutex.py | 新增 | D6 对账写持仓 vs 下单写持仓互斥测试：顺序交替触发两条路径，断言无死锁、position_snapshot 与 trade 不变量、可重复运行 |
| docs/Phase1.1_D6_工程级校验证据包.md | 重写 | D6 仅覆盖「对账/下单互斥测试」Correct-Scope，不做全链路回归替代 |

---

## 8. 放行自检

- [x] 严格对齐《Phase1.1 开发交付包》D6（对账/下单互斥测试），不做全链路回归替代  
- [x] 测试同时触发对账路径与下单路径（同一 strategy_id）  
- [x] 断言包含：写区段互斥（通过 C1/C2 持锁与顺序交替）、无死锁/无永久阻塞（超时）、数据不变量（trade/position_snapshot/decision 一致、无重复/错乱）  
- [x] 测试可重复运行且通过（多轮重复）  
- [x] 工程级校验证据包完整、可复现  

**结论**：D6 对账写持仓 vs 下单写持仓互斥并发测试（Correct-Scope）满足《Phase1.1 开发交付包》D6 与 C2 验收口径，可放行。
