# Phase 2.2 A2 证据包：决策过程展示只读 API

**模块**: Phase 2.2 A2
**交付日期**: 2026-03-04
**验收状态**: ✅ 通过

---

## 一、变更文件清单

| 类型 | 文件路径 |
|------|----------|
| 新增 | `src/app/routers/bi.py`（A2 部分） |

## 二、核心实现代码

### 端点

```
GET /api/bi/decision_flow?decision_id=|signal_id=
GET /api/bi/decision_flow/list?from=&to=&strategy_id=&limit=&offset=
```

**数据来源**（写死）：
- `Phase 1.2: TraceQueryService` 只读（C2 追溯 API）

### 关键实现

```python
@router.get("/decision_flow")
async def get_decision_flow(decision_id=None, signal_id=None):
    if not decision_id and not signal_id:
        return _err(400, "需要提供 decision_id 或 signal_id")
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_decision_id(decision_id)
    if result.trace_status == TRACE_STATUS_NOT_FOUND:
        return _err(404, ...)  # 明确 404

@router.get("/decision_flow/list")
async def list_decision_flow(...):
    items = await audit_service.list_traces(session, ...)
    return {"items": [{"trace_status": ..., "missing_nodes": ...}]}
```

## 三、可复现实跑步骤

```bash
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p3_decision_flow_list_has_trace_status -v
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p9_decision_flow_not_found -v
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p10_decision_flow_missing_params -v
```

**测试结果**：3 passed

## 四、只读边界证据

- 仅调用 `TraceQueryService`（只读）和 `audit_service.list_traces`（只读）
- 无任何 `Evaluator.evaluate`、`Optimizer.suggest`、`ReleaseGate` 写接口调用
- `NOT_FOUND` 时返回 404，`PARTIAL` 时 `trace_status` 与 `missing_nodes` 明确返回
- 不在 BI 层生成「新解释」或「应该怎么做」

## 五、验收口径逐条对照

| 验收条目 | 状态 | 说明 |
|----------|------|------|
| 可查并展示决策过程（信号→理由→风控→执行） | ✅ | 通过 TraceQueryService，trace_dict 含完整链路 |
| PARTIAL/NOT_FOUND 时展示 trace_status、missing_nodes | ✅ | result.to_dict() 已含 missing_nodes；NOT_FOUND 返回 404 |
| 数据一致性：与 1.2 同条件追溯查询结果一致 | ✅ | 直接调用 TraceQueryService，无中间处理 |
| 只读：未调用发布/回滚/门禁/评估/学习接口 | ✅ | 代码审查：仅 TraceQueryService + list_traces |
| 不存在的 decision_id 返回 404 | ✅ | test_p9 通过 |
| 缺少参数返回 400 | ✅ | test_p10 通过 |

---

**证据包状态**: 完整 ✅
