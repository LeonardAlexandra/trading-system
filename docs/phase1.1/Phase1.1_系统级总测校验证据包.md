# Phase1.1 系统级总测校验证据包

**版本**: v1.0  
**创建日期**: 2026-02-06  
**范围**: Phase1.0 + Phase1.1 联动系统级总测封版  
**目标**: 确认需求未丢失、实现与交付包一致、功能可用、关键不变式成立、无明显 bug。

---

## 0. 测试环境与前置条件

### 环境说明

| 项 | 说明 |
|----|------|
| **OS** | darwin 25.2.0（macOS） |
| **Python** | 3.13.11（miniconda3） |
| **依赖安装方式** | `pyproject.toml`，运行测试使用 `python -m pytest`（未使用 uv） |
| **测试库** | **SQLite**（`DATABASE_URL=sqlite:///<absolute_path>/phase11_system_test.db`）。Alembic 使用同步 `sqlite:///`（env.py 将 `sqlite+aiosqlite` 转为 `sqlite`）；pytest 使用 conftest 提供的 **内存 SQLite**（`sqlite+aiosqlite:///:memory:`），不共用同一文件。 |

### 必须执行并贴出输出

**alembic current（升级前）**

```text
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system
$ export DATABASE_URL="sqlite:///$(pwd)/phase11_system_test.db"
$ alembic current

INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.

```
（空库无当前 revision，无额外输出行。）

**alembic upgrade head**

```text
$ alembic upgrade head

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
```

**alembic current（升级后）**

```text
$ alembic current

INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
017 (head)
```

---

## 1. 需求覆盖矩阵（防止遗忘 Context 导致漏做）

基于 `docs/Phase1.0开发交付包.md` 与 `docs/Phase1.1开发交付包.md` 生成。  
「证据」列：本节证据对应下文章节编号（如 2/3/4/5）或“见全量回归”。

### Phase1.0 主要需求（摘要）

| 需求 | 对应代码入口（文件/函数/路由） | 对应测试用例（pytest 名称） | 证据 |
|------|------------------------------|-----------------------------|------|
| PR4 验签+解析 | `src/adapters/tradingview.py`（validate_signature/parse_webhook） | `test_valid_signature_returns_200`、`test_invalid_signature_returns_401` | §2 |
| PR5 Webhook 入口、body 验签 | `src/app/routers/signal_receiver.py` POST `/webhook/tradingview` | `test_valid_signature_returns_200`、`test_duplicate_signal_returns_duplicate_ignored_and_db_single_row` | §2 |
| PR6 去重、signal_id 稳定 | DedupSignalRepository、SignalParser | `test_duplicate_signal_returns_duplicate_ignored_and_db_single_row`、`test_signal_id_based_on_semantic_fields_not_payload_structure` | §2 |
| PR11 两段式幂等、decision_order_map | ExecutionEngine.execute、DecisionOrderMapRepository | `test_concurrent_decision_id_execution`、`test_execution_worker`、`test_resume_success_d5`（D5.1 锚点） | §4、§5 |
| PR13 Happy Path 串联 | main 链路、create_app | `test_valid_signature_returns_200`、`test_pr13_*` | §2、见全量回归 |
| 异常状态落库（TIMEOUT/FAILED） | ExecutionEngine 独立 session 更新 status | `test_persist_exception_status_commits_in_independent_session` | 见全量回归 |

### Phase1.1 开发项

