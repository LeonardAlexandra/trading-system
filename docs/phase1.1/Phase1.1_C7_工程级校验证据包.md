# Phase1.1 C7 工程级校验证据包

**模块**：C7 - STRATEGY_RESUMED 终态日志（恢复成功时的终态记录）  
**真理源**：《Phase1.1 开发交付包》C7 条款，无增删改。

---

## 0. C7 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 对条款的理解（1 句话） |
|-----------|----------------------------------|------------------------|
| C7-01 | 在 B1 POST /strategy/{id}/resume 强校验通过并执行恢复时，在同一事务或一致性边界内写入 STRATEGY_RESUMED 终态日志 | 恢复成功后必须写入 STRATEGY_RESUMED，且与恢复在同一事务内 |
| C7-02 | 日志内容：至少包含策略 ID、恢复时间、触发方式（如 API）、可选恢复前状态摘要（如上次 PAUSED 原因） | 日志记录策略 ID、恢复时间、触发方式及可选的恢复前挂起原因 |
| C7-03 | 与 B1 的衔接：仅当恢复成功并提交后写入，失败则不写 | 仅在 B1 强校验恢复成功后才写入，失败不写 |
| C7-04 | STRATEGY_RESUMED 必须在恢复成功并提交的同一事务或等价边界内写入；不允许在未执行恢复或强校验未通过时写入 | 日志写入与状态更新必须在同一事务内；未恢复成功绝不写入 |
| C7-05 | 以数据库中的 STRATEGY_RESUMED 终态日志为准；恢复是否发生以该记录及策略状态为准 | 终态日志为恢复发生的审计源，字段格式与 Phase1.1/表结构一致 |
| C7-06 | 交付物：STRATEGY_RESUMED 终态日志的写入逻辑及字段定义；与 B1 的衔接：在恢复成功分支内调用写入 | 写入逻辑在 B1 恢复成功分支内，字段含 trigger、previous_status、可选 previous_paused_* |

---

## 3.1 目标校验矩阵（逐条覆盖 C7 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式（测试/脚本/命令） | 结果 |
|-----------|-------------------|------------------------|----------------------------|------|
| C7-01 | 恢复成功时同事务内写入 STRATEGY_RESUMED | strategy_manager.py resume_strategy 持锁内 update_status_to_running 后 log_event_in_txn(STRATEGY_RESUMED) | test_c7_resume_success_writes_strategy_resumed_same_transaction、test_b1_resume_success_2xx_and_strategy_resumed | PASS |
| C7-02 | 日志含策略 ID、恢复时间、触发方式、可选恢复前原因 | 行上 strategy_id、created_at；diff_snapshot 含 trigger/previous_status/previous_paused_reason_code/previous_paused_message | test_c7_resumed_log_contains_trigger_and_previous_paused_reason 断言 trigger、previous_status、previous_paused_reason_code | PASS |
| C7-03 | 仅恢复成功写入，失败不写 | resume_strategy 仅在 outcome 成功分支内调用 log_event_in_txn(STRATEGY_RESUMED)；check_failed/not_found 不写 | test_b1_resume_check_failed、test_b1_resume_not_found 无 STRATEGY_RESUMED；test_b1_resume_success 有 | PASS |
| C7-04 | 同事务；未恢复成功不写 | session.in_transaction() 要求；写 STRATEGY_RESUMED 与 update_status_to_running 同锁内、同 session | test_c7_resume_success_writes_strategy_resumed_same_transaction 验证同事务内写入 | PASS |
| C7-05 | 以 DB 终态日志为准，字段符合定义 | position_reconcile_log 表 event_type=STRATEGY_RESUMED，diff_snapshot 为 JSON（trigger, previous_status, previous_paused_*） | test_c7 解析 diff_snapshot 断言字段存在且格式正确 | PASS |
| C7-06 | 写入逻辑在 B1 恢复成功分支内 | strategy_manager.resume_strategy 在持锁且 update 成功后调用 _build_resumed_snapshot 与 log_event_in_txn | 代码审查：仅 "ok" 路径写 STRATEGY_RESUMED | PASS |

---

## 3.2 关键实现快照（Code Snapshot）

### 恢复成功后写入 STRATEGY_RESUMED（与状态更新同事务）

```python
# src/execution/strategy_manager.py（节选）
async with lock.use_lock(strategy_id) as acquired:
    if not acquired:
        return ("check_failed", diff)
    updated = await state_repo.update_status_to_running(strategy_id)
    if not updated:
        raise RuntimeError(...)
    # C7：STRATEGY_RESUMED 终态日志内容至少含策略 ID（行上）、恢复时间（created_at）、触发方式、可选恢复前挂起原因
    resumed_snapshot = await _build_resumed_snapshot(strategy_id, reconcile_log_repo)
    await reconcile_log_repo.log_event_in_txn(
        strategy_id=strategy_id,
        event_type=STRATEGY_RESUMED,
        diff_snapshot=resumed_snapshot,
    )
    return ("ok", None)
```

