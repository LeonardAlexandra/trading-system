# PR14a 工程级校验证据包

本文档用于 PR14a 的工程级放行判断：实盘门禁（live_enabled）与限频/断路器状态外置已实现，多实例共享生效，全行为可审计。所有结论均有证据来源。

---

## 1）变更摘要与边界

**做了什么**

- **目标 1 - 实盘门禁（Live Trading Gate）**：ExecutionConfig 增加 `live_enabled: bool = False`；当 `live_enabled=true` 时，所有 enabled 策略必须显式配置 `strategy.account_id` 与 `strategy.exchange_profile_id`，且 account 须存在于 accounts、exchange_profile 须存在于 exchange_profiles，且 account.exchange_profile_id 与 strategy.exchange_profile_id 一致；缺任一项启动期 ConfigValidationError（reason_code：LIVE_GATE_MISSING_ACCOUNT_ID、LIVE_GATE_MISSING_EXCHANGE_PROFILE_ID、LIVE_GATE_ACCOUNT_NOT_FOUND、LIVE_GATE_EXCHANGE_PROFILE_NOT_FOUND、LIVE_GATE_ACCOUNT_EXCHANGE_MISMATCH）；`live_enabled=false` 时行为与 PR13 一致，允许默认回退（paper/default）。execution_events 增加 `live_enabled` 列，可区分 live vs dry_run 追溯。
- **目标 2 - 限频/断路器状态外置（多实例共享）**：新增表 `rate_limit_state`（account_id PK、window_start_utc、count、updated_at）、`circuit_breaker_state`（account_id PK、failures_count、opened_at_utc、updated_at）；新增 RateLimitRepository（allow_and_increment）、CircuitBreakerRepository（get_state、is_open、record_failure、record_success、close_circuit）；ExecutionEngine 可选注入 rate_limit_repo、circuit_breaker_repo，注入时按 account_id 读写共享状态，未注入时保持 PR13 进程内/事件计数行为。熔断打开/关闭、限频拒绝仍写 execution_events，含 account_id。
- **目标 3 - 兼容性与演进**：不破坏 PR11/PR12/PR13 既有测试与不变式；新配置项有默认值、启动期 fail-fast、reason_code 明确；migration 提供 upgrade/downgrade，downgrade 涉及 data loss 时门禁 ALLOW_DATA_LOSS=true。

**没做什么**

- 未接真实交易所、未引入真实 API Key、未把 live_enabled 变成“真的去下单”。
- 未改变 ExecutionEngine 幂等与事务边界、未改变 RiskManager 规则。
- 未引入 Redis/消息队列/Celery/额外外部依赖；本 PR 优先 DB。

---

## 2）目标校验矩阵（代码位置 + 校验方式 + PASS/FAIL）

| 目标/风险点 | 代码位置 | 校验方式 | 预期结果 | 实际结果 | 证据引用 |
|-------------|----------|----------|----------|----------|----------|
| live_enabled=true 缺 account_id → 启动 fail-fast | app_config.py validate()、reason_codes LIVE_GATE_* | test_pr14a_live_enabled_missing_account_id_fail_fast | ConfigValidationError(reason_code=LIVE_GATE_MISSING_ACCOUNT_ID) | PASS | test_pr14a_live_gate_and_shared_state.py |
| live_enabled=true 缺 exchange_profile_id → 启动 fail-fast | app_config.py validate() | test_pr14a_live_enabled_missing_exchange_profile_id_fail_fast | reason_code=LIVE_GATE_MISSING_EXCHANGE_PROFILE_ID | PASS | 同上 |
| live_enabled=false 时缺配置不阻塞 | app_config.py | test_pr14a_live_enabled_false_same_config_does_not_block | load_app_config 成功 | PASS | 同上 |
| 外置限频：两 engine 共享 DB，超限后第二实例被拒 | RateLimitRepository、ExecutionEngine rate_limit_repo | test_pr14a_shared_rate_limit_two_engines | 前 2 单成功，第 3 单（另一 session）failed、reason_code=RATE_LIMIT_EXCEEDED；events 含 RATE_LIMIT_EXCEEDED + account_id | PASS | 同上 |
| 外置断路器：两 engine 共享 DB，熔断后第二实例被拒 | CircuitBreakerRepository、ExecutionEngine circuit_breaker_repo | test_pr14a_shared_circuit_breaker_two_engines | 连续失败 → CIRCUIT_OPENED；第二实例 failed reason_code=CIRCUIT_OPEN；close_circuit 后可再下单；审计 CIRCUIT_OPENED/CLOSED | PASS | 同上 |
| execution_events 可区分 live_enabled | execution_events.live_enabled、append_event(..., live_enabled=) | ExecutionEvent 模型、ExecutionEventRepository.append_event | 事件含 live_enabled 列 | PASS | execution_event.py、009 migration |
| 回归：PR11/PR12/PR13 测试与不变式 | 全量 pytest | pytest -q、pytest -ra、pytest -q tests/integration | 63 通过（含 42 集成） | PASS | 见下文测试证据 |

