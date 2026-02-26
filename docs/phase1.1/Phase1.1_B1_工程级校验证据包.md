# Phase1.1 B1 工程级校验证据包

**模块**：B1 - POST /strategy/{id}/resume（强校验恢复 + diff 标准公式）  
**真理源**：《Phase1.1 开发交付包》B1 条款，无增删改。

---

## 0. B1 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 对条款的理解（1 句话） |
|-----------|----------------------------------|------------------------|
| B1-01 | 实现 POST /strategy/{id}/resume；强校验：在恢复前执行明确的状态与一致性检查（如持仓是否已校正、风控是否通过、策略状态是否为 PAUSED 等） | 仅当强校验通过时允许恢复，否则返回 400 及 diff |
| B1-02 | 失败时：返回 HTTP 400，响应体包含标准化的「差异」信息（diff），格式固定 | 校验失败时必须返回 400，body 为 Phase1.1 diff 结构（code, checks, snapshot） |
| B1-03 | diff 标准公式：文档中明确定义 diff 的字段名、结构与示例；diff JSON 顶层结构（固定字段名，全部必须出现）：code, checks, snapshot | diff 格式固定，不得修改；可被自动化脚本解析 |
| B1-04 | 成功时：将策略状态置为可接收信号（如 RUNNING），并触发或记录 STRATEGY_RESUMED（由 C7 落库） | 恢复成功时更新状态为 RUNNING，并写入 STRATEGY_RESUMED 终态日志 |
| B1-05 | 恢复成功与 STRATEGY_RESUMED 终态日志必须在同一一致性边界内（同一事务或等价保证） | 状态更新与 STRATEGY_RESUMED 在同一事务内提交 |
| B1-06 | 对不存在的 strategy id 返回 404 或约定错误码 | 策略不存在时返回 404 |

---

## 3.1 目标校验矩阵（逐条覆盖 B1 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式（测试/脚本/命令） | 结果 |
|-----------|-------------------|------------------------|----------------------------|------|
| B1-01 | 强校验：state_is_paused、risk_passed | strategy_manager.py resume_strategy 内先查 state、再 full_check | test_b1_resume_check_failed_400_diff、test_b1_resume_paused_but_risk_fails_400、test_b1_resume_success_2xx_and_strategy_resumed | PASS |
| B1-02 | 失败时 400 + diff | resume.py post_resume 中 outcome==check_failed 时 return JSONResponse(400, content=diff) | test_b1_resume_check_failed_400_diff 断言 outcome==check_failed 且 diff 含 code/checks/snapshot | PASS |
| B1-03 | diff 结构 code, checks, snapshot | strategy_manager.py _build_resume_diff；RESUME_CHECK_FAILED_CODE, checks 项含 field/expected/actual/pass | test_b1_resume_check_failed_400_diff 断言 code、checks、snapshot 及 checks 项结构 | PASS |
| B1-04 | 成功时 RUNNING + STRATEGY_RESUMED | strategy_manager.py 持锁内 update_status_to_running + log_event_in_txn(STRATEGY_RESUMED) | test_b1_resume_success_2xx_and_strategy_resumed 断言 status==RUNNING 且存在 STRATEGY_RESUMED 记录 | PASS |
| B1-05 | 同事务 | resume_strategy 要求 session.in_transaction()，持锁内先 update 再 log_event_in_txn | 同一 session.begin() 内完成，C7 同事务约束 | PASS |
| B1-06 | 不存在返回 404 | resume.py outcome==not_found 时 return JSONResponse(404, ...) | test_b1_resume_not_found 断言 outcome==not_found | PASS |

---

## 3.2 关键实现快照（Code Snapshot）

### POST /strategy/{id}/resume 路由（404 / 400 / 200）

```python
# src/app/routers/resume.py（节选）
@router.post("/{id}/resume")
async def post_resume(id: str):
    strategy_id = id.strip()
    ...
    async with get_db_session() as session:
        async with session.begin():
            ...
            outcome, diff = await resume_strategy(session, strategy_id, ...)
    if outcome == "not_found":
        return JSONResponse(status_code=404, content={"detail": "strategy not found", ...})
    if outcome == "check_failed":
        return JSONResponse(status_code=400, content=diff)
    return JSONResponse(status_code=200, content={"status": "resumed", "strategy_id": strategy_id})
```

### 强校验与 diff 构建（标准公式）

