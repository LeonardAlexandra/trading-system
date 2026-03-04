# Phase2.1 A6 证据包

## 模块名称与目标
- 模块：A6 一键回滚（rollback_to_stable）
- 目标：将当前 active 版本脱离生效（→ disabled），将上一 stable 版本重新置为 active，写 release_audit(action=ROLLBACK)。

## 修改/新增文件清单
- 修改：`src/phase21/release_gate.py`（rollback_to_stable 方法）

## 与规格逐条对照（B.3 回滚语义）

| 规格要求 | 实现 | 已实现 |
|---------|------|--------|
| 回滚粒度：参数级（param_version） | rollback_to_stable 仅操作 param_version 表 | ✅ |
| active 脱离生效 | active → disabled | ✅ |
| stable → active | 上一 stable 版本重新置为 active | ✅ |
| 写 release_audit(action=ROLLBACK) | 含 from_active / to_active / reason payload | ✅ |
| 无 stable 时抛 ReleaseGateError | 测试 F8 验证 | ✅ |
| 回滚可查审计 | get_release_audit_log 可查 ROLLBACK 记录 | ✅ |

## 测试证据
- 测试 F2：v1→stable → v2(active) → rollback → v1 重新 active，v2→disabled，ROLLBACK audit 写入 ✅
- 测试 F8：无 stable 时 rollback 抛 ReleaseGateError ✅

## 验收结论
- A6 验收通过（全套测试 374 passed, 0 failed）
