# Phase2.1 A1 证据包（系统级可验收）

## 模块名称与目标
- 模块：A1. ReleaseGate 状态扩展（param_version / strategy_runtime_state，Phase 2.1 扩展）
- 目标：在 A1 允许范围内完成 `release_gate.status` 五态扩展，支持 upgrade/downgrade，可审计证明变更范围。

## 修改/新增文件清单
- 修改：`alembic/versions/023_phase21_a1_release_gate_status_expand.py`
- 修改：`docs/Phase2.1_A1_证据包.md`
- 修改：`docs/runlogs/phase21_a1_migration_verify.txt`
- 修改：`docs/runlogs/phase21_a1_db_before_after.txt`
- 修改：`docs/runlogs/phase21_a1_change_scope_git.txt`

## 唯一真理源逐条对照（A1 原文 -> 证据位置）
引用源：`docs/plan/Phase2.1_模块化开发交付包.md` 的 A1 条目。

1. 原文（Goal）：
   - `candidate | approved | active | stable | disabled`
   证据：
   - 迁移常量：`alembic/versions/023_phase21_a1_release_gate_status_expand.py` 中 `ALLOWED_STATES = ("candidate", "approved", "active", "stable", "disabled")`
   - DB after 结构：`docs/runlogs/phase21_a1_db_before_after.txt` 中 `[after] SELECT sql ...` 包含 `stable`，不包含 `rollback`

2. 原文（Scope）：
   - 仅在 2.1 侧扩展状态字段，不修改 2.0 表语义
   证据：
   - 变更路径证明：`docs/runlogs/phase21_a1_change_scope_git.txt` 中 `git diff --name-only HEAD` 仅出现 A1 允许范围文件

3. 原文（Strong Constraints）：
   - 迁移支持 upgrade/downgrade，不破坏已有表
   证据：
   - `docs/runlogs/phase21_a1_migration_verify.txt` 含 `alembic upgrade 022`、`alembic upgrade 023`、`alembic downgrade 022` 原始输出
   - before/after 结构完整输出：`docs/runlogs/phase21_a1_db_before_after.txt`

4. 原文（AC）：
   - upgrade/downgrade 无报错；状态字段可存储五态；文档明确 2.1 自有扩展
   证据：
   - 迁移原始输出：`docs/runlogs/phase21_a1_migration_verify.txt`
   - 字段与约束输出：`docs/runlogs/phase21_a1_db_before_after.txt`
   - 本证据包逐条映射章节

## 变更范围证明（基线 + HEAD diff）
原始输出：`docs/runlogs/phase21_a1_change_scope_git.txt`

- 基线步骤（为可审计 HEAD diff）：
  - `git add -A`
  - `git commit -m "baseline before Phase2.1 A1" || true`
- 范围命令（已执行并记录原始输出）：
  - `git status`
  - `git diff --name-only HEAD`
  - `git diff HEAD -- alembic/versions/023_phase21_a1_release_gate_status_expand.py`
  - `git diff HEAD -- docs/Phase2.1_A1_证据包.md`

## 未跨模块修改证明
- 命令：`git diff --name-only HEAD | rg "^(src/models/|src/repositories/)" || true`
- 原始输出位置：`docs/runlogs/phase21_a1_change_scope_git.txt`
- 结果：无输出（未修改 `models/` 与 `repositories/`）

## 数据库真实结构 before/after（完整输出）
原始输出：`docs/runlogs/phase21_a1_db_before_after.txt`

关键核验点：
- before 默认值：`'approved'`
- after 默认值：`'candidate'`
- after CHECK：`('candidate','approved','active','stable','disabled')`
- after 输出中不含 `rollback`

## 核心实现代码（A1）
文件：`alembic/versions/023_phase21_a1_release_gate_status_expand.py`

关键实现：
- `ALLOWED_STATES = ("candidate", "approved", "active", "stable", "disabled")`
- PostgreSQL ENUM 路径：`ALTER TYPE ... ADD VALUE IF NOT EXISTS`
- VARCHAR 路径：`CHECK status IN ('candidate','approved','active','stable','disabled')`
- 默认值：`candidate`
- `downgrade()` 保持可执行

## 命令与原始输出
1. 迁移验证：`docs/runlogs/phase21_a1_migration_verify.txt`
2. DB before/after：`docs/runlogs/phase21_a1_db_before_after.txt`
3. 变更范围与跨模块自检：`docs/runlogs/phase21_a1_change_scope_git.txt`

## 验收结论（A1）
- 五态严格为：`candidate | approved | active | stable | disabled`
- 默认值为 `candidate`
- `rollback` 已从迁移状态集合与 DB CHECK 中移除
- 迁移升级/降级可执行
- 变更范围可审计，且未跨模块
