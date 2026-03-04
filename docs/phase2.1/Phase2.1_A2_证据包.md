# Phase2.1 A2 证据包

## 模块名称与目标
- 模块：A2 release_audit 表创建
- 目标：按 C.2 严格创建 `release_audit` 字段与索引，迁移可回滚。

## 修改/新增文件清单
- 修改：`alembic/versions/024_phase21_a2_release_audit_table.py`
- 修改：`docs/Phase2.1_A2_证据包.md`
- 修改：`docs/runlogs/phase21_a2_migration_verify.txt`

## 实际执行命令
- `alembic upgrade 023`
- `alembic upgrade 024`
- `PRAGMA table_info(release_audit)`
- `SELECT sql FROM sqlite_master WHERE type='table' AND name='release_audit'`
- `SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='release_audit' ORDER BY name`
- `alembic downgrade 023`

## 命令真实输出
- 原始输出文件：`docs/runlogs/phase21_a2_migration_verify.txt`

### PRAGMA 完整输出
```txt
(0, 'id', 'BIGINT', 1, None, 1)
(1, 'strategy_id', 'VARCHAR(255)', 1, None, 0)
(2, 'param_version_id', 'VARCHAR(255)', 1, None, 0)
(3, 'action', 'VARCHAR(32)', 1, None, 0)
(4, 'gate_type', 'VARCHAR(32)', 0, None, 0)
(5, 'passed', 'BOOLEAN', 0, None, 0)
(6, 'operator_or_rule_id', 'VARCHAR(255)', 0, None, 0)
(7, 'created_at', 'DATETIME', 1, 'CURRENT_TIMESTAMP', 0)
(8, 'payload', 'JSON', 0, None, 0)
```

### 建表 SQL 完整输出
```txt
("CREATE TABLE release_audit (\n\tid BIGINT NOT NULL, \n\tstrategy_id VARCHAR(255) NOT NULL, \n\tparam_version_id VARCHAR(255) NOT NULL, \n\taction VARCHAR(32) NOT NULL, \n\tgate_type VARCHAR(32), \n\tpassed BOOLEAN, \n\toperator_or_rule_id VARCHAR(255), \n\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tpayload JSON, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_release_audit_action CHECK (action IN ('APPLY','ROLLBACK','AUTO_DISABLE','SUBMIT_CANDIDATE','REJECT')), \n\tCONSTRAINT ck_release_audit_gate_type CHECK (gate_type IS NULL OR gate_type IN ('MANUAL','RISK_GUARD'))\n)",)
```

### 索引 SQL 输出
```txt
('idx_release_audit_created_at', 'CREATE INDEX idx_release_audit_created_at ON release_audit (created_at)')
('idx_release_audit_param_version_id', 'CREATE INDEX idx_release_audit_param_version_id ON release_audit (param_version_id)')
('idx_release_audit_strategy_id', 'CREATE INDEX idx_release_audit_strategy_id ON release_audit (strategy_id)')
('sqlite_autoindex_release_audit_1', None)
```

## 与 C.2 字段逐条对照
- `id`：BIGINT PK，已实现。
- `strategy_id`：VARCHAR NOT NULL，已实现。
- `param_version_id`：VARCHAR NOT NULL，已实现。
- `action`：仅允许 `APPLY | ROLLBACK | AUTO_DISABLE | SUBMIT_CANDIDATE | REJECT`，已通过 CHECK 约束实现。
- `gate_type`：允许 `MANUAL | RISK_GUARD`（可空），已通过 CHECK 约束实现。
- `passed`：BOOLEAN 可空，已实现。
- `operator_or_rule_id`：VARCHAR 可空，已实现。
- `created_at`：TIMESTAMP 非空默认 `now()`（SQLite 显示 `CURRENT_TIMESTAMP`），已实现。
- `payload`：JSON 可空，已实现。

## 与 A2 Acceptance Criteria 逐条对照
- [x] 迁移可重复执行且可回滚。
  - 证据：runlog 中 `Running upgrade 023 -> 024` 与 `Running downgrade 024 -> 023`。
- [x] 表中存在 C.2 全部字段及必要索引。
  - 证据：PRAGMA、建表 SQL、索引 SQL 完整输出。
- [x] 文档明确 action 枚举及必写约定。
  - 证据：本证据包字段对照中明确 action 枚举；A2 迁移内 `ck_release_audit_action` 约束与 C.2 一致。

## 验收结论
- A2 修复后通过。
