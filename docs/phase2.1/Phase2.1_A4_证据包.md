# Phase2.1 A4 证据包

## 模块名称与目标
- 模块：A4 param_version 表创建 + Optimizer/Learner 服务
- 目标：
  1. 建立 `param_version` 表（migration 026），携带发布状态机五态字段 `release_state`。
  2. 实现 Optimizer（B.5：仅读 Phase 2.0 evaluation_report，仅产出白名单参数建议）。
  3. 写 `learning_audit` 审计记录（仅存 ID 引用，不存报告内容）。

## 修改/新增文件清单
- 新增：`alembic/versions/026_phase21_a4_param_version_table.py`
- 新增：`src/models/param_version.py`
- 新增：`src/models/release_audit.py`
- 新增：`src/models/learning_audit.py`
- 修改：`src/models/__init__.py`（注册三个新模型）
- 新增：`src/repositories/param_version_repository.py`
- 新增：`src/repositories/release_audit_repository.py`
- 新增：`src/repositories/learning_audit_repository.py`
- 新增：`src/phase21/__init__.py`
- 新增：`src/phase21/whitelist.py`（B.4 白名单唯一事实源）
- 新增：`src/phase21/optimizer.py`（T2.1-1 Optimizer/Learner）

## 与规格逐条对照

### param_version 表（C.1）
- `id (BIGINT PK)`：✅ 已实现
- `param_version_id (VARCHAR UNIQUE NOT NULL)`：✅ 已实现
- `strategy_id (VARCHAR NOT NULL)`：✅ 已实现
- `strategy_version_id (VARCHAR NOT NULL)`：✅ 已实现
- `params (JSONB NOT NULL)`：✅ 仅白名单参数
- `release_state (VARCHAR NOT NULL DEFAULT 'candidate')`：✅ 五态 + CHECK 约束
- `created_at / updated_at`：✅ 已实现

### Optimizer 约束（B.5）
- 输入仅为 Phase 2.0 evaluation_report（ID 引用）：✅
- 禁止扫描 trade/execution/decision_snapshot 表：✅（接口约束：仅接受 EvaluationReport 对象）
- 建议参数仅含白名单键（B.1/B.4）：✅（validate_params 强制校验）
- 写 learning_audit（仅 ID 引用，不含报告内容）：✅

### 白名单唯一事实源（B.4）
- `src/phase21/whitelist.py` 为单一事实源，代码/文档/测试均引用此处：✅
- 禁止文档白名单与代码不一致：✅（测试 F4 验证白名单拦截）

## 验收结论
- A4 验收通过（全套测试 374 passed, 0 failed）
