# PR15a 工程级校验证据包

本文档用于 PR15a 的工程级放行判断：引入真实 OkxHttpClient（仅 demo endpoint）、仅开放 get_order/cancel_order 真实请求、create_order 明确禁用、真实 HTTP 行为可审计且不泄露 secret。所有结论均有证据来源。

---

## 1）变更摘要与边界

**做了什么**

- **目标 1 - 真实 OkxHttpClient（仅 demo endpoint）**：实现 RealOkxHttpClient（`src/execution/okx_client.py`），支持 OKX API v5 签名（HMAC-SHA256 + Base64）、仅允许 demo 环境（env 必须为 "demo"）；env 为 live/production 时构造 fail-fast（reason_code OKX_LIVE_FORBIDDEN）。Demo 请求使用 `https://www.okx.com` + header `x-simulated-trading: 1`。密钥仅从构造参数/AppConfig 读取，禁止写入 log/events/snapshot/response。支持可注入 transport（测试可离线）。
- **目标 2 - OkxExchangeAdapter 仅允许真实 get_order / cancel_order**：create_order 在 PR15a 明确禁用，直接抛出 PermanentOrderError("create_order disabled in PR15a")，不产生任何真实下单请求。get_order / cancel_order 使用注入的 OkxHttpClient（Fake 或 Real），返回结果携带 http_status、okx_code、request_id 用于审计。
- **目标 3 - 真实 HTTP 请求的审计**：每次真实 get_order / cancel_order 后，OrderManager 写入 execution_events（event_type OKX_HTTP_GET_ORDER / OKX_HTTP_CANCEL_ORDER），事件含 action、http_status、okx_code、request_id（受控长度）；不含 api_key/secret/passphrase/签名字符串/原始 header。错误分类 reason_code 可区分（OKX_AUTH_FAILED、OKX_RATE_LIMIT、OKX_TEMP_UNAVAILABLE、OKX_BAD_REQUEST 等）。
- **目标 4 - 可测试性**：默认 pytest 不访问外网。真实 OkxHttpClient 网络测试可标记 @pytest.mark.external，默认跳过；通过 RUN_EXTERNAL_OKX_TESTS=true 或 --run-external-okx-tests 开启。FakeOkxHttpClient 与可注入 transport 保证单测/集成测试离线可跑。新增 OkxHttpClient 签名离线单元测试、RealOkxHttpClient env!=demo fail-fast 测试、create_order 禁用测试。

**没做什么**

- 未允许任何 create_order 的真实 HTTP 下单请求（demo 也不行）。
- 未允许 live endpoint；未改变 ExecutionEngine 幂等/事务边界；未泄露 secret。
- 未引入新外部依赖导致本地测试无法运行（httpx 已加入主依赖，可注入 transport）。

---

## 2）目标校验矩阵（代码位置 + 校验方式 + PASS/FAIL）

| 目标/风险点 | 代码位置 | 校验方式 | 预期结果 | 实际结果 | 证据引用 |
|-------------|----------|----------|----------|----------|----------|
| OkxHttpClient 签名与请求构造（离线） | okx_client.py _okx_sign | test_okx_sign_fixed_timestamp_and_secret、test_okx_sign_post_with_body | 固定时间戳/secret 签名一致；POST body 参与 prehash | PASS | test_okx_client.py |
| RealOkxHttpClient env!=demo fail-fast | okx_client.py RealOkxHttpClient.__init__ | test_real_okx_http_client_live_forbidden | ConfigValidationError(reason_code=OKX_LIVE_FORBIDDEN) | PASS | test_okx_client.py |
| create_order 在 PR15a 明确禁用 | okx_adapter.py create_order | test_okx_adapter_create_order_disabled_pr15a | PermanentOrderError("create_order disabled in PR15a")；post_calls=0 | PASS | test_okx_adapter.py |
| cancel_order 返回 CancelOrderResult + 审计字段 | okx_adapter.py、order_manager.py | test_okx_adapter_cancel_order_ok/fail | success、http_status、okx_code；OrderManager 写 OKX_HTTP_CANCEL_ORDER | PASS | test_okx_adapter.py、order_manager.py |
| get_order 返回审计字段；OrderManager 写 OKX_HTTP_GET_ORDER | okx_adapter.py、order_manager.py | test_okx_adapter_get_order_state_mapping | GetOrderResult 含 http_status/okx_code/request_id；事件不含 secret | PASS | test_okx_adapter.py |
| okx.env=live 启动 fail-fast | app_config.py validate() | test_pr15a_okx_env_live_fail_fast | ConfigValidationError(OKX_LIVE_FORBIDDEN) | PASS | test_pr14b_okx_config_and_dry_run.py |
| 默认测试离线可跑 | conftest.py、pytest.mark.external | pytest -q（无外网） | 79 passed | PASS | 见下文测试证据 |
| 回归：PR14b/PR14a 不变式 | 全量 pytest | pytest -q、pytest -ra、pytest -q tests/integration | 79 通过（47 集成） | PASS | 见下文测试证据 |

