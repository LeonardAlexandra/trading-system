# PR17b：极小额 Live 下单阶段 — 工程级校验证据包（补强版）

## 补强修订摘要

1. **confirm_token reason_code 语义精确化**
   - 缺失 token（配置或 env 任一侧空）：`LIVE_GATE_CONFIRM_TOKEN_MISSING`
   - 不匹配 token（两端均有值但不一致）：`LIVE_GATE_CONFIRM_TOKEN_MISMATCH`

2. **事故演练 B 口径与覆盖**
   - 新增 integration test：`test_pr17b_incident_b_live_path_5xx_circuit_reset`，在 okx_live profile + is_live_endpoint=True 路径下，fake transport 返回 5xx，触发 retry/circuit breaker，验证 reset 写 CIRCUIT_RESET_BY_OPERATOR。
   - 原有 `test_pr17a_incident_b_circuit_breaker_then_reset_audit` 使用 Demo 路径（is_live_endpoint=False），两者互补：**事故演练 B 逻辑为 endpoint-agnostic**，Demo 与 live path 均可触发断路器与 reset 审计。

---

## 1）变更摘要与边界

### 变更摘要
- **目标 1**：移除 PR17a 的 LIVE_GATE_PR17A_ORDER_DISABLED 禁用逻辑；门禁全过且 live_enabled 时**允许 live create_order**（PR17b 首次允许真实 live 下单）。
- **目标 2**：PR17b 极小额风险限制：live_max_order_notional、live_max_order_qty、live_max_orders_per_hour、live_max_orders_per_day；超限拒绝 + 审计。
- **目标 3**：RealOkxHttpClient 支持 env=live；okx.env 允许 "demo" 或 "live"；OkxExchangeAdapter 支持 live_endpoint 参数。
- **目标 4**：事件体系统一保持（OKX_HTTP_* / ORDER_*）；重试仅 Transient；无 secret 泄露。
- **目标 5**：事故演练：门禁全过但 live 风险超限 → 拒绝；transient 5xx → 断路器 → reset → CIRCUIT_RESET_BY_OPERATOR。

### 边界（未做）
- **极小额**：PR17b 仅允许白名单账户+交易对+极小额度+一次性 token；默认测试离线。
- **不破坏**：PR17a 门禁矩阵、PR16c 精度、PR15b 闭环、ExecutionEngine 幂等与事务边界。

---

## 2）门禁矩阵（逐条门禁 → 拒绝事件 → reason_code → 证据）

| 门禁 | 拒绝事件 | reason_code | 证据 |
|------|----------|-------------|------|
| live_enabled=false | ORDER_REJECTED | LIVE_GATE_LIVE_ENABLED_REQUIRED | test_live_gate_live_enabled_false_rejects |
| allow_real_trading=false | ORDER_REJECTED | LIVE_GATE_ALLOW_REAL_TRADING_OFF | test_pr17a_allow_real_trading_off_rejects |
| live_allowlist_accounts 为空 | ORDER_REJECTED | LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED | test_live_gate_allowlist_accounts_empty_rejects |
| account_id 不在 allowlist | ORDER_REJECTED | LIVE_GATE_ACCOUNT_NOT_ALLOWED | test_pr17a_account_not_in_allowlist_rejects |
| live_confirm_token 或 LIVE_CONFIRM_TOKEN 缺失 | ORDER_REJECTED | LIVE_GATE_CONFIRM_TOKEN_MISSING | test_live_gate_confirm_token_missing_rejects |
| 两端均有 token 但不一致 | ORDER_REJECTED | LIVE_GATE_CONFIRM_TOKEN_MISMATCH | test_pr17a_confirm_token_mismatch_rejects |
| live_allowlist_symbols 为空 | ORDER_REJECTED | LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED | test_pr17a_allowlist_symbols_empty_rejects |
| symbol 不在 allowlist | ORDER_REJECTED | LIVE_GATE_SYMBOL_NOT_ALLOWED | test_pr17a_symbol_not_in_allowlist_rejects |
| 门禁全过 | 允许 create_order | — | test_pr17b_all_gates_pass_allows_create_order |

---

## 3）Live 风险限制规则表（notional/频次）+ 审计证据

| 限制 | 配置 | reason_code | 是否触发 HTTP |
|------|------|-------------|---------------|
| 单笔名义价值 | live_max_order_notional | LIVE_RISK_NOTIONAL_EXCEEDED | 否 |
| 单笔 qty | live_max_order_qty | LIVE_RISK_QTY_EXCEEDED | 否 |
| 每小时订单数 | live_max_orders_per_hour | LIVE_RISK_HOURLY_LIMIT | 否 |
| 每日订单数 | live_max_orders_per_day | LIVE_RISK_DAILY_LIMIT | 否 |
| 价格不可用 | live_last_price_override / market_data | LIVE_RISK_PRICE_UNAVAILABLE | 否 |

