# Phase2.1 A1 证据包（系统级可验收）

## 模块名称与目标
- 模块：A1. ReleaseGate 状态扩展（param_version / strategy_runtime_state，Phase 2.1 扩展）
- 目标：在 A1 允许范围内扩展 `release_gate.status` 五态并保证迁移可升级/可降级。
- 五态明确为：`candidate | approved | active | stable | disabled`。
- 明确不存在：`rollback`。

## 修改/新增文件清单
- 修改：`alembic/versions/023_phase21_a1_release_gate_status_expand.py`
- 修改：`docs/Phase2.1_A1_证据包.md`
- 修改：`docs/runlogs/phase21_a1_baseline_git.txt`
- 修改：`docs/runlogs/phase21_a1_migration_verify.txt`
- 修改：`docs/runlogs/phase21_a1_db_before_after.txt`
- 修改：`docs/runlogs/phase21_a1_change_scope_git.txt`

## 实际执行命令
1. 基线可审计命令（写入 `docs/runlogs/phase21_a1_baseline_git.txt`）：
   - `git status`
   - `git add -A`
   - `git commit -m "baseline before Phase2.1 A1" || true`
   - `git log --oneline -5`
2. 迁移验证命令（写入 `docs/runlogs/phase21_a1_migration_verify.txt`）：
   - `alembic upgrade 022`
   - `alembic upgrade 023`
   - `alembic downgrade 022`
3. DB 结构 before/after 命令（写入 `docs/runlogs/phase21_a1_db_before_after.txt`）：
   - `PRAGMA table_info(release_gate);`
   - `SELECT sql FROM sqlite_master WHERE name='release_gate';`
   - 分别在 upgrade 前后执行
4. 变更范围命令（写入 `docs/runlogs/phase21_a1_change_scope_git.txt`）：
   - `git status`
   - `git diff --name-only HEAD`
   - `git diff HEAD -- alembic/versions/023_phase21_a1_release_gate_status_expand.py`
   - `git diff HEAD -- docs/Phase2.1_A1_证据包.md`
   - `git diff --name-only HEAD | rg "^(src/|tests/|config/)" || true`

## 命令真实输出（原始）
- 基线输出：`docs/runlogs/phase21_a1_baseline_git.txt`
- 迁移输出：`docs/runlogs/phase21_a1_migration_verify.txt`
- DB before/after 输出：`docs/runlogs/phase21_a1_db_before_after.txt`
- 范围证明输出：`docs/runlogs/phase21_a1_change_scope_git.txt`

## 唯一真理源逐条对照（A1）
来源：`docs/plan/Phase2.1_模块化开发交付包.md` A1 条目。

1. A1 五态：`candidate | approved | active | stable | disabled`
- 证据片段：
  - `phase21_a1_migration_verify.txt` 中 `after_upgrade_release_gate_sql= ... CHECK ... ('candidate','approved','active','stable','disabled')`
  - `phase21_a1_db_before_after.txt` 中 `[after] SELECT sql ...` 同样包含 `stable`
  - 同两份输出均不含 `rollback` 于允许集合

2. 默认值为 `candidate`
- 证据片段：
  - `phase21_a1_migration_verify.txt` 中 `after_upgrade_table_info` 行：`(1, 'status', 'VARCHAR(20)', 1, "'candidate'", 0)`
  - `phase21_a1_db_before_after.txt` 中 `[after] PRAGMA table_info(release_gate)` 同样显示默认值 `candidate`

3. 迁移支持 upgrade/downgrade
- 证据片段：
  - `phase21_a1_migration_verify.txt` 中：
    - `Running upgrade 021 -> 022`
    - `Running upgrade 022 -> 023`
    - `Running downgrade 023 -> 022`

4. Phase2.1 自有扩展，不改变 Phase2.0 语义
- 证据片段：
  - `alembic/versions/023_phase21_a1_release_gate_status_expand.py` 注释：
    - `Phase2.1 自有扩展：仅调整 release_gate.status 的允许集合与默认值，不触碰 Phase2.0 语义。`
  - `phase21_a1_change_scope_git.txt` 中 `git diff --name-only HEAD` 仅出现 A1 范围文件。

## 与 A1 Acceptance Criteria 逐条对照
- AC1：迁移可重复执行（upgrade/downgrade 无报错）
  - 证据：`docs/runlogs/phase21_a1_migration_verify.txt` 片段 `Running upgrade 022 -> 023`、`Running downgrade 023 -> 022`
- AC2：存在可存储五态的状态字段
  - 证据：`docs/runlogs/phase21_a1_db_before_after.txt` `[after] SELECT sql ... CHECK (status IN ('candidate','approved','active','stable','disabled'))`
- AC3：明确为 Phase2.1 扩展，未改 Phase2.0 语义
  - 证据：迁移文件注释 + `docs/runlogs/phase21_a1_change_scope_git.txt` 的路径范围输出

## 跨模块修改自检
- 检查命令：`git diff --name-only HEAD | rg "^(src/|tests/|config/)" || true`
- 原始输出：`docs/runlogs/phase21_a1_change_scope_git.txt`
- 结果：无输出（未触发 `src/` `tests/` `config/` 路径变更）

## 验收结论
- A1 验收通过：五态为 `candidate/approved/active/stable/disabled`，默认值 `candidate`，不存在 `rollback`，迁移 upgrade/downgrade 可执行，且变更范围可审计。
