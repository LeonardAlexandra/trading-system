# Phase1.2 D6 模块证据包：E2E-6 决策快照写入失败可验证点

## 模块名称与目标

| 项目 | 内容 |
|------|------|
| 模块编号 | D6 |
| 模块名称 | E2E-6 决策快照写入失败可验证点 |
| 目标 | 验证决策快照写入失败时，不产出 TradingDecision、触发强告警、写 ERROR 日志、拒绝本次决策；禁止静默放行。 |

---

## 本模块涉及的变更文件清单（新增 / 修改 / 删除）

| 类型 | 路径 |
|------|------|
| 新增 | `tests/integration/test_phase12_d6_snapshot_failure_verification.py` |
| 新增 | `docs/runlogs/d6_e2e6_snapshot_failure_pytest.txt` |
| 新增 | `docs/Phase1.2_D6_模块证据包.md`（本文件） |

无修改：决策快照写入失败时的处理逻辑已存在于 execution_engine（try/except save → alert_callback、_maybe_error、FAILED 状态、_maybe_audit_failed），本模块仅新增 D6 可验证点验收测试与证据包。

---

## 本模块的核心实现代码（关键函数或完整文件）

**无。** 本模块为可验证点定义，无代码变更。既有实现位于 `src/execution/execution_engine.py`：在 `_execute_one_impl` 内 `await self._snapshot_repo.save(snapshot)` 的 try/except 中，捕获异常后调用 `self._alert_callback(decision_id, strategy_id, err_msg)`、`await self._maybe_error(...)`（写 ERROR 日志，含 decision_id/strategy_id/reason）、`event_repo.append_event(..., FINAL_FAILED, status=FAILED, reason_code="DECISION_SNAPSHOT_SAVE_FAILED", ...)`、`_persist_exception_status(..., FAILED, ...)`、`await self._maybe_audit_failed(...)`（写 AUDIT），并 `return {"status": "failed", "reason_code": "DECISION_SNAPSHOT_SAVE_FAILED"}`，不进入下单/成交路径，故不产生 trade/order。

---

## 本模块对应的测试用例与可复现实跑步骤

- **测试用例**：`tests/integration/test_phase12_d6_snapshot_failure_verification.py::test_d6_snapshot_save_failure_no_trade_failed_log_alert`
  - 步骤：Webhook 创建 decision → mock `DecisionSnapshotRepository.save` 抛异常 → `run_once(WorkerConfig.from_env())` → 断言：decision_order_map.status=FAILED；trade 表无该 decision_id 记录；log 表存在 ERROR 或 AUDIT，且 message 含 decision_id 或 strategy_id，且 event_type/message 与 decision_snapshot 失败相关（decision_snapshot_save_failed / execution_failed / DECISION_SNAPSHOT_SAVE_FAILED）。
- **可复现步骤**：在项目根目录 `trading_system/` 下执行：  
  `python3 -m pytest tests/integration/test_phase12_d6_snapshot_failure_verification.py -v`

---

## 测试命令与原始输出结果

**实际执行的命令：**

```bash
python3 -m pytest tests/integration/test_phase12_d6_snapshot_failure_verification.py -v
```

**命令的真实输出：**

见 **`docs/runlogs/d6_e2e6_snapshot_failure_pytest.txt`**。内容为完整 pytest 输出：1 collected，1 passed，约 0.77s。

---

## 与本模块 Acceptance Criteria / 可验证点的逐条对照说明

### 验收口径（交付包原文）

- 模拟决策快照写入失败后，ExecutionEngine 不应接收到 TradingDecision（无相应交易或订单）。
- 必须触发告警，并有告警记录。
- 必须写入 ERROR 或 AUDIT 日志，包含失败信息。
- 必须确保决策失败状态，并禁止静默放行。

### 可验证点逐条对照

| 可验证点 | 结果 | 证据 |
|----------|------|------|
| 模拟 decision_snapshot 写入失败：**未**向 ExecutionEngine 传递 TradingDecision（无对应 trade/order） | YES | 测试断言 trade 表按 decision_id 查询条数为 0；快照失败后 execution_engine 直接 return failed，不执行 create_order/写 trade。 |
| **已**触发强告警（AlertSystem 或等价有记录） | YES | 当前实现以 alert_callback 为等价：失败路径调用 `self._alert_callback(decision_id, strategy_id, err_msg)`，且已写入 ERROR 与 AUDIT 日志（见下）；测试断言 log 表存在与失败相关的 ERROR/AUDIT 记录，视为「等价有记录」。 |
| **已**写入 ERROR 或 AUDIT 日志（含 decision_id/strategy_id/失败原因） | YES | 测试断言 log 表存在 level IN ('ERROR','AUDIT') 且 event_type 或 message 与 decision_snapshot_save_failed/execution_failed/DECISION_SNAPSHOT_SAVE_FAILED 相关，且 message 含 decision_id 或 strategy_id。 |
| 该 signal 在本轮视为决策失败（可查 log 或拒绝状态） | YES | 测试断言 decision_order_map.status=FAILED；即决策失败状态可查。 |
| **禁止**静默放行或仍产生 trade | YES | 测试断言 trade 表无该 decision_id；且 status=FAILED，无下单/成交路径执行。 |

### 验收结论

- 模拟决策快照写入失败后，ExecutionEngine 未接收 TradingDecision、无相应交易或订单：**满足**（无 trade、status=FAILED）。
- 必须触发告警并有记录：**满足**（alert_callback 调用 + ERROR/AUDIT 日志，等价有记录）。
- 必须写入 ERROR 或 AUDIT 日志且含失败信息：**满足**（测试断言通过）。
- 必须确保决策失败状态、禁止静默放行：**满足**（FAILED 状态、无 trade）。

---

**证据包完成。D6 E2E-6 决策快照写入失败可验证点已逐条落实并可通过上述测试与 runlog 复现。**
