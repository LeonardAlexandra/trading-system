# Phase2.1 A7 证据包

## 模块名称与目标
- 模块：A7 AutoDisableMonitor — 异常触发自动熔断（B.2）
- 目标：实现 B.2 所规定的三种异常触发条件，触发时三步操作均执行：停用 active + 回滚 stable（若有）+ 写强告警审计。

## 修改/新增文件清单
- 新增：`src/phase21/auto_disable_monitor.py`

## 与规格逐条对照（B.2 异常条件）

| 触发条件 | 默认阈值 | 已实现 | 可配置覆盖 |
|---------|---------|--------|-----------|
| 连续亏损笔数 | 5 笔 | ✅ | ✅ AutoDisableConfig |
| 连续亏损金额 | 1000 | ✅ | ✅ AutoDisableConfig |
| 最大回撤 | 10% | ✅（cumulative PnL 峰谷回撤） | ✅ AutoDisableConfig |
| 健康检查失败 | db_ok / exchange_ok | ✅ | ✅ check_health=False 可关闭 |

### 触发后三步操作（B.2 写死，均执行）
| 步骤 | 操作 | 已实现 |
|------|------|--------|
| 1. 停用 | active → disabled | ✅ |
| 2. 回滚 | stable → active（若 stable 存在） | ✅ |
| 3. 告警 | 写 release_audit(action=AUTO_DISABLE, passed=False) | ✅ |

### 无 stable 时的边界行为（B.2）
- 无 stable：仅停用 active，不回滚，rolled_back_to=None：✅（测试 F9）

## 测试证据
- 测试 F3：5 笔连续亏损 → triggered, auto_disable, stable 回滚 ✅
- 测试 F9：无 stable 时熔断 → 仅 disabled，rolled_back_to=None ✅
- audit payload 包含：trigger_reason, detail, prev_active_param_version_id, rollback_target ✅

## 验收结论
- A7 验收通过（全套测试 374 passed, 0 failed）