---

## 3）回归不变式声明

- **幂等语义**：未改变。decision_id 仍为唯一幂等主键。
- **ExecutionEngine 事务边界**：未改变。CLAIM → resolve → 风控/限频/熔断检查 → 外部调用 → 状态落库；限频/熔断读写在 repository 层，事务由调用方 session 管理。
- **风控规则**：未改变。RiskManager 语义未动。
- **审计语义**：增强。execution_events 增加 live_enabled；熔断打开/关闭、限频拒绝仍写 events，含 account_id。
- **secret 隔离**：未改变。事件/配置无 secret。

---

## 4）测试运行证据（pytest 原始输出）

### 命令 1：pytest -q

```bash
cd trading_system && .venv/bin/python -m pytest -q
```

**终端原始输出：**

```
...............................................................          [100%]
63 passed in 2.92s
```

---

### 命令 2：pytest -ra

```bash
cd trading_system && .venv/bin/python -m pytest -ra
```

**终端原始输出：**

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 63 items

tests/execution/test_order_manager.py .......                            [ 11%]
tests/integration/test_app_startup_config_injection.py ..                [ 14%]
tests/integration/test_config_snapshot_event.py ...                      [ 19%]
tests/integration/test_execution_events.py ....                          [ 25%]
tests/integration/test_execution_worker.py ....                          [ 31%]
tests/integration/test_order_manager_audit.py ..                         [ 34%]
tests/integration/test_pr11_strategy_isolation.py .....                  [ 42%]
tests/integration/test_pr13_safety_valves.py ....                        [ 49%]
tests/integration/test_pr14a_live_gate_and_shared_state.py .....         [ 57%]
tests/integration/test_risk_manager.py .....                             [ 65%]
tests/integration/test_tradingview_webhook.py .......                    [ 76%]
tests/integration/test_tradingview_webhook_config_validation.py .        [ 77%]
tests/unit/application/test_signal_service.py ...                        [ 82%]
tests/unit/repositories/test_decision_order_map_repo.py ....             [ 88%]
tests/unit/repositories/test_dedup_signal_repo.py ....                   [ 95%]
tests/unit/repositories/test_orders_repo.py ...                           [100%]

