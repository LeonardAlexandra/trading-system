# Phase1.2 D2 模块证据包：E2E-2 审计可验证点

## 模块名称与目标

| 项目 | 内容 |
|------|------|
| 模块编号 | D2 |
| 模块名称 | E2E-2 审计可验证点 |
| 目标 | 验证风控拒绝或执行失败时，审计日志可查且可按时间/组件/级别筛选。 |

---

## 本模块涉及的变更文件清单（新增 / 修改 / 删除）

| 类型 | 路径 |
|------|------|
| 新增 | `tests/integration/test_phase12_d2_audit_verification.py` |
| 新增 | `docs/runlogs/d2_e2e2_audit_pytest.txt` |
| 修改 | `docs/Phase1.2_D2_模块证据包.md`（本文件，E2E-2 审计可验证点证据包） |

---

## 本模块的核心实现代码（关键函数或完整文件）

**无。** 本模块为可验证点定义，不修改业务逻辑；仅新增测试用例验证既有能力：执行失败/风控拒绝时 execution_engine 通过既有 C3 路径写 LogRepository（AUDIT/ERROR），LogRepository.query 已支持按 created_at_from/created_at_to（即 start_ts/end_ts 语义）、component、level 筛选。实现位于既有 `src/repositories/log_repository.py`（query 方法）与 `src/execution/execution_engine.py`（_maybe_audit_failed、_maybe_error、_maybe_audit）。

---

## 本模块对应的测试用例与可复现实跑步骤

- **测试用例**：`tests/integration/test_phase12_d2_audit_verification.py`
  - `test_d2_audit_log_contains_failure_event`：触发一次执行失败（决策快照 save 抛异常）后，断言 LogRepository.query(level="AUDIT") 与 query(level="ERROR") 的并集中含该事件（event_type/component/message 与 execution_failed 或 decision_snapshot_save_failed 相关）。
  - `test_d2_audit_query_filter_by_time_component_level`：同上触发失败，再以 LogRepository.query(created_at_from, created_at_to, component="execution_engine", level="AUDIT"/"ERROR") 筛选，断言能筛出该事件；并验证 component/level 过滤生效（错误 component 或 level=INFO 不包含该 AUDIT/ERROR）。
- **可复现步骤**：在项目根目录 `trading_system/` 下执行：  
  `python3 -m pytest tests/integration/test_phase12_d2_audit_verification.py -v`

---

## 测试命令与原始输出结果

**实际执行的命令：**

```bash
python3 -m pytest tests/integration/test_phase12_d2_audit_verification.py -v
```

**命令的真实输出：**

见 **`docs/runlogs/d2_e2e2_audit_pytest.txt`**。内容为完整 pytest 输出：2 collected，2 passed，约 0.66s。

---

## 与本模块 Acceptance Criteria / 可验证点的逐条对照说明

### 验收口径（交付包原文）

- 触发风控拒绝或执行失败后，LogRepository.query(level=AUDIT 或 ERROR) 应包含该事件。
- query 按 start_ts, end_ts, component, level 筛选结果应正确。

### 可验证点逐条对照

| 可验证点 | 结果 | 证据 |
|----------|------|------|
| 触发一次风控拒绝或执行失败后，LogRepository.query(level=AUDIT 或 ERROR) 含该事件 | YES | test_d2_audit_log_contains_failure_event：触发决策快照 save 异常 → 执行 run_once → 调用 LogRepository.query(level="AUDIT") 与 query(level="ERROR")，断言返回列表中至少一条为 execution_engine 的 execution_failed/decision_snapshot_save_failed 相关记录。 |
| query 按 start_ts, end_ts, component, level 可筛选出对应记录 | YES | test_d2_audit_query_filter_by_time_component_level：同上触发失败后，以 created_at_from/created_at_to（与 start_ts/end_ts 语义一致）、component="execution_engine"、level="AUDIT" 或 "ERROR" 调用 query，断言结果含该事件；并断言 component="other_component" 及 level="INFO" 筛选后不包含该 AUDIT/ERROR 记录，证明按 component、level 筛选正确。 |

### 验收结论

- 触发执行失败后，LogRepository.query(level=AUDIT 或 ERROR) 含该事件：**满足**（测试断言通过）。
- query 按 start_ts/end_ts（created_at_from/created_at_to）、component、level 筛选结果正确：**满足**（测试断言通过）。

---

**证据包完成。D2 E2E-2 审计可验证点已逐条落实并可通过上述测试与 runlog 复现。**
