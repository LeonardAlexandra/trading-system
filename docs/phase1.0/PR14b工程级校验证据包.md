# PR14b 工程级校验证据包

本文档用于 PR14b 的工程级放行判断：OKX 适配器骨架（Demo/Sandbox）、可测试的沙箱交互、可审计的全链路已实现，绝不产生真实下单副作用。所有结论均有证据来源。

---

## 1）变更摘要与边界

**做了什么**

- **目标 1 - OKX Adapter（Demo/Sandbox）**：实现 OkxExchangeAdapter，对接 OKX API v5 语义；仅实现 ExchangeAdapter 最小接口 create_order / cancel_order / get_order；返回结构符合 CreateOrderResult / GetOrderResult（含 exchange_order_id、status、filled_qty、avg_price、error）；错误分类为 TransientOrderError（可重试：50011 限频、5xxxx 服务器）与 PermanentOrderError（不可重试：50111–50116 鉴权、51xxx 订单拒绝）。PR14b 内不允许真实下单：仅使用注入的 OkxHttpClient（测试为 FakeOkxHttpClient，不访问网络）。
- **目标 2 - OKX 作为默认交易所仍安全**：配置层增加 okx 区段（env、api_key、secret、passphrase）；有 okx 时默认提供 exchange_profiles.okx_demo；okx.env 唯一允许值为 "demo"，缺 key/secret/passphrase 时启动 fail-fast。PR14b 阶段无论 live_enabled 如何，均强制 dry-run，不产生真实 side effect。
- **目标 3 - 密钥与安全**：OKX API Key/Secret/Passphrase 仅从 AppConfig 读取；禁止写入 log / response / execution_events / CONFIG_SNAPSHOT；validate() 在使用 okx_demo profile 时对 demo 下 key/secret/passphrase 非空做 fail-fast（reason_code OKX_SECRET_MISSING）。
- **目标 4 - 可测试性**：引入可注入的 OkxHttpClient 接口与 FakeOkxHttpClient；单元/集成测试不访问 OKX 网络；通过 Fake 模拟 OKX 返回 JSON 验证 create_order 成功/失败、cancel_order 成功/失败、get_order 状态映射（live/partially_filled/filled/canceled/rejected → 统一 OrderStatus）。
- **目标 5 - 审计**：ExecutionEngine 在下单/失败路径仍写 execution_events；新增 reason_code（OKX_AUTH_FAILED、OKX_RATE_LIMIT、OKX_TEMP_UNAVAILABLE、OKX_ORDER_REJECTED、OKX_SECRET_MISSING）进入白名单；DRY_RUN 标记继续存在；测试通过 Fake client 调用计数证明无 hit live endpoint。

**没做什么**

- 未真实访问 OKX 网络（测试全部离线可跑）。
- 未实盘下单、未把 live_enabled 作为“真的去下单”开关。
- 未引入 Redis/消息队列/Celery；未破坏 PR11–PR14a 不变式；未泄露任何 secret。

---

## 2）目标校验矩阵（代码位置 + 校验方式 + PASS/FAIL）

| 目标/风险点 | 代码位置 | 校验方式 | 预期结果 | 实际结果 | 证据引用 |
|-------------|----------|----------|----------|----------|----------|
| create_order OK → exchange_order_id/status/filled_qty | okx_adapter.py、FakeOkxHttpClient | test_okx_adapter_create_order_ok_returns_exchange_id_and_status | 返回 ordId、status=FILLED、filled_qty/avg_price | PASS | test_okx_adapter.py |
| create_order 错误分类 Transient/Permanent | okx_adapter.py | test_okx_adapter_create_order_*_transient/permanent | 50011→Transient；50111→Permanent；51xxx→Permanent；5xxxx→Transient | PASS | test_okx_adapter.py |
| cancel_order OK/Fail | okx_adapter.py | test_okx_adapter_cancel_order_ok / cancel_order_fail | code=0→True；非0→False | PASS | test_okx_adapter.py |
| get_order 状态映射 | okx_adapter.py _okx_status_to_unified | test_okx_status_to_unified、test_okx_adapter_get_order_state_mapping | live→SUBMITTED；filled→FILLED；canceled→CANCELLED；rejected→REJECTED | PASS | test_okx_adapter.py |
| okx demo 缺 key/secret/passphrase → fail-fast | app_config.py validate() | test_pr14b_okx_demo_missing_secret_fail_fast、test_pr14b_okx_demo_missing_passphrase_fail_fast | ConfigValidationError(reason_code=OKX_SECRET_MISSING) | PASS | test_pr14b_okx_config_and_dry_run.py |
| CONFIG_SNAPSHOT 不包含 okx secret | snapshot.py（白名单无 okx 密钥） | test_pr14b_config_snapshot_no_okx_secret | snapshot message 无 api_key/secret/passphrase | PASS | test_pr14b_okx_config_and_dry_run.py |
| 强制 dry-run：okx_demo + Fake client 无 live 调用 | DryRunExchangeAdapter(OkxExchangeAdapter(FakeOkxHttpClient)) | test_pr14b_dry_run_okx_demo_fake_client_no_live_call | 走完整链路；Fake post_calls=0；events dry_run；无 "live endpoint" | PASS | test_pr14b_okx_config_and_dry_run.py |
| 回归：PR11–PR14a 不变式与测试 | 全量 pytest | pytest -q、pytest -ra、pytest -q tests/integration | 76 通过（含 46 集成） | PASS | 见下文测试证据 |

