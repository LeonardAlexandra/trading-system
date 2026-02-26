# Phase1.2 C8 模块证据包：多笔回放与审计查询界面（T1.2b-2）

## 模块名称与目标

| 项目 | 内容 |
|------|------|
| 模块编号 | C8 |
| 模块名称 | 多笔回放与审计查询界面（T1.2b-2） |
| 目标 | 提供多笔回放 API（list_traces）与审计日志查询界面（CLI 或 Web）；每条 TraceSummary 含 trace_status，PARTIAL 时含 missing_nodes；界面与 1.2a 入库数据一致。 |

---

## 本次修改/新增的文件清单

| 类型 | 路径 |
|------|------|
| 修改 | `src/schemas/trace.py` |
| 修改 | `src/services/trace_query_service.py` |
| 修改 | `src/services/audit_service.py` |
| 修改 | `tests/integration/test_phase12_c8_list_traces.py` |
| 新增 | `docs/runlogs/c8_pytest.txt` |
| 新增 | `docs/Phase1.2_C8_模块证据包.md`（本文件） |
| **C8-R1** | 修改 `src/app/routers/audit.py`（错误码 400/404/500、统一 error_code/message、列表上限 100） |
| **C8-R1** | 修改 `tests/integration/test_phase12_c8_list_traces.py`（新增 test_audit_traces_400_param_error、test_audit_traces_500_service_exception） |
| **C8-R1** | 新增 `docs/runlogs/c8_r1_pytest.txt` |

无新增路由或 CLI 入口；审计界面（CLI `logs` / Web `/api/audit/logs` + 页面）已存在；C8-R1 仅补齐错误码语义与测试。

---

## 实际执行的命令（逐条列出）

1. `cd /Users/zhangkuo/TradingView Indicator/trading_system && python -m pytest tests/integration/test_phase12_c8_list_traces.py -v`
2. `cd /Users/zhangkuo/TradingView Indicator/trading_system && python -m pytest tests/integration/test_phase12_c8_list_traces.py -v 2>&1 | tee docs/runlogs/c8_pytest.txt`
3. **C8-R1**：`python3 -m pytest tests/integration/test_phase12_c8_list_traces.py -v 2>&1 | tee docs/runlogs/c8_r1_pytest.txt`

---

## 命令的真实输出结果

见 `docs/runlogs/c8_pytest.txt`、`docs/runlogs/c8_r1_pytest.txt`。

**C8-R1 pytest 原始输出**（完整见 `docs/runlogs/c8_r1_pytest.txt`）：

```
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
collecting ... collected 5 items

tests/integration/test_phase12_c8_list_traces.py::test_list_traces_partial_missing_decision_snapshot PASSED [ 20%]
tests/integration/test_phase12_c8_list_traces.py::test_list_traces_partial_missing_trade PASSED [ 40%]
tests/integration/test_phase12_c8_list_traces.py::test_audit_log_query_interface_matches_log_repository PASSED [ 60%]
tests/integration/test_phase12_c8_list_traces.py::test_audit_traces_400_param_error PASSED [ 80%]
tests/integration/test_phase12_c8_list_traces.py::test_audit_traces_500_service_exception PASSED [100%]

============================== 5 passed in 0.37s ===============================
```

---

## 本模块核心实现（关键代码）

### 1. TraceQueryService.list_traces（`src/services/trace_query_service.py`）

- 签名：`async def list_traces(self, start_ts, end_ts, strategy_id=None, limit=100, offset=0) -> List[TraceSummary]`
- 行为：limit 截断至 LIST_TRACES_MAX_LIMIT(100)；按 strategy_id 有无调用 list_decisions 或 list_decisions_by_time，再对每条 decision 调用 get_trace_by_decision_id，组装 TraceSummary（含 trace_status、missing_nodes；PARTIAL 时 missing_nodes 非空由 C2 保证）。

### 2. TraceSummary 结构（`src/schemas/trace.py`）