| 需求 | 对应代码入口（文件/函数/路由） | 对应测试用例（pytest 名称） | 证据 |
|------|------------------------------|-----------------------------|------|
| A1 锁+TTL 字段 | `alembic/versions/013_a1_*.py`、`strategy_runtime_state` 模型 | 迁移在 §0；锁行为见 D1/C1 | §0、§4 |
| A2 EXTERNAL_SYNC、UNIQUE(strategy_id, external_trade_id) | `alembic/versions/014_*`、Trade 模型、TradeRepository | `test_c3_idempotent_integrity_error_treated_as_success`、`test_d2_idempotent_skip_duplicate_external_trade_id` | §4 |
| A3 position_reconcile_log、event_type 枚举 | `alembic/versions/015_*`、PositionReconcileLogRepository | `test_invalid_event_type_db_check_constraint_fails`、`test_c6_*`、`test_d3_*` | §3、§4、见全量回归 |
| B1 POST /strategy/{id}/resume、400+diff、2xx+STRATEGY_RESUMED | `src/app/routers/resume.py`、`resume_strategy` | `test_b1_resume_*`、`test_d4_*`、`test_d5_*`、`test_c7_*` | §3、§4 |
| B2 GET /strategy/{id}/status 只读 | `src/app/routers/resume.py` get_strategy_status | `test_b2_get_status_*`、`test_b2_get_status_read_only_no_side_effects` | §3 |
| C1 ReconcileLock acquire/renew/release/TTL | `src/locks/reconcile_lock.py` ReconcileLock | `test_d1_ttl_expiry_*`、`test_d1_explicit_release_*`、`test_acquire_*`、`test_renew_*`、`test_ttl_*` | §4 |
| C2 下单与对账互斥 | ExecutionEngine、PositionManager.reconcile 持 ReconcileLock | `test_d6_*`、`test_phase3_lock_not_acquired_does_not_drop_order` | §4、见全量回归 |
| C3 EXTERNAL_SYNC 定价优先级、reconcile 写 trade+log | PositionManager.reconcile | `test_d2_external_sync_trade_uses_*`、`test_d2_*_price_tier`、`test_c3_*` | 见全量回归 |
| C4 对账后 RiskManager 全量检查 | 对账路径末尾调用 RiskManager | `test_c4_full_check_*` | 见全量回归 |
| C5 超仓挂起 PAUSED+STRATEGY_PAUSED 同事务 | strategy_manager.pause_strategy、position_reconcile_log | `test_c5_risk_fail_pause_same_transaction`、`test_c5_signal_rejected_when_paused`、`test_d3_*` | §3、§4 |
| C6 STRATEGY_PAUSED 含 diff_snapshot、可解析 | position_reconcile_log.diff_snapshot | `test_c6_strategy_paused_has_non_empty_parseable_diff_snapshot`、`test_c6_diff_snapshot_contains_no_sensitive_keys` | §3 |
| C7 STRATEGY_RESUMED 与恢复同事务 | resume_strategy 内写 STRATEGY_RESUMED | `test_c7_resume_success_writes_strategy_resumed_same_transaction`、`test_c7_resumed_log_contains_*` | §3、§4 |
| D1 TTL 锁超时、可配置短 TTL | lock_tests.py、test_reconcile_lock.py | `test_d1_ttl_expiry_other_session_can_acquire`、`test_d1_explicit_release_*`、unit lock 全系列 | §4 |
| D2 EXTERNAL_SYNC 定价三档 | PositionManager.reconcile 定价逻辑 | `test_d2_external_sync_trade_uses_exchange_price` 等、`test_resolve_price_tier_*` | 见全量回归 |
| D3 超仓挂起事务性 | C5 实现 | `test_d3_full_chain_paused_and_log_and_signal_rejected`、`test_d3_no_partial_success_state_without_log` | §3、§4 |
| D4 Resume 400+diff 结构 | B1 强校验失败 | `test_d4_resume_fail_returns_400_and_structured_diff`、`test_d4_resume_fail_diff_structure_no_plain_text` | §3 |
| D5 Resume 成功+STRATEGY_RESUMED | B1+C7 | `test_d5_resume_success_then_running_and_strategy_resumed_and_signal_accepted` | §3、§4 |
| D5.1 锚点：accepted 后 decision_order_map 至少一条、状态为可推进集合 | test_resume_success_d5 内断言 | 同上，断言 `dom_row` 存在且 `status in D5_1_ANCHOR_ALLOWED_STATUSES` | §4 |
| D6 对账/下单互斥 | C2 | `test_d6_concurrent_reconcile_and_order_mutex_no_deadlock`、`test_d6_repeat_runs_expose_no_race` | 见全量回归 |