---

## 3）回归不变式声明

- **幂等语义**：未改变。decision_id 仍为唯一幂等主键。
- **ExecutionEngine 事务边界**：未改变。CLAIM → resolve → 风控/限频/熔断 → 外部调用（Adapter）→ 落库。
- **风控规则**：未改变。RiskManager 语义未动。
- **审计语义**：未改变。execution_events 继续写入；DRY_RUN 标记存在；无 secret 写入 events/snapshot。
- **secret 隔离**：增强。okx api_key/secret/passphrase 仅存 AppConfig，不进入 log/events/snapshot/response。

---

## 4）测试运行证据（pytest 原始输出）

### 命令 1：pytest -q

```bash
cd trading_system && .venv/bin/python -m pytest -q
```

**终端原始输出：**

```
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 2.53s
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
collected 76 items

tests/execution/test_order_manager.py .......                            [  9%]
tests/integration/test_app_startup_config_injection.py ..                [ 11%]
tests/integration/test_config_snapshot_event.py ...                      [ 15%]
tests/integration/test_execution_events.py ....                          [ 21%]
tests/integration/test_execution_worker.py ....                          [ 26%]
tests/integration/test_order_manager_audit.py ..                         [ 28%]
tests/integration/test_pr11_strategy_isolation.py .....                  [ 35%]
tests/integration/test_pr13_safety_valves.py ....                        [ 40%]
tests/integration/test_pr14a_live_gate_and_shared_state.py .....         [ 47%]
tests/integration/test_pr14b_okx_config_and_dry_run.py ....              [ 52%]
tests/integration/test_risk_manager.py .....                             [ 59%]
tests/integration/test_tradingview_webhook.py .......                    [ 68%]
tests/integration/test_tradingview_webhook_config_validation.py .        [ 69%]
tests/unit/application/test_signal_service.py ...                        [ 73%]
tests/unit/execution/test_okx_adapter.py .........                       [ 85%]
tests/unit/repositories/test_decision_order_map_repo.py ....             [ 90%]
tests/unit/repositories/test_dedup_signal_repo.py ....                   [ 96%]
tests/unit/repositories/test_orders_repo.py ...                          [100%]

============================== 76 passed in 2.22s ==============================
```

---

### 命令 3：pytest -q tests/integration

```bash
cd trading_system && .venv/bin/python -m pytest -q tests/integration
```

**终端原始输出：**

```
..............................................                           [100%]
46 passed in 2.53s
```

---

## 5）新增/修改测试清单

