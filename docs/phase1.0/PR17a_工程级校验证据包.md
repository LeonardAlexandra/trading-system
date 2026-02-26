# PR17a：Live 路径预演阶段 — 工程级校验证据包

## 1）变更摘要与边界

### 变更摘要
- **目标 1**：Live endpoint 路径可运行，但 **PR17a 阶段任何情况下 create_order 不得真正发送 live HTTP 请求**（post_calls_to_live_endpoint=0）。通过 `_LiveEndpointAdapter` 模拟 is_live_endpoint=True，门禁全过时仍返回 LIVE_GATE_PR17A_ORDER_DISABLED，不调用 exchange.create_order。
- **目标 2**：多重门禁在 is_live_endpoint=True 路径下全部生效、不可绕过；每项缺失均有 distinct reason_code。
- **目标 3**：Live allowlist 启动期+运行期一致性强化：live_enabled 或 allow_real_trading 时，allowlist_accounts 与 allowlist_symbols 必须非空；运行期校验 account/symbol 在 allowlist 内。
- **目标 4**：事故演练 2 场景 + 回滚入口验证：门禁缺失 → 拒绝 → 审计；断路器打开 → reset → CIRCUIT_RESET_BY_OPERATOR 审计。

### 边界（未做）
- **不接实盘**：PR17a 禁用 live create_order，无真实下单副作用。
- **不接外部 API**：默认测试使用 FakeOkxHttpClient，离线可跑。
- **不破坏**：PR15b/PR16/PR16c 门禁与精度语义、ExecutionEngine 幂等与事务边界、execution_events 语义、secret 不泄露。

---

## 2）目标校验矩阵（代码位置 + 校验方式 + PASS）

| 校验项 | 代码位置 | 校验方式 | 证据 |
|--------|----------|----------|------|
| 门禁全过仍禁止 live 下单 | live_gate.py PR17A_LIVE_ORDER_DISABLED | check_live_gates 返回 LIVE_GATE_PR17A_ORDER_DISABLED | test_pr17a_all_gates_pass_still_rejects_no_http，post_calls=0 |
| allowlist_accounts 非空 | live_gate.py | allowlist 为空 → LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED | test_live_gate_allowlist_accounts_empty_rejects |
| allowlist_symbols 非空 | execution_engine.py | symbols 为空 → LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED | test_pr17a_allowlist_symbols_empty_rejects |
| account 不在 allowlist | live_gate.py | LIVE_GATE_ACCOUNT_NOT_ALLOWED | test_pr17a_account_not_in_allowlist_rejects |
| symbol 不在 allowlist | execution_engine.py | LIVE_GATE_SYMBOL_NOT_ALLOWED | test_pr17a_symbol_not_in_allowlist_rejects |
| 启动期 allowlist 必填 | app_config.validate() | live_enabled/allow_real_trading 时 fail-fast | test_pr17a_allowlist_startup_failfast |
| 断路器回滚 + 审计 | CircuitBreakerRepository.close_circuit + append_event | CIRCUIT_RESET_BY_OPERATOR | test_pr17a_incident_b_circuit_breaker_then_reset_audit |

---

## 3）Live 门禁矩阵（逐条门禁 → 触发条件 → 拒绝事件 → reason_code → 证据）

| 门禁 | 触发条件 | 拒绝事件 | reason_code | 证据 |
|------|----------|----------|-------------|------|
| allow_real_trading | is_live_endpoint 且 allow_real_trading=false | ORDER_REJECTED | LIVE_GATE_ALLOW_REAL_TRADING_OFF | test_pr17a_allow_real_trading_off_rejects |
| live_allowlist_accounts 为空 | is_live_endpoint 且 allowlist_accounts=[] | ORDER_REJECTED | LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED | test_live_gate_allowlist_accounts_empty_rejects |
| account_id 不在 allowlist | is_live_endpoint 且 account 不在列表 | ORDER_REJECTED | LIVE_GATE_ACCOUNT_NOT_ALLOWED | test_pr17a_account_not_in_allowlist_rejects |
| live_confirm_token | token 与 env 不一致 | ORDER_REJECTED | LIVE_GATE_CONFIRM_TOKEN_MISSING | test_pr17a_confirm_token_mismatch_rejects |
| live_allowlist_symbols 为空 | is_live_endpoint 且 allowlist_symbols=[] | ORDER_REJECTED | LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED | test_pr17a_allowlist_symbols_empty_rejects |
| symbol 不在 allowlist | is_live_endpoint 且 symbol 不在列表 | ORDER_REJECTED | LIVE_GATE_SYMBOL_NOT_ALLOWED | test_pr17a_symbol_not_in_allowlist_rejects |
| PR17a 阶段禁用 live 下单 | 门禁全过 | ORDER_REJECTED | LIVE_GATE_PR17A_ORDER_DISABLED | test_pr17a_all_gates_pass_still_rejects_no_http |

---

## 4）事故演练场景与回滚说明

### 场景 A：门禁缺失 → 拒绝 → 审计正确（无 HTTP）
- **复现步骤**：配置 is_live_endpoint=True（模拟）、allow_real_trading=false；执行决策。
- **预期**：ORDER_REJECTED，reason_code=LIVE_GATE_ALLOW_REAL_TRADING_OFF；post_calls=0；events 含 ORDER_REJECTED。
- **证据**：test_pr17a_incident_a_gate_missing_no_http_audit_correct。

