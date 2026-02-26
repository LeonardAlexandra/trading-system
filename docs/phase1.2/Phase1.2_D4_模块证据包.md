# Phase1.2 D4 模块证据包：E2E-4 多笔回放可验证点

## 模块名称与目标

| 项目 | 内容 |
|------|------|
| 模块编号 | D4 |
| 模块名称 | E2E-4 多笔回放可验证点 |
| 目标 | 验证多笔回放 API 与审计查询界面与 1.2a 数据一致。 |

---

## 本模块涉及的变更文件清单（新增 / 修改 / 删除）

| 类型 | 路径 |
|------|------|
| 新增 | `tests/integration/test_phase12_d4_list_traces_verification.py` |
| 新增 | `docs/runlogs/d4_e2e4_list_traces_pytest.txt` |
| 新增 | `docs/Phase1.2_D4_模块证据包.md`（本文件） |

无修改：list_traces 与审计日志查询已由 C8 实现，本模块仅新增 D4 可验证点验收测试与证据包。

---

## 本模块的核心实现代码（关键函数或完整文件）

**无。** 本模块为可验证点定义，无代码变更。既有实现位于：

- **list_traces**：`src/services/audit_service.list_traces` → `TraceQueryService.list_traces`，返回 `List[TraceSummary]`；HTTP 暴露为 GET /api/audit/traces?from=&to=&strategy_id=&limit=&offset=，响应 `{"items": [TraceSummary.to_dict(), ...], "count": n}`。
- **审计查询界面**：GET /api/audit/logs?from=&to=&component=&level=&limit=&offset= 调用 `audit_service.query_logs`，内部仅使用 `LogRepository.query(created_at_from, created_at_to, component, level, ...)`，故筛选结果与 log 表一致。

---

## 本模块对应的测试用例与可复现实跑步骤

- **测试用例**：`tests/integration/test_phase12_d4_list_traces_verification.py`
  - `test_d4_list_traces_returns_list_trace_summary`：插入一条 decision（decision_order_map）在时间范围内，请求 GET /api/audit/traces?from=&to=&limit=100，断言 200、body.items 为数组、每条含 decision_id/trace_status/missing_nodes，且 trace_status ∈ {COMPLETE, PARTIAL, NOT_FOUND}、missing_nodes 为数组；并断言含本次插入的 decision_id。
  - `test_d4_audit_query_interface_matches_log_table`：写入若干 log（LogRepository.write），请求 GET /api/audit/logs?from=&to=&component=&level=AUDIT&limit=100，再以相同参数调用 LogRepository.query，断言 API 返回的 items 的 id 集合与 LogRepository.query 结果的 id 集合一致。
- **可复现步骤**：在项目根目录 `trading_system/` 下执行：  
  `python3 -m pytest tests/integration/test_phase12_d4_list_traces_verification.py -v`

---

## 测试命令与原始输出结果

**实际执行的命令：**

```bash
python3 -m pytest tests/integration/test_phase12_d4_list_traces_verification.py -v
```

**命令的真实输出：**

见 **`docs/runlogs/d4_e2e4_list_traces_pytest.txt`**。内容为完整 pytest 输出：2 collected，2 passed，约 0.56s。

---

## 与本模块 Acceptance Criteria / 可验证点的逐条对照说明

### 验收口径（交付包原文）

- list_traces 返回列表中的每条记录应符合要求，且与 1.2a 数据一致。
- 审计查询界面的筛选结果必须与 log 表的数据一致。

### 可验证点逐条对照

| 可验证点 | 结果 | 证据 |
|----------|------|------|
| list_traces 指定时间范围返回 list[TraceSummary] | YES | test_d4_list_traces_returns_list_trace_summary：指定 from/to 请求 GET /api/audit/traces，断言 200、items 为 list、每条含 decision_id、trace_status、missing_nodes，trace_status 为 COMPLETE/PARTIAL/NOT_FOUND 之一、missing_nodes 为 list；数据来源为 decision_order_map 等 1.2a 表，与 1.2a 数据一致。 |
| 审计查询界面筛选结果与 log 表一致 | YES | test_d4_audit_query_interface_matches_log_table：写入 log 后，以相同时间范围/component/level 调用 GET /api/audit/logs 与 LogRepository.query，断言两者返回的 id 集合相等，即界面（API）筛选结果与 log 表一致。 |

### 验收结论

- list_traces 指定时间范围返回 list[TraceSummary]，且与 1.2a 数据一致：**满足**（测试通过）。
- 审计查询界面筛选结果与 log 表一致：**满足**（API 仅用 LogRepository.query，测试断言 id 集合一致）。

---

**证据包完成。D4 E2E-4 多笔回放可验证点已逐条落实并可通过上述测试与 runlog 复现。**