```python
# src/execution/strategy_manager.py（节选）
def _build_resume_diff(strategy_id: str, current_status: str, checks: List[Dict]) -> Dict:
    return {
        "code": RESUME_CHECK_FAILED_CODE,
        "checks": checks,
        "snapshot": {"strategy_id": strategy_id, "status": current_status},
    }

# resume_strategy 内：state = get_by_strategy_id -> 无则 return ("not_found", None)
# check_state_paused = (current_status == STATUS_PAUSED)
# risk_result = await risk_manager.full_check(strategy_id, positions, risk_config_override)
# risk_passed = risk_result.get("passed", False)
# checks = [{"field": FIELD_STATE_IS_PAUSED, "expected": True, "actual": ..., "pass": ...}, ...]
# 若任一未通过 -> return ("check_failed", _build_resume_diff(...))
```

### 恢复成功：更新 RUNNING + 写 STRATEGY_RESUMED（同事务）

```python
# src/execution/strategy_manager.py（节选）
async with lock.use_lock(strategy_id) as acquired:
    if not acquired:
        return ("check_failed", diff)
    updated = await state_repo.update_status_to_running(strategy_id)
    ...
    await reconcile_log_repo.log_event_in_txn(
        strategy_id=strategy_id,
        event_type=STRATEGY_RESUMED,
        diff_snapshot=resumed_snapshot,
    )
    return ("ok", None)
```

---

## 3.3 测试与实跑输出（原始证据）

### pytest -q

```
........................................................................ [ 37%]
........................................................................ [ 75%]
...............................................                          [100%]
191 passed in 11.13s
```

### pytest -q tests/integration

```
104 passed in 6.41s
```

### B1 专项测试

```bash
pytest tests/integration/test_b1_resume.py -q -v
```

```
tests/integration/test_b1_resume.py::test_b1_resume_not_found PASSED
tests/integration/test_b1_resume.py::test_b1_resume_check_failed_400_diff PASSED
tests/integration/test_b1_resume.py::test_b1_resume_paused_but_risk_fails_400 PASSED
tests/integration/test_b1_resume.py::test_b1_resume_success_2xx_and_strategy_resumed PASSED
4 passed in 0.37s
```

---

## 3.4 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 恢复过程中的强校验是否完全按照 Phase1.1 要求执行？ | **是** | 强校验项：state_is_paused（策略状态为 PAUSED）、risk_passed（full_check 通过）；未通过不执行恢复 |
| diff 格式是否符合 Phase1.1 规定的结构？ | **是** | 顶层 code（RESUME_CHECK_FAILED）、checks（array of {field, expected, actual, pass}）、snapshot（strategy_id, status）；测试断言上述字段存在且可解析 |
| 恢复成功时，是否更新了策略状态并写入 STRATEGY_RESUMED 日志？ | **是** | update_status_to_running 后立即 log_event_in_txn(STRATEGY_RESUMED)，同事务；test_b1_resume_success 断言 DB 中 status=RUNNING 且存在 STRATEGY_RESUMED 记录 |
| 是否在校验失败时返回了标准 400 错误？ | **是** | outcome==check_failed 时路由返回 JSONResponse(400, content=diff)；服务层返回 diff 符合标准公式 |
| 是否存在残余风险？ | 有说明 | 路由层使用默认 RiskConfig()，与对账/挂起时使用的风控配置可能不一致时，resume 的 risk_passed 结果以当前传入的 risk_config_override 为准；生产环境可改为从配置或策略维度注入 risk_config。 |

---

## 3.5 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| src/repositories/strategy_runtime_state_repo.py | 新增 update_status_to_running | B1-04, B1-05 |
| src/execution/strategy_manager.py | 新增 resume_strategy、_build_resume_diff，强校验与 diff 标准、持锁内 RUNNING+STRATEGY_RESUMED | B1-01, B1-02, B1-03, B1-04, B1-05 |
| src/app/routers/resume.py | 新增 POST /strategy/{id}/resume，映射 outcome 为 404/400/200 | B1-01, B1-02, B1-06 |
| src/app/main.py | 注册 resume.router | B1 路由暴露 |
| tests/integration/test_b1_resume.py | B1/D4/D5 集成测试：not_found、check_failed+diff、success+STRATEGY_RESUMED | 全条款 |
| docs/Phase1.1_B1_工程级校验证据包.md | 本证据包 | 全条款 |

---

**验收结论**：B1 条款在校验矩阵中逐条覆盖；强校验按 Phase1.1 执行（state_is_paused、risk_passed）；恢复成功时状态更新为 RUNNING 并写入 STRATEGY_RESUMED；校验失败时返回 400 且 body 为标准 diff；证据包可复现（pytest 命令见 3.3）。