### 场景 B：连续 transient 5xx → 断路器打开 → 拒单 → 回滚 + 审计
- **复现步骤**：Demo 路径，FakeOkx 返回 5xx；执行 2 笔失败；第三笔被 CIRCUIT_OPEN 拒绝；调用 CircuitBreakerRepository.close_circuit + append_event(CIRCUIT_RESET_BY_OPERATOR)。
- **预期**：第三笔 reason_code=CIRCUIT_OPEN；reset 后写入 CIRCUIT_RESET_BY_OPERATOR。
- **证据**：test_pr17a_incident_b_circuit_breaker_then_reset_audit；scripts/reset_circuit_breaker.py。

---

## 5）回归不变式声明

- **幂等**：decision_id 不变。
- **事务边界**：CLAIM → 外部调用 → 落库，未改变。
- **风控**：RiskManager 语义不变。
- **审计**：execution_events 单调递增、不泄露 secret/header/signature。
- **PR17a**：create_order live HTTP = 0，post_calls_to_live_endpoint=0。

---

## 6）测试运行证据（pytest 原始输出）

**skipped / xfailed / warnings**：无；全部 passed。

### 6.1）pytest -q

```
........................................................................ [ 51%]
....................................................................     [100%]
140 passed in 2.95s
```

### 6.2）pytest -ra

```
tests/account/test_manager.py ...                                        [  2%]
...
tests/integration/test_pr17a_allowlist_startup_failfast.py ...           [ 45%]
tests/integration/test_pr17a_incident_drill_rollback.py ..               [ 46%]
tests/integration/test_pr17a_live_path_gates.py ......                   [ 50%]
...
============================= 140 passed in 3.32s ==============================
```

### 6.3）pytest -q tests/integration

```
...
tests/integration/test_pr17a_allowlist_startup_failfast.py::test_live_enabled_allowlist_accounts_empty_fail_fast PASSED [ 65%]
tests/integration/test_pr17a_allowlist_startup_failfast.py::test_live_enabled_allowlist_symbols_empty_fail_fast PASSED [ 67%]
tests/integration/test_pr17a_allowlist_startup_failfast.py::test_allow_real_trading_allowlist_accounts_empty_fail_fast PASSED [ 68%]
tests/integration/test_pr17a_incident_drill_rollback.py::test_pr17a_incident_a_gate_missing_no_http_audit_correct PASSED [ 70%]
tests/integration/test_pr17a_incident_drill_rollback.py::test_pr17a_incident_b_circuit_breaker_then_reset_audit PASSED [ 71%]
tests/integration/test_pr17a_live_path_gates.py::test_pr17a_allow_real_trading_off_rejects PASSED [ 72%]
...
tests/integration/test_pr17a_live_path_gates.py::test_pr17a_all_gates_pass_still_rejects_no_http PASSED [ 80%]
...
============================== 70 passed in 2.38s ==============================
```

---

## 7）新增/修改测试清单

| 类型 | 路径 | 说明 |
|------|------|------|
| 新增 | tests/integration/test_pr17a_live_path_gates.py | Live 路径门禁矩阵（6 条） |
| 新增 | tests/integration/test_pr17a_allowlist_startup_failfast.py | 启动期 allowlist 必填（3 条） |
| 新增 | tests/integration/test_pr17a_incident_drill_rollback.py | 事故演练 A/B + 回滚（2 条） |
| 修改 | tests/unit/execution/test_live_gate.py | 新增 allowlist_accounts 空拒绝、PR17a 全过仍拒绝；ALLOWLIST_NOT_MATCHED → ACCOUNT_NOT_ALLOWED |
| 修改 | tests/integration/test_pr14a_live_gate_and_shared_state.py | 配置补充 allowlist 以满足 PR17a 启动校验 |
| 修改 | tests/integration/test_pr16_live_gates.py | 配置补充 live_allowlist_symbols、qty_precision_by_symbol |
| 修改 | tests/integration/test_pr16_incident_rehearsal.py | 配置补充 live_allowlist_accounts、live_allowlist_symbols、qty_precision_by_symbol |

---

## 8）配置与运维影响

### 新增 reason_code
- LIVE_GATE_ACCOUNT_NOT_ALLOWED
- LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED
- LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED
- LIVE_GATE_PR17A_ORDER_DISABLED

### 配置
- live_enabled 或 allow_real_trading 时，live_allowlist_accounts 与 live_allowlist_symbols 必须非空（启动 fail-fast）。
- 其余沿用 PR16/PR16c 配置。

---

## 9）风险清单与残余风险声明

| 风险 | 缓解 | 残余 |
|------|------|------|
| 误接实盘 | PR17a 门禁全过仍 LIVE_GATE_PR17A_ORDER_DISABLED；create_order 不调用 | PR17b+ 需显式移除禁用逻辑 |
| allowlist 漏配 | 启动期 fail-fast | 运维须在启用 live 前完成配置 |
| 断路器误操作 | reset 脚本写 CIRCUIT_RESET_BY_OPERATOR 审计 | 需权限管控 |

**残余风险**：PR17a 不接实盘；上线实盘前须在后续 PR 中显式启用 live 下单路径。

---

## 10）一键复现说明

```bash
cd trading_system
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -ra
.venv/bin/python -m pytest -q tests/integration
```

- 默认离线，不访问外网。
- external tests：无；如需可后续 opt-in 并注明开启方式。

---

以上为 PR17a 工程级校验证据包。
