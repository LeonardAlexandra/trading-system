# PR15b 工程级校验证据包

本文档用于 PR15b 的工程级放行判断：在 OKX Demo/Sandbox 环境下安全开放 create_order 真实 HTTP 下单能力，与 ExecutionEngine/OrderManager/审计体系形成闭环；重试策略门禁化；事件体系统一（OKX_HTTP_* vs ORDER_*）。所有结论均有证据来源。

---

## 1）变更摘要与边界

**做了什么**

- **目标 1 - 开放 OKX Demo 真实 create_order**：OkxExchangeAdapter.create_order 通过注入的 OkxHttpClient 发出真实 HTTP 请求（仅 demo：env 必须 demo + RealOkxHttpClient 门禁 live）。最小订单类型：市价单（ordType=market）。请求/响应映射完整：exchange_order_id、status（SUBMITTED/REJECTED/FILLED 等）、filled_qty/avg_price（OKX 无则 None）。新增通信审计事件 OKX_HTTP_CREATE_ORDER（action/http_status/okx_code/request_id/attempt，受控长度）；禁止 api_key/secret/passphrase/签名/原始 header。
- **目标 2 - 订单业务审计与通信审计体系统一**：  
  - **通信审计（只记录网络交互结果）**：OKX_HTTP_CREATE_ORDER、OKX_HTTP_GET_ORDER、OKX_HTTP_CANCEL_ORDER、OKX_HTTP_RETRY。  
  - **订单业务审计（只记录订单状态与业务动作）**：ORDER_SUBMIT_OK、ORDER_SUBMIT_FAILED、ORDER_CANCELLED、ORDER_SYNCED 等。  
  禁止在 OKX_HTTP_* 中写订单业务状态变更（除 http/okx_code/attempt）；禁止在 ORDER_* 中写密钥/签名/HTTP header。
- **目标 3 - 重试策略门禁化**：仅对 TransientOrderError 重试（网络错误、5xx、限频/临时不可用）；对 PermanentOrderError 禁止重试（4xx/鉴权/参数错误/拒单）。重试次数有限（max_attempts）+ backoff（execution.backoff_seconds）。每次重试/失败均写 OKX_HTTP_CREATE_ORDER（含 attempt）；重试失败后 execution FAILED，reason_code 明确（OKX_TEMP_UNAVAILABLE/OKX_RATE_LIMIT/OKX_AUTH_FAILED/ORDER_REJECTED 等）。重试在 ExecutionEngine 层实现，不破坏事务边界与幂等语义。
- **目标 4 - 默认测试离线；真实网络 opt-in**：默认 pytest 不访问外网；真实 OKX Demo 网络测试标记 @pytest.mark.external，默认跳过，RUN_EXTERNAL_OKX_TESTS=true 开启；离线测试使用 FakeOkxHttpClient 模拟 create_order 成功/拒绝/鉴权/限频/5xx，覆盖错误分类与重试。

**没做什么**

- 未允许 live endpoint；未对 Permanent 错误重试；未混用 OKX_HTTP_* 与 ORDER_* 字段职责；未泄露 secret/签名/原始 header；未改变 ExecutionEngine 幂等与事务边界；未改变 RiskManager 语义。

---

## 2）目标校验矩阵（代码位置 + 校验方式 + PASS/FAIL）

| 目标/风险点 | 代码位置 | 校验方式 | 预期结果 | 实际结果 | 证据引用 |
|-------------|----------|----------|----------|----------|----------|
| create_order 成功 → CreateOrderResult + 审计字段 | okx_adapter.py | test_okx_adapter_create_order_success | exchange_order_id、status、http_status、okx_code；无 secret | PASS | test_okx_adapter.py |
| 鉴权/拒单 → PermanentOrderError，不重试 | okx_adapter.py、execution_engine.py | test_okx_adapter_create_order_auth_failed_permanent、test_pr15b_create_order_permanent_no_retry | PermanentOrderError；attempt_count=1；OKX_HTTP_CREATE_ORDER + FINAL_FAILED | PASS | test_okx_adapter.py、test_pr15b_okx_create_order_closed_loop.py |
| 限频/5xx → TransientOrderError，可重试 | okx_adapter.py、execution_engine.py | test_okx_adapter_create_order_rate_limit_transient、test_okx_adapter_create_order_server_error_transient、test_pr15b_create_order_transient_then_success | TransientOrderError；第一次 retry_scheduled；第二次成功 ORDER_SUBMIT_OK | PASS | test_okx_adapter.py、test_pr15b_okx_create_order_closed_loop.py |
| OKX_HTTP_CREATE_ORDER 仅含 action/http_status/okx_code/request_id/attempt | execution_engine.py _okx_http_create_order_message | test_okx_http_create_order_message_only_allowed_keys、test_okx_http_message_no_secret | message 无 secret/passphrase/api_key/sign | PASS | test_event_schema_pr15b.py |
| 事件体系统一：OKX_HTTP_* vs ORDER_* | event_types.py、execution_engine.py、order_manager.py | test_order_event_types_exist、test_okx_http_event_types_list | 类型分离；ORDER_* 不含通信敏感字段 | PASS | test_event_schema_pr15b.py |
| 成功路径：OKX_HTTP_CREATE_ORDER + ORDER_SUBMIT_OK | execution_engine.py | test_pr15b_create_order_success_okx_http_and_order_submit_ok | 事件含 OKX_HTTP_CREATE_ORDER、ORDER_SUBMIT_OK；message 无 secret | PASS | test_pr15b_okx_create_order_closed_loop.py |
| 回归：全量 pytest | 全量 | pytest -q、pytest -ra、pytest -q tests/integration | 90 passed（50 集成） | PASS | 见下文测试证据 |