- 必填：decision_id, trace_status, missing_nodes。
- 可选：strategy_id, symbol, created_at, signal_id, summary（蓝本 D.9）。
- PARTIAL 时 missing_nodes 由 TraceQueryService.get_trace_by_decision_id 返回非空列表。

### 3. 审计日志查询界面

- **CLI**：`src/cli/audit.py` 子命令 `logs`，参数 `--from`、`--to`、`--component`、`--level`，内部调用 `audit_service.query_logs`。
- **Web**：`GET /api/audit/logs`（from/to, component, level），实现于 `src/app/routers/audit.py`，调用 `audit_service.query_logs`。
- `audit_service.query_logs` 仅调用 `LogRepository.query(created_at_from, created_at_to, component, level, limit, offset)`，不修改 C3 语义。

### 4. C8-R1 错误码与异常映射（`src/app/routers/audit.py`）

- **400 参数错误**：body 含 `error_code=INVALID_PARAMS`、`message`。触发：`/api/audit/traces` 缺少或无效 from/to、from > to；`/api/audit/logs` 传入无效 from/to 或 from > to。不使用 FastAPI 默认 422。
- **404 未找到**：当前 list 接口无“单资源未找到”语义；空列表返回 200 + `items=[]`。404 保留用于未来单资源查询（如有）。
- **500 服务错误**：未预期异常被捕获后，写入 `LogRepository.write("ERROR", "audit_api", message, event_type=...)`，不泄露敏感信息；返回 `error_code=INTERNAL_ERROR`、`message="Internal server error"`。
- **列表上限**：`/api/audit/traces` 的 limit 为 `Query(100, ge=1, le=100)`，未放宽。

关键代码片段（异常与响应）：

```python
# 400
return JSONResponse(
    status_code=400,
    content={"error_code": ERROR_CODE_INVALID_PARAMS, "message": "Missing or invalid parameter: from"},
)
# 500
async def _log_error_and_return_500(message: str, event_type: str = "internal_error") -> JSONResponse:
    try:
        async with get_db_session() as session:
            repo = LogRepository(session)
            await repo.write("ERROR", AUDIT_API_COMPONENT, message, event_type=event_type)
            await session.commit()
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={"error_code": ERROR_CODE_INTERNAL_ERROR, "message": "Internal server error"},
    )
```

---

## 本模块对应的测试用例与可复现步骤

| 用例 | 说明 |
|------|------|
| `test_list_traces_partial_missing_decision_snapshot` | 有 decision 无 decision_snapshot → list_traces 返回该条 PARTIAL，missing_nodes 含 decision_snapshot 且非空。 |
| `test_list_traces_partial_missing_trade` | 有 decision + snapshot、无 execution/trade → PARTIAL，missing_nodes 含 trade 且非空。 |
| `test_audit_log_query_interface_matches_log_repository` | 写入 log 后，audit_service.query_logs 与 LogRepository.query 同条件查询结果 id 集合一致，验证审计界面筛选与 log 表一致且仅用 LogRepository.query。 |
| **C8-R1** `test_audit_traces_400_param_error` | 参数错误 → 400：缺 to、from>to、无效 datetime；断言 status_code==400、error_code==INVALID_PARAMS、message 存在。 |
| **C8-R1** `test_audit_traces_500_service_exception` | 服务异常 → 500：monkeypatch audit_service.list_traces 抛异常；断言 status_code==500、error_code==INTERNAL_ERROR、message 含 "Internal server error"。 |

可复现：在项目根执行  
`python3 -m pytest tests/integration/test_phase12_c8_list_traces.py -v`

---

## 与本模块验收口径的逐条对照说明