**未覆盖自动化测试的需求（记录为风险，本轮不强制补测）**

- Phase1.0：PR1/PR2/PR3 基础设施与迁移的“人工验收”部分（已通过 alembic 与全量用例间接覆盖）；PR12 OrderManager 查询/取消若有独立入口，可补集成用例。
- Phase1.1：无单独“仅文档”需求；所有开发项均有至少一个自动化用例或迁移证据。

---

## 2. Phase1.0 主链路可用性冒烟（真实入口）

- **覆盖**：webhook 验签通过的 happy path；webhook 重复信号/幂等（至少 1 个用例）。

**实际执行的 pytest 命令与输出摘要：**

```text
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system
$ python -m pytest tests/integration/test_tradingview_webhook.py -v -k "test_valid_signature or test_duplicate_signal"

============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO
collecting ... collected 7 items / 5 deselected / 2 selected

tests/integration/test_tradingview_webhook.py::test_valid_signature_returns_200 PASSED [ 50%]
tests/integration/test_tradingview_webhook.py::test_duplicate_signal_returns_duplicate_ignored_and_db_single_row PASSED [100%]

======================= 2 passed, 5 deselected in 0.35s =======================
```

---

## 3. Phase1.1 核心能力冒烟（挂起/恢复/状态查询）

- **覆盖**：风控失败触发 PAUSED + STRATEGY_PAUSED 日志 + diff_snapshot 可解析；B1 resume 失败 400+diff、成功 200+状态 RUNNING+STRATEGY_RESUMED；B2 status 只读无副作用。

**实际执行的 pytest 命令与输出摘要：**

```text
$ python -m pytest tests/integration/test_risk_pause_flow.py tests/integration/test_b1_resume.py tests/integration/test_b2_strategy_status.py tests/integration/test_c6_diff_snapshot.py -v

============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
collecting ... collected 12 items

tests/integration/test_risk_pause_flow.py::test_d3_full_chain_paused_and_log_and_signal_rejected PASSED [  8%]
tests/integration/test_risk_pause_flow.py::test_d3_no_partial_success_state_without_log PASSED [ 16%]
tests/integration/test_b1_resume.py::test_b1_resume_not_found PASSED     [ 25%]
tests/integration/test_b1_resume.py::test_b1_resume_check_failed_400_diff PASSED [ 33%]
tests/integration/test_b1_resume.py::test_b1_resume_paused_but_risk_fails_400 PASSED [ 41%]
tests/integration/test_b1_resume.py::test_b1_resume_success_2xx_and_strategy_resumed PASSED [ 50%]
tests/integration/test_b2_strategy_status.py::test_b2_get_status_200_when_exists_running PASSED [ 58%]
tests/integration/test_b2_strategy_status.py::test_b2_get_status_200_when_exists_paused PASSED [ 66%]
tests/integration/test_b2_strategy_status.py::test_b2_get_status_404_when_not_exists PASSED [ 75%]
tests/integration/test_b2_strategy_status.py::test_b2_get_status_read_only_no_side_effects PASSED [ 83%]
tests/integration/test_c6_diff_snapshot.py::test_c6_strategy_paused_has_non_empty_parseable_diff_snapshot PASSED [ 91%]
tests/integration/test_c6_diff_snapshot.py::test_c6_diff_snapshot_contains_no_sensitive_keys PASSED [100%]

============================== 12 passed in 0.52s ==============================
```

---

## 4. 关键不变式回归（系统级必须项）

以下均为实际执行命令与输出摘要。

### 4.1 互斥：ReconcileLock 的 acquire/ttl/release

```text
$ python -m pytest tests/integration/lock_tests.py tests/unit/locks/test_reconcile_lock.py -v

...
tests/integration/lock_tests.py::test_d1_ttl_expiry_other_session_can_acquire PASSED [  8%]
tests/integration/lock_tests.py::test_d1_explicit_release_then_other_session_can_acquire PASSED [ 16%]
tests/unit/locks/test_reconcile_lock.py::test_acquire_release_success PASSED [ 25%]
tests/unit/locks/test_reconcile_lock.py::test_acquire_fails_when_held_by_other PASSED [ 33%]
tests/unit/locks/test_reconcile_lock.py::test_release_only_by_holder PASSED [ 41%]
tests/unit/locks/test_reconcile_lock.py::test_renew_success PASSED       [ 50%]
tests/unit/locks/test_reconcile_lock.py::test_ttl_expiry_allow_steal PASSED [ 58%]
...
============================== 12 passed in 5.78s ==============================
```