### 恢复前挂起原因与恢复时间、触发方式（C7 字段）

```python
# _build_resumed_snapshot：diff_snapshot 含 trigger、previous_status，可选 previous_paused_reason_code、previous_paused_message（来自最近 STRATEGY_PAUSED）
async def _build_resumed_snapshot(strategy_id: str, reconcile_log_repo: PositionReconcileLogRepository) -> str:
    payload = {"trigger": "API", "previous_status": STATUS_PAUSED}
    try:
        logs = await reconcile_log_repo.list_by_strategy(strategy_id, limit=50)
        for log in logs:
            if getattr(log, "event_type", None) == STRATEGY_PAUSED and getattr(log, "diff_snapshot", None):
                data = json.loads(log.diff_snapshot.strip())
                if isinstance(data, dict):
                    payload["previous_paused_reason_code"] = data.get("reason_code")
                    payload["previous_paused_message"] = (data.get("message") or "")[:500]
                break
    except Exception:
        pass
    return json.dumps(payload, ensure_ascii=False)
```

- **策略 ID**：行字段 `strategy_id`。  
- **恢复时间**：行字段 `created_at`（server_default=func.now()）。  
- **触发方式**：diff_snapshot 中 `trigger: "API"`。  
- **恢复前状态摘要**：diff_snapshot 中 `previous_status`、可选 `previous_paused_reason_code`、`previous_paused_message`（来自最近一条 STRATEGY_PAUSED 的 diff_snapshot）。

### 事务边界保证

- `resume_strategy` 要求 `session.in_transaction()`；写 STRATEGY_RESUMED 与 `update_status_to_running` 在同一 `session.begin()` 与同一 `lock.use_lock` 内，任一步异常由调用方事务回滚。

---

## 3.3 测试与实跑输出（原始证据）

### pytest -q

```
........................................................................ [ 37%]
........................................................................ [ 74%]
.................................................                        [100%]
193 passed in 11.87s
```

### pytest -q tests/integration

```
106 passed in 6.00s
```

### C7 专项测试

```bash
pytest tests/integration/test_c7_strategy_resumed_log.py -q -v
```

```
tests/integration/test_c7_strategy_resumed_log.py::test_c7_resume_success_writes_strategy_resumed_same_transaction PASSED
tests/integration/test_c7_strategy_resumed_log.py::test_c7_resumed_log_contains_trigger_and_previous_paused_reason PASSED
2 passed in 0.12s
```

---

## 3.4 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否每次恢复成功后都写入了 STRATEGY_RESUMED 终态日志？ | **是** | resume_strategy 在 update_status_to_running 成功后必调用 log_event_in_txn(STRATEGY_RESUMED, diff_snapshot=...)；无其他成功出口 |
| 是否记录了恢复前挂起的原因？ | **是** | diff_snapshot 由 _build_resumed_snapshot 构建，在存在最近 STRATEGY_PAUSED 时写入 previous_paused_reason_code、previous_paused_message；无 PAUSED 时仍含 trigger、previous_status |
| 恢复日志与状态更新是否在同一事务内提交？ | **是** | 同一 session、同一 lock 块内先 update_status_to_running 再 log_event_in_txn；resume_strategy 要求 session.in_transaction() |
| 是否存在残余风险？ | 有说明 | 若 list_by_strategy 或解析 STRATEGY_PAUSED 的 diff_snapshot 异常，_build_resumed_snapshot 内 try/except 会吞掉，此时 diff_snapshot 仅含 trigger 与 previous_status，仍满足「至少含策略 ID、恢复时间、触发方式」；可选恢复前原因可能缺失。 |

---

## 3.5 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| src/execution/strategy_manager.py | 新增 _build_resumed_snapshot（含恢复前挂起原因），恢复成功分支内写 STRATEGY_RESUMED 时使用 | C7-01, C7-02, C7-04, C7-06 |
| tests/integration/test_c7_strategy_resumed_log.py | C7 集成测试：恢复成功必写 STRATEGY_RESUMED、同事务、diff_snapshot 含 trigger/previous_status/previous_paused_reason_code | C7-01, C7-02, C7-05 |
| docs/Phase1.1_C7_工程级校验证据包.md | 本证据包：条款表、校验矩阵、实现快照、测试输出、回归声明、变更清单 | 全条款 |

---

**验收结论**：C7 条款在校验矩阵中逐条覆盖；恢复成功后必写 STRATEGY_RESUMED；日志字段与 Phase1.1 定义一致（策略 ID、恢复时间、触发方式、可选恢复前原因）；与策略状态更新在同一事务内提交；证据包可复现（pytest 命令见 3.3）。
