# Phase 2.2 B2 证据包：门禁/回滚/自动停用历史展示只读 API

**模块**: Phase 2.2 B2
**交付日期**: 2026-03-04
**验收状态**: ✅ 通过

---

## 一、变更文件清单

| 类型 | 文件路径 |
|------|----------|
| 新增 | `src/app/routers/bi.py`（B2 部分） |

## 二、核心实现代码

### 端点

```
GET /api/bi/release_audit?strategy_id=&from=&to=&limit=
```

**数据来源**（写死）：
- `Phase 2.1: release_audit` 只读查询

### 关键实现

```python
@router.get("/release_audit")
async def get_release_audit(strategy_id=None, from_=None, to=None, limit=50):
    async with get_db_session() as session:
        stmt = select(ReleaseAudit)
        # 只读查询
    return {
        "items": [{
            "action": r.action,
            "gate_type": r.gate_type,
            "passed": r.passed,
            # B4 脱敏：operator_or_rule_id 仅展示是否存在，不暴露内部规则 ID
            "has_operator": r.operator_or_rule_id is not None,
            # 注意：operator_or_rule_id 字段不出现在响应中
        }]
    }
```

### B4 脱敏设计

- `operator_or_rule_id` 是内部运营/规则标识，不得暴露给 BI 消费方
- 替换为布尔字段 `has_operator`：`True` 表示存在 operator，`False` 表示系统自动执行
- 验证：`"operator_or_rule_id" not in item` 且 `"op-secret-123" not in str(item)`

## 三、可复现实跑步骤

```bash
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p6_release_audit_operator_masked -v
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p12_release_audit_no_operator -v
```

**测试结果**：2 passed

## 四、只读边界证据

- 仅 `select(ReleaseAudit)` 只读查询，无任何写接口调用
- 不触发 `ReleaseGate.submit_candidate/confirm_manual/apply_approved/rollback_to_stable`
- 无「通过门禁」「执行回滚」等控制面入口
- 本接口不成为「第二个 ReleaseGate」

## 五、验收口径逐条对照

| 验收条目 | 状态 | 说明 |
|----------|------|------|
| 可查并展示门禁/回滚/自动停用历史列表 | ✅ | test_p6 通过；返回 action、gate_type、passed 等字段 |
| 数据一致性：与 2.1 release_audit 查询结果一致 | ✅ | 直接从 release_audit 表读取 |
| 只读：未调用发布/回滚/门禁接口 | ✅ | 代码审查：仅 select 查询 |
| 无任何可触发状态变更的调用 | ✅ | test_p7 验证 GET-only；test_p13 页面无变更按钮 |
| B4 脱敏：operator_or_rule_id 不暴露 | ✅ | test_p6/p12 验证字段替换为 has_operator |

---

**证据包状态**: 完整 ✅