### 4.2 幂等：A2 UNIQUE 冲突在并发/重复 reconcile 时视为“幂等成功”（IntegrityError 被吞为 skip）

```text
$ python -m pytest tests/integration/test_d2_external_sync_pricing.py -v -k "idempotent or c3_idempotent"

tests/integration/test_d2_external_sync_pricing.py::test_c3_idempotent_integrity_error_treated_as_success PASSED [ 50%]
tests/integration/test_d2_external_sync_pricing.py::test_d2_idempotent_skip_duplicate_external_trade_id PASSED [100%]

======================= 2 passed, 10 deselected in 0.07s =======================
```

### 4.3 事务一致性：PAUSED/RESUMED 与终态日志不允许“部分成功”

- **C5**：`test_c5_risk_fail_pause_same_transaction`、`test_d3_no_partial_success_state_without_log` 验证挂起与 STRATEGY_PAUSED 同事务。
- **C7**：`test_c7_resume_success_writes_strategy_resumed_same_transaction` 验证恢复与 STRATEGY_RESUMED 同事务。

```text
$ python -m pytest tests/integration/test_c5_pause_and_signal_rejection.py tests/integration/test_c7_strategy_resumed_log.py -v

tests/integration/test_c5_pause_and_signal_rejection.py::test_c5_risk_fail_pause_same_transaction PASSED [ 25%]
tests/integration/test_c5_pause_and_signal_rejection.py::test_c5_signal_rejected_when_paused PASSED [ 50%]
tests/integration/test_c7_strategy_resumed_log.py::test_c7_resume_success_writes_strategy_resumed_same_transaction PASSED [ 75%]
tests/integration/test_c7_strategy_resumed_log.py::test_c7_resumed_log_contains_trigger_and_previous_paused_reason PASSED [100%]

============================== 4 passed in 0.12s ==============================
```

### 4.4 D5.1 锚点：accepted 后 decision_order_map 至少一条记录，状态断言使用集合（不锁死为 RESERVED）

用例 `test_d5_resume_success_then_running_and_strategy_resumed_and_signal_accepted` 内已实现：accepted 后查询 `decision_order_map`，断言存在对应记录且 `status in D5_1_ANCHOR_ALLOWED_STATUSES`（RESERVED, SUBMITTING, PENDING_EXCHANGE, PLACED, FILLED）。

```text
$ python -m pytest tests/integration/test_resume_success_d5.py -v

tests/integration/test_resume_success_d5.py::test_d5_resume_success_then_running_and_strategy_resumed_and_signal_accepted PASSED [100%]

============================== 1 passed in 0.38s ==============================
```

---

## 5. 全量回归（Phase1.0 + Phase1.1 联动）

**必须运行并贴出输出：pytest -q**

```text
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system
$ python -m pytest -q

........................................................................ [ 34%]
........................................................................ [ 68%]
...................................................................      [100%]
211 passed in 8.37s
```
（补强 A 新增 `test_phase11_file_db_consistency.py` 共 2 条用例后，全量由 209 增至 211。）

**结论**：无失败；无需修复与二次全绿。若后续出现失败，需在本节补充：失败堆栈、根因定位、修复提交说明，并再次贴出 `pytest -q` 全绿输出。

---

## 6. 最终结论与残余风险

### 封版建议

**建议封版 Phase1.1：YES。**

- 需求与交付包一致（迁移至 017、B1/B2/C1–C7/D1–D6 均有实现与测试对应）。
- 主链路与 Phase1.1 核心能力冒烟通过，关键不变式（互斥、幂等、事务一致性、D5.1 锚点）均有回归证据。
- 全量回归 211 用例通过（含补强 A 新增 2 条），无未修复失败。