| 验收口径（Phase1.2 交付包 C8） | 实现/校验方式 | 结果 |
|--------------------------------|----------------|------|
| list_traces 返回列表；任一条 PARTIAL 含 missing_nodes 非空及已有节点摘要。 | TraceQueryService.list_traces 返回 List[TraceSummary]；PARTIAL 由 get_trace_by_decision_id 保证 missing_nodes 非空；TraceSummary 含 summary 等。test_list_traces_partial_* 断言 PARTIAL 与 missing_nodes。 | YES |
| 审计界面按时间/组件/级别筛选结果与 log 表一致。 | query_logs 仅调用 LogRepository.query；test_audit_log_query_interface_matches_log_repository 断言同条件查询结果 id 一致。 | YES |
| **C8-R1** 错误码 400 参数错误 | GET /api/audit/traces、/api/audit/logs 在缺参/无效/from>to 时返回 400，body 含 error_code=INVALID_PARAMS、message。test_audit_traces_400_param_error 覆盖缺 to、from>to、无效 datetime。 | YES，证据：`src/app/routers/audit.py`、`test_phase12_c8_list_traces.py::test_audit_traces_400_param_error` |
| **C8-R1** 错误码 404 未找到 | 当前仅 list 接口，空列表 200+[]；404 保留用于单资源未找到（现有无此端点）。 | YES，证据：路由无单资源 by-id，列表空为 200 |
| **C8-R1** 错误码 500 服务错误 | 未预期异常捕获后写 LogRepository ERROR、返回 500，body 含 error_code=INTERNAL_ERROR、message 不泄露敏感信息。test_audit_traces_500_service_exception 通过 monkeypatch 注入异常。 | YES，证据：`_log_error_and_return_500`、`test_phase12_c8_list_traces.py::test_audit_traces_500_service_exception` |
| **C8-R1** 列表单次上限 100 | /api/audit/traces 的 limit 为 Query(100, ge=1, le=100)，未放宽。 | YES，证据：`src/app/routers/audit.py` get_traces limit 参数 |

---

## 验收结论

- **是否满足模块目标**：是。  
- list_traces 已实现于 TraceQueryService，返回 list[TraceSummary]，trace_status / missing_nodes 规则满足；审计查询界面（CLI + Web）仅调用 LogRepository.query，筛选结果与 log 表一致，且已有测试与 runlog 可审计。
- **C8-R1**：错误码 400/404/500 已按蓝本补齐；参数错误返回 400（INVALID_PARAMS）、服务异常返回 500（INTERNAL_ERROR）并写 ERROR 日志；列表上限 100 保持；pytest 5 条全部通过，证据见 `docs/runlogs/c8_r1_pytest.txt`。

---

## 【封版变更记录】

- **为何重开**：按「唯一真理源」Phase1.2_模块化开发交付包【C8】逐条实现时，发现 list_traces 须落在 **TraceQueryService** 上（交付包明确「TraceQueryService.list_traces」），且 TraceSummary 须含 trace_status / missing_nodes 规则及蓝本 D.9 的 summary 等；审计界面须**仅**调用 LogRepository.query。此前实现中 list_traces 仅在 audit_service 内实现、未在 TraceQueryService 上提供，存在语义与真理源不一致风险，故重开 C8 以对齐交付包。
- **变更影响面**：  
  - **文件**：`src/schemas/trace.py`（TraceSummary 增加 summary）、`src/services/trace_query_service.py`（新增 list_traces）、`src/services/audit_service.py`（list_traces 改为调用 TraceQueryService.list_traces）、`tests/integration/test_phase12_c8_list_traces.py`（新增审计界面与 LogRepository.query 一致性用例）、`docs/runlogs/c8_pytest.txt`、本证据包。  
  - **接口**：TraceQueryService.list_traces(start_ts, end_ts, strategy_id=None, limit=100, offset=0) → list[TraceSummary]；audit_service.list_traces 仅委托上述接口。  
  - **测试**：保留并沿用 test_list_traces_partial_*；新增 test_audit_log_query_interface_matches_log_repository。
- **唯一有效封版声明**：本证据包所对应的实现版本（含上述变更影响面）为 C8 的**唯一有效封版版本**；此前任何「C8 已通过」的封版均被本版替代，以本版为准。审计者以本文档及本小节确定 C8 唯一有效封版及变更原因。