**证据**：tests/integration/test_pr17b_live_risk_limits.py（notional、hourly、daily 超限拒绝，无 HTTP，审计存在）。

---

## 4）Live endpoint 真实选择路径证据

- **RealOkxHttpClient**：env=live 时构造成功，_env="live"，_base_url 为 live；env=prod 等无效值 fail-fast。
- **OkxExchangeAdapter**：live_endpoint=True 时 is_live_endpoint() 返回 True。
- **测试**：test_real_okx_http_client_live_allowed；test_pr17b_all_gates_pass_allows_create_order（Fake 下 post_calls>=1）。
- **离线**：默认使用 FakeOkxHttpClient，不访问外网。
- **External**：无；如需可 opt-in 并注明 live key 配置方式。

---

## 5）事故演练场景与回滚说明

### 场景 A：门禁全过但 live 风险超限 → 拒绝（无 HTTP）+ 审计
- **复现**：配置 live_max_order_notional=5，live_last_price_override=1000，qty=0.01 → notional=10 > 5。
- **预期**：ORDER_REJECTED，reason_code=LIVE_RISK_NOTIONAL_EXCEEDED，post_calls=0。
- **证据**：test_pr17b_notional_exceeded_rejects_no_http。

### 场景 B：transient 5xx → retry → 断路器打开 → 拒绝 → 可回滚
- **口径**：事故演练 B 为 **endpoint-agnostic**，Demo 路径与 live 路径均可触发断路器与 reset 审计。
- **Demo 路径**（is_live_endpoint=False）：test_pr17a_incident_b_circuit_breaker_then_reset_audit。
- **Live 路径**（is_live_endpoint=True）：test_pr17b_incident_b_live_path_5xx_circuit_reset。
- **复现**：fake transport 返回 5xx；2 笔失败 → 第三笔 CIRCUIT_OPEN；调用 close_circuit + append_event(CIRCUIT_RESET_BY_OPERATOR)。
- **预期**：CIRCUIT_OPENED、FINAL_FAILED；reset 后 CIRCUIT_RESET_BY_OPERATOR。
- **证据**：test_pr17b_incident_b_live_path_5xx_circuit_reset；scripts/reset_circuit_breaker.py。

---

## 6）回归不变式声明

- **幂等**：decision_id 不变。
- **事务边界**：CLAIM → 外部调用 → 落库，未改变。
- **风控**：RiskManager 语义不变。
- **审计**：execution_events 单调递增，无 secret 泄露。
- **事件体系统一**：OKX_HTTP_* 与 ORDER_* 分工不变；重试仅 Transient。

---

## 7）测试运行证据（pytest 原始输出）

**skipped / xfailed / warnings**：无；全部 passed。

### 7.1）pytest -q

```
........................................................................ [ 48%]
........................................................................ [ 97%]
...                                                                      [100%]
147 passed in 2.23s
```

### 7.2）pytest -q tests/integration

```
........................................................................ [ 97%]
..                                                                       [100%]
74 passed in 1.76s
```

---

## 8）新增/修改测试清单（补强版）

| 类型 | 路径 | 说明 |
|------|------|------|
| 新增 | tests/integration/test_pr17b_live_risk_limits.py | Live 风险限制（notional/hourly/daily）3 条 |
| **新增** | tests/integration/test_pr17a_incident_drill_rollback.py::test_pr17b_incident_b_live_path_5xx_circuit_reset | **Live path 事故 B：5xx→circuit→reset** |
| 修改 | tests/integration/test_pr17a_live_path_gates.py | test_pr17a_confirm_token_mismatch_rejects 断言 MISMATCH |
| 修改 | tests/unit/execution/test_live_gate.py | 新增 test_live_gate_confirm_token_missing_rejects；test_live_gate_confirm_token_mismatch_rejects 断言 MISMATCH |
| 修改 | tests/unit/execution/test_okx_client.py | test_real_okx_http_client_env_invalid_forbidden；test_real_okx_http_client_live_allowed |
| 修改 | tests/integration/test_pr14b_okx_config_and_dry_run.py | test_pr15a_okx_env_invalid_fail_fast |

---

## 9）风险清单与残余风险声明

| 风险 | 缓解 | 残余 |
|------|------|------|
| 误超限 | live 风险限制极小额；超限拒绝+审计 | 需运维按交易所规则配置 notional/频次 |
| live 误开 | 门禁全过 + token + allowlist；默认 allow_real_trading=false | 需显式配置与 token |
| 断路器误操作 | reset 脚本写 CIRCUIT_RESET_BY_OPERATOR | 需权限管控 |

**残余风险**：PR17b 首次允许 live create_order，建议先极小额度验证；上线前核对所有门禁与风险配置。

---

## 10）一键复现说明

```bash
cd trading_system
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/integration
```

- 默认离线，不访问外网。
- External tests：无；opt-in 时需提供 live key 并注明开启方式。

---

以上为 PR17b 工程级校验证据包（补强版）。