### 残余风险（记录，不阻塞封版）

| 风险 | 说明 | 建议 |
|------|------|------|
| 部分需求无独立用例 | Phase1.0 PR1/PR2/PR3 的“项目结构/迁移可重复”等依赖人工或 alembic+全量间接覆盖 | 可保留现状；若有合规要求可补简短验收清单 |
| 测试环境仅 SQLite | 全量回归与不变式均在 SQLite（内存+文件）执行，未在 PostgreSQL 上跑 | 封版后若需生产同构，建议在 CI 或预发增加 PostgreSQL 矩阵 |
| 外部/实盘测试默认跳过 | `@pytest.mark.external` 的 OKX 等测试默认不跑，需 `RUN_EXTERNAL_OKX_TESTS=true` | 已知且符合设计；实盘/外网验证需单独流程 |

---

## 7. 封版补强（A / C）

### 7.1 补强 A：文件 SQLite + 应用启动 + 集成测试一致性验证

**目标**：证明「迁移后的文件库」可被应用与集成测试共同使用，消灭迁移库/运行库割裂风险。

**约定**：
- 指定文件库：`./phase11_system_test.db`（项目根下；可由 `PHASE11_FILE_DB` 覆盖为绝对路径）。
- 干净库：执行前删除该文件并重新迁移，再以同一路径作为 `DATABASE_URL` 启动应用并跑集成测试。

**使用的 DATABASE_URL**：
- Alembic（同步）：`sqlite:///$(pwd)/phase11_system_test.db`
- 应用/测试（异步）：`sqlite+aiosqlite:///<absolute_path>/phase11_system_test.db`（由 `tests/integration/test_phase11_file_db_consistency.py` 内 fixture 根据 `PHASE11_FILE_DB` 或默认路径构造）

**运行命令与原始输出**

```text
# 1) 清理并重建文件库
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system
$ rm -f phase11_system_test.db
$ export DATABASE_URL="sqlite:///$(pwd)/phase11_system_test.db"

# 2) alembic current（升级前）
$ alembic current
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.

# 3) alembic upgrade head
$ alembic upgrade head
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001, Initial schema for PR2 (dedup_signal, decision_order_map, orders)
...（省略中间 002～016）...
INFO  [alembic.runtime.migration] Running upgrade 016 -> 017, C5: strategy_runtime_state.status, position_reconcile_log.diff_snapshot, signal_rejection 表

# 4) alembic current（升级后）
$ alembic current
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
017 (head)

# 5) 使用同一文件库跑集成测试（应用通过 create_app() 读 DATABASE_URL，fixture 注入同一文件路径）
$ python -m pytest tests/integration/test_phase11_file_db_consistency.py -v
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
collecting ... collected 2 items

tests/integration/test_phase11_file_db_consistency.py::test_webhook_writes_to_file_db PASSED [ 50%]
tests/integration/test_phase11_file_db_consistency.py::test_status_read_from_file_db PASSED [100%]

============================== 2 passed in 0.33s ===============================
```

**结论**：迁移后的文件库 `phase11_system_test.db` 可被应用正常读写；webhook 真实入口写入 dedup_signal/decision_order_map，GET /strategy/{id}/status 从同一库读取，无失败。

---

### 7.2 补强 C：并发/竞态稳定性压力回归（防 flaky）

**目标**：对关键并发/互斥链路做「重复运行 N 次」证明，避免偶发竞态在 CI/生产出现。

**选用用例**：`tests/integration/test_d6_reconcile_vs_order_mutex.py`（D6：对账写持仓 vs 下单写持仓互斥，C1/C2/D6 相关）。

**运行命令与汇总输出**