---

## 3）回归不变式声明

- **幂等语义**：未改变。decision_id 仍为唯一幂等主键。
- **ExecutionEngine 事务边界**：未改变。CLAIM → resolve → 风控/限频/熔断 → 外部调用（create_order）→ 落库；重试通过 RESERVED + next_run_at 再次 claim，不破坏边界。
- **风控规则**：未改变。RiskManager 语义未动。
- **审计语义**：增强。OKX_HTTP_CREATE_ORDER 记录每次 create_order 通信结果（含 attempt）；ORDER_SUBMIT_OK/ORDER_SUBMIT_FAILED/FINAL_FAILED 记录业务结果；OKX_HTTP_* 与 ORDER_* 职责分离，无混用。
- **secret 隔离**：维持。OKX_HTTP_* message 仅含 action/http_status/okx_code/request_id/attempt；无 api_key/secret/passphrase/签名字符串/原始 header。

---

## 4）测试运行证据（pytest 原始输出）

### 命令 1：pytest -q

```bash
cd trading_system && .venv/bin/python -m pytest -q
```

**终端原始输出：**

```
........................................................................ [ 80%]
..................                                                       [100%]
90 passed in 4.27s
```

---

### 命令 2：pytest -ra

```bash
cd trading_system && .venv/bin/python -m pytest -ra -q
```

**终端原始输出：**

```
90 passed in 2.45s
```

---

### 命令 3：pytest -q tests/integration

```bash
cd trading_system && .venv/bin/python -m pytest -q tests/integration
```

**终端原始输出：**

```
..................................................                       [100%]
50 passed in 2.42s
```

---

### 可选 external 测试（PR15b）

- 真实 OKX Demo 网络测试（若有）须标记 `@pytest.mark.external`。
- 默认不运行；开启方式：`RUN_EXTERNAL_OKX_TESTS=true` 或 `pytest --run-external-okx-tests ...`。
- 未提供真实 API Key 时测试应自动 skip；输出中不得打印 secret。

---

## 5）新增/修改测试清单（断言点明确）

| 测试文件 | 新增/修改 | 断言点 |
|----------|------------|--------|
| tests/unit/execution/test_okx_adapter.py | 修改 | create_order 成功返回 exchange_order_id/status/http_status/okx_code；鉴权 50111→PermanentOrderError；限频 50011→TransientOrderError；51xxx→PermanentOrderError；5xx→TransientOrderError |
| tests/unit/common/test_event_schema_pr15b.py | 新增 | OKX_HTTP_CREATE_ORDER message 仅含 action/http_status/okx_code/request_id/attempt；无 secret/passphrase/api_key；ORDER_* 与 OKX_HTTP_* 类型分离 |
| tests/integration/test_pr15b_okx_create_order_closed_loop.py | 新增 | 成功路径：OKX_HTTP_CREATE_ORDER + ORDER_SUBMIT_OK，message 无 secret；Permanent 路径：OKX_HTTP_CREATE_ORDER + FINAL_FAILED，attempt_count=1，post_calls=1；Transient 重试路径：第一次 5xx→retry_scheduled，第二次成功→ORDER_SUBMIT_OK，post_calls=2 |

---

## 6）配置与运维影响

- **无新增必填配置**。okx.env 继续仅允许 "demo"；create_order 仅在 dry_run=false 且使用 OkxExchangeAdapter（非 DryRunExchangeAdapter）时发出真实 HTTP。
- **重试**：沿用 execution.max_attempts、execution.backoff_seconds；仅 TransientOrderError 重试，PermanentOrderError 不重试。
- **事件**：新增 OKX_HTTP_CREATE_ORDER、OKX_HTTP_RETRY、ORDER_SUBMITTED、ORDER_REJECTED 常量；OKX_HTTP_CREATE_ORDER 在每次 create_order 调用后写入（成功或失败），message 受控长度。

---

## 7）风险清单与残余风险声明

- **已缓解**：live 误用 → RealOkxHttpClient + AppConfig 双重门禁；create_order 仅通过注入 client，demo 唯一。
- **已缓解**：Permanent 被重试 → ExecutionEngine 仅对 TransientOrderError 重试，PermanentOrderError 单独分支直接 FAILED。
- **已缓解**：事件混用/泄密 → OKX_HTTP_* message 仅含通信字段；ORDER_* 不含 secret/header；schema 断言测试防回归。
- **残余风险**：真实 Demo 网络/账户异常需人工或 external 测试验证；PR16 更接近实盘演练/灰度门禁时需再次审查。

---

## 8）一键复现说明（离线与 external）

**离线测试（默认，不访问外网）：**

```bash
cd trading_system
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -ra -q
.venv/bin/python -m pytest -q tests/integration
```

**可选：开启 external 测试（需 OKX Demo API Key，且不打印 secret）：**

```bash
export RUN_EXTERNAL_OKX_TESTS=true
.venv/bin/python -m pytest -v -m external
# 或
.venv/bin/python -m pytest -v --run-external-okx-tests
```