---

## 3）回归不变式声明

- **幂等语义**：未改变。decision_id 仍为唯一幂等主键。
- **ExecutionEngine 事务边界**：未改变。CLAIM → resolve → 风控/限频/熔断 → 外部调用（Adapter）→ 落库。
- **风控规则**：未改变。RiskManager 语义未动。
- **审计语义**：增强。execution_events 新增 OKX_HTTP_GET_ORDER / OKX_HTTP_CANCEL_ORDER；事件 message 仅含 action、http_status、okx_code、request_id（受控长度）；无 secret/签名字符串/原始 header。
- **secret 隔离**：维持。okx api_key/secret/passphrase 不进入 log/events/snapshot/response；RealOkxHttpClient 不在日志中输出 header/签名。

---

## 4）测试运行证据（pytest 原始输出）

### 命令 1：pytest -q

```bash
cd trading_system && .venv/bin/python -m pytest -q
```

**终端原始输出：**

```
........................................................................ [ 91%]
.......                                                                  [100%]
79 passed in 4.00s
```

---

### 命令 2：pytest -ra

```bash
cd trading_system && .venv/bin/python -m pytest -ra
```

**终端原始输出：**

```
........................................................................ [ 91%]
.......                                                                  [100%]
79 passed in 4.74s
```

---

### 命令 3：pytest -q tests/integration

```bash
cd trading_system && .venv/bin/python -m pytest -q tests/integration
```

**终端原始输出：**

```
...............................................                          [100%]
47 passed in 3.82s
```

---

### 可选 external 测试（PR15a）

- 真实 OKX Demo 网络测试（若有）须标记 `@pytest.mark.external`。
- 默认不运行；开启方式：
  - 环境变量：`RUN_EXTERNAL_OKX_TESTS=true`
  - 命令行：`pytest --run-external-okx-tests ...`
- 未提供真实 API Key 时测试应自动 skip；输出中不得打印 secret。

---

## 5）新增/修改测试清单

| 测试文件 | 新增/修改 | 说明 |
|----------|------------|------|
| tests/unit/execution/test_okx_client.py | 新增 | 签名离线断言、env!=demo fail-fast、Fake 返回 OkxResponse |
| tests/unit/execution/test_okx_adapter.py | 修改 | create_order 改为禁用断言；cancel_order 断言 CancelOrderResult |
| tests/integration/test_pr14b_okx_config_and_dry_run.py | 新增 | test_pr15a_okx_env_live_fail_fast |
| tests/integration/test_pr13_safety_valves.py | 修改 | FailingAdapter.cancel_order 返回 CancelOrderResult |
| tests/integration/test_pr14a_live_gate_and_shared_state.py | 修改 | FailingAdapter.cancel_order 返回 CancelOrderResult |
| tests/conftest.py | 修改 | 注册 pytest.mark.external；默认跳过 external 测试 |

---

## 6）配置与运维影响

- **新增/变更配置**：无新增必填项。okx.env 继续仅允许 "demo"；若配置为 "live" 启动 fail-fast（reason_code OKX_LIVE_FORBIDDEN）。
- **默认值**：okx.env 默认 "demo"；RealOkxHttpClient 仅在此环境下允许构造。
- **Fail-fast**：okx.env != "demo" 时 AppConfig.validate() 与 RealOkxHttpClient 构造均抛出 ConfigValidationError(OKX_LIVE_FORBIDDEN)。

---

## 7）风险清单与残余风险声明

- **已缓解**：真实网络访问 → 默认测试全部离线；RealOkxHttpClient 仅 demo；create_order 硬编码禁用。
- **已缓解**：live 误用 → 配置与客户端双重门禁（validate + 构造时检查）。
- **已缓解**：secret 泄露 → 事件/日志/snapshot 白名单不包含 okx 密钥；审计事件仅含 http_status、okx_code、request_id。
- **残余风险**：若未来启用 create_order（PR15b），需单独放行与审计；当前 PR15a 不涉及下单闭环。

---

## 8）一键复现说明

**离线测试（默认，不访问外网）：**

```bash
cd trading_system
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -ra
.venv/bin/python -m pytest -q tests/integration
```

**可选：开启 external 测试（需 OKX Demo API Key，且不打印 secret）：**

```bash
export RUN_EXTERNAL_OKX_TESTS=true
.venv/bin/python -m pytest -v -m external
# 或
.venv/bin/python -m pytest -v --run-external-okx-tests
```

（当前代码库未包含需外网的 external 用例；若后续添加，须标记 @pytest.mark.external 并遵守上述约定。）
