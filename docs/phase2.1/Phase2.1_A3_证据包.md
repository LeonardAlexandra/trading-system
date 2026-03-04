# Phase2.1 A3 证据包

## 模块名称与目标
- 模块：A3 learning_audit 表创建
- 目标：按 A3/C.3 创建 `learning_audit`，仅存 `evaluation_report_id` 引用，不存 Phase2.0 报告内容。

## 修改/新增文件清单
- 修改：`alembic/versions/025_phase21_a3_learning_audit_table.py`
- 修改：`docs/Phase2.1_A3_证据包.md`
- 修改：`docs/runlogs/phase21_a3_migration_verify.txt`

## 实际执行命令
- `alembic upgrade 024`
- `alembic upgrade 025`
- `PRAGMA table_info(learning_audit)`
- `SELECT sql FROM sqlite_master WHERE type='table' AND name='learning_audit'`
- `SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='learning_audit' ORDER BY name`
- `alembic downgrade 024`

## 命令真实输出
- 原始输出文件：`docs/runlogs/phase21_a3_migration_verify.txt`

## 与 A3/C.3 字段逐条对照
- `id (BIGINT/UUID, PK)`：已实现 `id BIGINT PRIMARY KEY`。
- `strategy_id (string, NOT NULL)`：已实现，NOT NULL。
- `evaluation_report_id (string, NULLABLE)`：已实现，可空。
- `param_version_id_candidate (string, NULLABLE)`：已实现，可空。
- `suggested_params (JSONB, NULLABLE)`：已实现 `JSONB`，可空。
- `created_at (timestamptz, NOT NULL)`：迁移定义为 `sa.DateTime(timezone=True)`，NOT NULL，默认 `now()`。

## 索引对照
- 必需索引：
  - `idx_learning_audit_strategy_id`
  - `idx_learning_audit_created_at`
- 可选索引（已实现）：
  - `idx_learning_audit_evaluation_report_id`
  - `idx_learning_audit_param_version_id_candidate`

## 仅存 ID、不存 2.0 内容的边界说明
- 本表不包含 `evaluation_snapshot`、`suggestion_payload`、`param_version` 等内容型字段。
- `evaluation_report_id` 仅为字符串引用 ID。
- 建表 SQL 可见仅有 `evaluation_report_id` 引用字段，且无用于存放 2.0 报告内容的 JSONB 快照字段。

## 与 A3 Acceptance Criteria 逐条对照
- [x] 表结构正确
  - 证据：runlog 中 `PRAGMA table_info(learning_audit)` 与建表 SQL 完整输出。
- [x] 索引存在
  - 证据：runlog 中索引输出包含 `idx_learning_audit_strategy_id`、`idx_learning_audit_created_at`。
- [x] migrate 成功
  - 证据：runlog 中 `Running upgrade 024 -> 025`。
- [x] downgrade 成功
  - 证据：runlog 中 `Running downgrade 025 -> 024`。

## 验收结论
- A3 验收通过。