| 文件路径 | 测试函数名 | 关键断言点 | 覆盖目标 |
|----------|------------|------------|----------|
| tests/unit/execution/test_okx_adapter.py | test_okx_adapter_create_order_ok_returns_exchange_id_and_status | exchange_order_id/status/filled_qty/avg_price；Fake post_calls 一次 | create_order OK 映射 |
| tests/unit/execution/test_okx_adapter.py | test_okx_adapter_create_order_rate_limit_transient | 50011 → TransientOrderError | 错误分类 Transient |
| tests/unit/execution/test_okx_adapter.py | test_okx_adapter_create_order_auth_failed_permanent | 50111 → PermanentOrderError | 错误分类 Permanent |
| tests/unit/execution/test_okx_adapter.py | test_okx_adapter_create_order_server_error_transient | 50000 → TransientOrderError | 错误分类 Transient |
| tests/unit/execution/test_okx_adapter.py | test_okx_adapter_create_order_rejected_permanent | 51000 → PermanentOrderError | 错误分类 Permanent |
| tests/unit/execution/test_okx_adapter.py | test_okx_adapter_cancel_order_ok / cancel_order_fail | code=0→True；非0→False | cancel_order OK/Fail |
| tests/unit/execution/test_okx_adapter.py | test_okx_status_to_unified、test_okx_adapter_get_order_state_mapping | live→SUBMITTED；filled→FILLED；canceled→CANCELLED；rejected→REJECTED | get_order 状态映射 |
| tests/integration/test_pr14b_okx_config_and_dry_run.py | test_pr14b_okx_demo_missing_secret_fail_fast | OKX_SECRET_MISSING、message 含 api_key | 配置 fail-fast |
| tests/integration/test_pr14b_okx_config_and_dry_run.py | test_pr14b_okx_demo_missing_passphrase_fail_fast | OKX_SECRET_MISSING、message 含 passphrase | 配置 fail-fast |
| tests/integration/test_pr14b_okx_config_and_dry_run.py | test_pr14b_config_snapshot_no_okx_secret | snapshot 字符串无 secret-key/secret-value/secret-pass | CONFIG_SNAPSHOT 无 secret |
| tests/integration/test_pr14b_okx_config_and_dry_run.py | test_pr14b_dry_run_okx_demo_fake_client_no_live_call | DryRun(Okx(Fake))；result filled；post_calls=0；events dry_run；无 "live endpoint" | 强制 dry-run 安全 |

---

## 6）配置与运维影响

- **新增配置项**（均有默认值或 fail-fast）：
  - **okx**（可选区段）：env（默认 "demo"，PR14b 唯一允许值）、api_key、secret、passphrase。可从环境变量 OKX_API_KEY、OKX_SECRET、OKX_PASSPHRASE 覆盖。
  - 当 exchange_profiles 中存在 okx_demo 或 mode/name 为 okx_demo/okx 时，必须提供 okx 区段且 env=demo，api_key/secret/passphrase 非空，否则启动 ConfigValidationError(OKX_SECRET_MISSING 或 INVALID_EXECUTION_CONFIGURATION)。
- **默认 exchange_profiles**：当配置中存在 okx 区段时，自动添加 exchange_profiles.okx_demo（id=okx_demo，name=okx，mode=okx_demo），便于“默认交易所=OKX”。
- **fail-fast**：validate() 校验上述项；缺项或 env≠demo → ConfigValidationError。

---

## 7）风险清单与残余风险声明

- **已缓解**：真实网络访问 → 测试全部使用 FakeOkxHttpClient，不访问 OKX；生产 PR14b 仍强制 dry-run，DryRunExchangeAdapter 不调用 inner create_order。
- **已缓解**：secret 泄露 → okx 密钥不写入 log/events/snapshot/response；CONFIG_SNAPSHOT 白名单不包含 okx。
- **残余风险**：PR14b 不实现真实 HTTP 客户端；仅当后续 PR（如 PR15）引入“可选 live endpoint”时，需在真实客户端中严格使用 Demo URL 与 x-simulated-trading: 1 header，并保留门禁。

---

## 8）一键复现说明（离线测试如何跑）

- **环境准备**：`cd trading_system`，Python 3.10+，`pip install -e ".[dev]"`（或项目 .venv）。
- **运行测试**（无需网络、无需 OKX API Key）：
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/python -m pytest -ra`
  - `.venv/bin/python -m pytest -q tests/integration`
- **仅跑 PR14b 相关**：
  - `.venv/bin/python -m pytest tests/unit/execution/test_okx_adapter.py tests/integration/test_pr14b_okx_config_and_dry_run.py -v`
- **环境变量**：测试使用假 key（config 中 okx.api_key/secret/passphrase 为占位字符串）；无需真实 OKX 密钥。

---

**PR14b 成功标准**：OKX adapter 骨架完成（Demo/Sandbox）、完全离线可测；OKX 成为默认交易所（默认 profile okx_demo）；仍强制 dry-run，绝不产生真实下单副作用；不泄露 secret；tests 全绿 + 工程级证据包完整。
