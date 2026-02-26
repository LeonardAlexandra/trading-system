# Phase1.2 D5 模块证据包：E2E-5 链路缺失可验证点

## 模块名称与目标

| 项目 | 内容 |
|------|------|
| 模块编号 | D5 |
| 模块名称 | E2E-5 链路缺失可验证点 |
| 目标 | 验证有 decision 无 execution、有 decision 无 decision_snapshot、有 execution 无 trade、signal_id 不存在等场景下，响应符合 B.2（200、trace_status=PARTIAL 或 NOT_FOUND、missing_nodes 正确、body 含已存在节点）。 |

---

## 本模块涉及的变更文件清单（新增 / 修改 / 删除）

| 类型 | 路径 |
|------|------|
| 新增 | `tests/integration/test_phase12_d5_trace_partial_verification.py` |
| 新增 | `docs/runlogs/d5_e2e5_trace_partial_pytest.txt` |
| 新增 | `docs/Phase1.2_D5_模块证据包.md`（本文件） |

无修改：trace 查询逻辑已由 C2 实现，本模块仅新增 D5 可验证点验收测试与证据包。

---

## 本模块的核心实现代码（关键函数或完整文件）

**无。** 本模块为可验证点定义，无代码变更。既有实现位于 `src/services/trace_query_service.py`（get_trace_by_decision_id、get_trace_by_signal_id）与 `src/app/routers/trace.py`（GET /api/trace/decision/{decision_id}、GET /api/trace/signal/{signal_id}），已满足 B.2：PARTIAL 时返回 200、missing_nodes 非空、body 含已存在节点；NOT_FOUND 时返回 404 或 200+trace_status=NOT_FOUND。

---

## 本模块对应的测试用例与可复现实跑步骤

- **测试用例**：`tests/integration/test_phase12_d5_trace_partial_verification.py`
  - `test_d5_decision_no_execution_partial_body_has_signal_decision_snapshot`：构造有 decision + signal + decision_snapshot，无 execution、无 trade；GET /api/trace/decision/{id} 断言 200、trace_status=PARTIAL、missing_nodes 含 execution 与 trade、body 含 signal/decision/decision_snapshot。
  - `test_d5_decision_no_snapshot_partial_missing_decision_snapshot`：构造有 decision + signal，无 decision_snapshot；断言 200、PARTIAL、missing_nodes 含 decision_snapshot。
  - `test_d5_execution_no_trade_partial_missing_trade`：构造有 decision + snapshot + execution（decision_order_map 置 exchange_order_id、status=FILLED），无 trade 表行；断言 200、PARTIAL、missing_nodes 含 trade。
  - `test_d5_nonexistent_signal_id_404_or_not_found`：GET /api/trace/signal/不存在的 signal_id；断言 404 或（200 且 trace_status=NOT_FOUND、无节点）。
  - `test_d5_partial_not_404_and_has_trace_status_missing_nodes`：构造有 decision 无 snapshot，断言非 404、body 必含 trace_status 与 missing_nodes（禁止部分数据存在时 404 或 body 空且无 trace_status/missing_nodes）。
- **可复现步骤**：在项目根目录 `trading_system/` 下执行：  
  `python3 -m pytest tests/integration/test_phase12_d5_trace_partial_verification.py -v`

---

## 测试命令与原始输出结果

**实际执行的命令：**

```bash
python3 -m pytest tests/integration/test_phase12_d5_trace_partial_verification.py -v
```

**命令的真实输出：**

见 **`docs/runlogs/d5_e2e5_trace_partial_pytest.txt`**。内容为完整 pytest 输出：5 collected，5 passed，约 0.88s。

---

## 与本模块 Acceptance Criteria / 可验证点的逐条对照说明

### 验收口径（交付包原文）

- 构造「有 decision 无 execution」时，get_trace 返回 200，trace_status=PARTIAL，missing_nodes 含 execution/trade，body 含 signal/decision/snapshot。
- 构造「有 decision 无 decision_snapshot」时，trace_status=PARTIAL，missing_nodes 含 decision_snapshot。
- 构造「有 execution 无 trade」时，trace_status=PARTIAL，missing_nodes 含 trade。
- 构造「不存在的 signal_id」时，返回 404 或 200 + trace_status=NOT_FOUND，并无节点。
- 禁止部分数据存在时返回 404 或 body 为空且无 trace_status、missing_nodes。

### 可验证点逐条对照

| 可验证点 | 结果 | 证据 |
|----------|------|------|
| 有 decision 无 execution：200，PARTIAL，missing 含 execution/trade，body 含 signal/decision/snapshot | YES | test_d5_decision_no_execution_partial_body_has_signal_decision_snapshot：插入 signal+decision+decision_snapshot，不写 execution/trade；GET /api/trace/decision/{id} 断言 200、trace_status=PARTIAL、missing_nodes 含 execution 与 trade、body.signal/decision/decision_snapshot 非空。 |
| 有 decision 无 decision_snapshot：PARTIAL，missing 含 decision_snapshot | YES | test_d5_decision_no_snapshot_partial_missing_decision_snapshot：插入 signal+decision，不写 decision_snapshot；断言 200、PARTIAL、missing_nodes 含 decision_snapshot。 |
| 有 execution 无 trade：PARTIAL，missing 含 trade | YES | test_d5_execution_no_trade_partial_missing_trade：插入 decision+snapshot，将 decision_order_map 置为 FILLED+exchange_order_id，不写 trade 表；断言 200、PARTIAL、missing_nodes 含 trade。 |
| 不存在的 signal_id：404 或 200+NOT_FOUND，并无节点 | YES | test_d5_nonexistent_signal_id_404_or_not_found：GET /api/trace/signal/不存在的 id；断言 status_code 为 404 或（200 且 trace_status=NOT_FOUND 且无有效节点）。 |
| 禁止部分存在时 404 或 body 空且无 trace_status、missing_nodes | YES | test_d5_partial_not_404_and_has_trace_status_missing_nodes：有 decision 无 snapshot 时断言非 404、body 含 trace_status 与 missing_nodes 且为 PARTIAL。 |

### 验收结论

- 上述五条可验证点均通过测试，get_trace 在链路缺失场景下符合 B.2：200、trace_status=PARTIAL 或 NOT_FOUND、missing_nodes 正确、body 含已存在节点；不存在的 signal_id 为 404 或 200+NOT_FOUND；部分数据存在时不返回 404 且 body 必含 trace_status、missing_nodes。**满足。**

---

**证据包完成。D5 E2E-5 链路缺失可验证点已逐条落实并可通过上述测试与 runlog 复现。**
