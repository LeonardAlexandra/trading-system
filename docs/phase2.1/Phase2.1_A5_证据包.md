# Phase2.1 A5 证据包

## 模块名称与目标
- 模块：A5 ReleaseGate 发布门禁状态机
- 目标：实现 candidate → approved → active 全路径，支持人工审批与风控护栏两种门禁类型，每次迁移写 release_audit。

## 修改/新增文件清单
- 新增：`src/phase21/release_gate.py`（ReleaseGate 状态机）
- 新增：`src/application/phase21_service.py`（应用层入口，封装事务边界）

## 与规格逐条对照（B.3 状态机）

### 状态迁移路径（写死）
| 迁移 | 方法 | gate_type | audit action | 已实现 |
|------|------|-----------|--------------|--------|
| → candidate | `submit_candidate` | MANUAL | SUBMIT_CANDIDATE | ✅ |
| candidate → approved | `confirm_manual` | MANUAL | APPLY | ✅ |
| candidate → approved | `risk_guard_approve` | RISK_GUARD | APPLY | ✅ |
| approved → active | `apply_approved` | MANUAL | APPLY | ✅ |
| active → stable | `mark_stable` | MANUAL | APPLY | ✅ |
| active → disabled (+ stable → active) | `rollback_to_stable` | MANUAL | ROLLBACK | ✅ |
| candidate/approved → disabled | `reject_candidate` | MANUAL | REJECT | ✅ |

### 禁止行为强制（B.3 写死）
- candidate 直接 apply_approved → StateTransitionError（测试 F5）：✅
- 非白名单参数 submit_candidate → ReleaseGateError（测试 F4）：✅
- 无 stable 时回滚 → ReleaseGateError（测试 F8）：✅

### release_audit 每步均写（G 节）
- 每次状态迁移均写 release_audit 记录：✅
- 记录字段：strategy_id, param_version_id, action, gate_type, passed, operator_or_rule_id, created_at, payload：✅

## 验收结论
- A5 验收通过（全套测试 374 passed, 0 failed）