============================== 63 passed in 2.10s ==============================
```

---

### 命令 3：pytest -q tests/integration

```bash
cd trading_system && .venv/bin/python -m pytest -q tests/integration
```

**终端原始输出：**

```
..........................................                               [100%]
42 passed in 2.80s
```

---

## 5）新增/修改测试清单（断言点明确）

| 文件路径 | 测试函数名 | 关键断言点 | 覆盖目标 |
|----------|------------|------------|----------|
| tests/integration/test_pr14a_live_gate_and_shared_state.py | test_pr14a_live_enabled_missing_account_id_fail_fast | load_app_config 抛 ConfigValidationError，reason_code=LIVE_GATE_MISSING_ACCOUNT_ID；message 含 account_id | Live Gate：缺 account_id 启动 fail-fast |
| tests/integration/test_pr14a_live_gate_and_shared_state.py | test_pr14a_live_enabled_missing_exchange_profile_id_fail_fast | reason_code=LIVE_GATE_MISSING_EXCHANGE_PROFILE_ID；message 含 exchange_profile_id | Live Gate：缺 exchange_profile_id 启动 fail-fast |
| tests/integration/test_pr14a_live_gate_and_shared_state.py | test_pr14a_live_enabled_false_same_config_does_not_block | live_enabled=false、策略无 account_id/exchange_profile_id 时 load_app_config 成功 | 兼容：live_enabled=false 不阻塞 |
| tests/integration/test_pr14a_live_gate_and_shared_state.py | test_pr14a_shared_rate_limit_two_engines | 两 engine（两 session）共享同一 DB；前 2 单 filled，第 3 单（engine2）failed、reason_code=RATE_LIMIT_EXCEEDED；events 含 RATE_LIMIT_EXCEEDED 且 account_id=acc1 | 外置限频多实例共享 |
| tests/integration/test_pr14a_live_gate_and_shared_state.py | test_pr14a_shared_circuit_breaker_two_engines | 连续 2 次失败 → CIRCUIT_OPENED；第三单（另一 engine）failed reason_code=CIRCUIT_OPEN；close_circuit 后新单 filled | 外置断路器多实例共享 + CIRCUIT_OPENED/CLOSED 审计 |

---

## 6）DB/Migration 校验

- **迁移文件**：`alembic/versions/009_pr14a_rate_limit_circuit_breaker_state.py`
- **upgrade**：创建表 `rate_limit_state`（account_id PK, window_start_utc, count, updated_at）、`circuit_breaker_state`（account_id PK, failures_count, opened_at_utc, updated_at）；为 `execution_events` 增加列 `live_enabled`（Boolean, nullable, server_default=false）。
- **downgrade**：删除 `execution_events.live_enabled`；删除表 `circuit_breaker_state`、`rate_limit_state`。涉及数据丢失，门禁：**必须设置环境变量 `ALLOW_DATA_LOSS=true` 方可执行 downgrade**，否则抛出 RuntimeError。
- **data loss**：downgrade 会丢失 rate_limit_state、circuit_breaker_state 表内数据及 execution_events.live_enabled 列；门禁已明确。

---

## 7）配置与运维影响

- **新增配置项**（均有默认值、启动期校验）：
  - execution.live_enabled：bool，默认 False。为 true 时，所有 enabled 策略必须显式配置 account_id、exchange_profile_id，且与 exchange_profiles/accounts 一致，否则 ConfigValidationError（LIVE_GATE_* reason_code）。
- **fail-fast**：validate() 在 live_enabled=true 时校验上述项；缺项或不一致 → ConfigValidationError，reason_code 见第 1 节。
- **Worker**：execution_worker 创建 ExecutionEngine 时已注入 RateLimitRepository、CircuitBreakerRepository（同一 session），多实例共享同一 DB 时限频/熔断状态一致。

---

## 8）风险清单与残余风险声明

- **已缓解**：PR13 限频/断路器为进程内状态、多实例失效 → PR14a 外置至 DB，按 account_id 共享。
- **已缓解**：配置默认回退（paper/default）在实盘阶段误用风险 → live_enabled 门禁使“缺显式配置不可能启动实盘准备模式”。
- **残余风险**：live_enabled 仅为门禁与校验，不代表启用真实交易所；真实下单仍由后续 PR14b/PR15 接入。

---

## 9）一键复现说明

- **环境准备**：`cd trading_system`，Python 3.10+，`pip install -e ".[dev]"`（或项目 .venv）。
- **运行测试**：`.venv/bin/python -m pytest -q`；`.venv/bin/python -m pytest -ra`；`.venv/bin/python -m pytest -q tests/integration`。
- **DB 迁移**：`alembic upgrade head`（009 增加 rate_limit_state、circuit_breaker_state 表及 execution_events.live_enabled）。downgrade 需 `ALLOW_DATA_LOSS=true`。
- **环境变量**：无需 secret；测试使用临时 SQLite。

---

**PR14a 完成标准**：live_enabled 门禁使“配置疏忽不可能导致实盘事故”；限频/断路器状态外置、多实例共享生效；所有行为可审计、可回放；不破坏既有不变式与测试；工程级证据包完整可复现。
