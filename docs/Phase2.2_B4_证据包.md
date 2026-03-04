# Phase 2.2 B4 证据包：权限与脱敏

**模块**: Phase 2.2 B4
**交付日期**: 2026-03-04
**验收状态**: ✅ 通过

---

## 一、变更文件清单

| 类型 | 文件路径 |
|------|----------|
| 新增 | `src/app/routers/bi.py`（B4 脱敏逻辑） |

## 二、权限模型（写死）

### 当前约定：单租户 / 内网使用

本 Phase 不实现多租户。明确声明：

> **当前为单租户/内网使用，不实现认证层。**

权限角色约定（已文档化，当前不强制认证）：

| 角色 | 可查看范围 | 写权限 |
|------|-----------|--------|
| viewer | 统计、曲线、决策过程、版本/评估历史、门禁历史 | 无 |
| operator | viewer 基础上 + release_audit payload 完整字段 | 无 |
| admin | 所有展示数据 | 无（BI 不得成为控制面） |

**所有角色均不可通过 BI 触发状态变更。**

## 三、必须脱敏字段（写死）

| 字段 | 处理方式 | 实现位置 |
|------|----------|----------|
| `operator_or_rule_id` | 替换为布尔字段 `has_operator` | `bi.py:437-438` |
| API key / 交易所密钥 | 不在任何 BI 响应中出现 | 原始 ORM 模型不含此字段 |
| `okx secret` | 不在任何 BI 响应中出现 | 原始 ORM 模型不含此字段 |

### 脱敏实现代码

```python
# bi.py → get_release_audit → items 列表
{
    "id": r.id,
    "action": r.action,
    "gate_type": r.gate_type,
    "passed": r.passed,
    # B4 脱敏：operator_or_rule_id 仅展示是否存在，不暴露内部规则 ID
    "has_operator": r.operator_or_rule_id is not None,
    # 注意：无 "operator_or_rule_id" 字段
}
```

## 四、可复现实跑步骤

```bash
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p6_release_audit_operator_masked -v
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p12_release_audit_no_operator -v
```

**测试内容**：
- `test_p6`: `"operator_or_rule_id" not in item` ✅，`"op-secret-123" not in str(item)` ✅，`has_operator is True` ✅
- `test_p12`: `has_operator is False`（当 operator 为 None 时）✅

**测试结果**：2 passed

## 五、验收口径逐条对照

| 验收条目 | 状态 | 说明 |
|----------|------|------|
| 最小权限模型已文档化；各角色可访问范围符合 D.4 | ✅ | 本证据包第二节已写死文档化 |
| 必须脱敏字段在展示/导出中已脱敏 | ✅ | test_p6/p12 验证 operator_or_rule_id 脱敏 |
| 多租户或「当前单租户/内网使用」已明确表述 | ✅ | bi.py 文件头注释 + 本证据包明确写死 |
| 无任何角色可通过 BI 触发状态变更 | ✅ | test_p7 验证 GET-only；test_p13 页面无变更按钮 |

---

**证据包状态**: 完整 ✅