```text
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system
$ passed=0; failed=0; for i in $(seq 1 20); do out=$(python -m pytest tests/integration/test_d6_reconcile_vs_order_mutex.py -q --tb=no 2>&1); if echo "$out" | grep -q "passed"; then passed=$((passed+1)); echo "Run $i: PASS"; else failed=$((failed+1)); echo "Run $i: FAIL"; echo "$out"; fi; done; echo "=== Total: $passed passed, $failed failed ==="

Run 1: PASS
Run 2: PASS
Run 3: PASS
Run 4: PASS
Run 5: PASS
Run 6: PASS
Run 7: PASS
Run 8: PASS
Run 9: PASS
Run 10: PASS
Run 11: PASS
Run 12: PASS
Run 13: PASS
Run 14: PASS
Run 15: PASS
Run 16: PASS
Run 17: PASS
Run 18: PASS
Run 19: PASS
Run 20: PASS
=== Total: 20 passed, 0 failed ===
```

**结论**：D6 并发互斥测试连续 20 次均 PASS，无 flaky 暴露。

---

### 7.3 最终封版结论是否变化

**结论不变，仍为 YES。**  
补强 A 证明迁移库与运行库一致、补强 C 证明 D6 并发稳定；未发现新缺陷，封版建议仍为 **建议封版 Phase1.1：YES**。

---

## 附录：实际执行的关键命令清单（便于复跑）

```bash
# 0. 环境（在项目根 trading_system 下）
export DATABASE_URL="sqlite:///$(pwd)/phase11_system_test.db"

# 0. 迁移
alembic current
alembic upgrade head
alembic current

# 2. Phase1.0 冒烟
python -m pytest tests/integration/test_tradingview_webhook.py -v -k "test_valid_signature or test_duplicate_signal"

# 3. Phase1.1 冒烟
python -m pytest tests/integration/test_risk_pause_flow.py tests/integration/test_b1_resume.py tests/integration/test_b2_strategy_status.py tests/integration/test_c6_diff_snapshot.py -v

# 4. 关键不变式
python -m pytest tests/integration/lock_tests.py tests/unit/locks/test_reconcile_lock.py -v
python -m pytest tests/integration/test_d2_external_sync_pricing.py -v -k "idempotent or c3_idempotent"
python -m pytest tests/integration/test_c5_pause_and_signal_rejection.py tests/integration/test_c7_strategy_resumed_log.py -v
python -m pytest tests/integration/test_resume_success_d5.py -v

# 5. 全量回归
python -m pytest -q

# ---------- 封版补强 A：文件 SQLite + 应用 + 集成测试一致性 ----------
rm -f phase11_system_test.db
export DATABASE_URL="sqlite:///$(pwd)/phase11_system_test.db"
alembic current && alembic upgrade head && alembic current
python -m pytest tests/integration/test_phase11_file_db_consistency.py -v

# ---------- 封版补强 C：D6 并发压力 20 次 ----------
passed=0; failed=0
for i in $(seq 1 20); do
  out=$(python -m pytest tests/integration/test_d6_reconcile_vs_order_mutex.py -q --tb=no 2>&1)
  if echo "$out" | grep -q "passed"; then passed=$((passed+1)); echo "Run $i: PASS"; else failed=$((failed+1)); echo "Run $i: FAIL"; echo "$out"; fi
done
echo "=== Total: $passed passed, $failed failed ==="
```

**补强 C 脚本路径与内容**：已新增 `scripts/phase11_stress_d6_20runs.sh`，内容如下（便于复跑）：

```bash
#!/usr/bin/env bash
# 封版补强 C：D6 并发/互斥测试连续运行 20 次，验证无 flaky。
# 用法：在项目根 trading_system 下执行：bash scripts/phase11_stress_d6_20runs.sh
set -e
cd "$(dirname "$0")/.." || exit 1
passed=0
failed=0
for i in $(seq 1 20); do
  out=$(python -m pytest tests/integration/test_d6_reconcile_vs_order_mutex.py -q --tb=no 2>&1)
  if echo "$out" | grep -q "passed"; then
    passed=$((passed+1))
    echo "Run $i: PASS"
  else
    failed=$((failed+1))
    echo "Run $i: FAIL"
    echo "$out"
  fi
done
echo "=== Total: $passed passed, $failed failed ==="
exit $failed
```

---

**文档结束**
