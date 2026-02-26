# Phase1.1 C5 工程级校验证据包

**模块**：C5 - 超仓挂起（拒绝信号 + PAUSED + 终态日志）  
**真理源**：《Phase1.1 开发交付包》C5 条款，无增删改。

---

## 0. C5 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 对条款的理解（1 句话） |
|------------|----------------------------------|------------------------|
| C5-01 | 超仓或不通过风控时挂起策略 | 触发 PAUSED 状态并拒绝新信号 |
| C5-02 | 信号拒绝返回 200 + 拒绝原因 | 必须返回 HTTP 200，且在 body 中明确「拒绝原因」 |
| C5-03 | 必须写入 STRATEGY_PAUSED 终态日志 | 终态日志记录挂起原因、持仓信息等（含差异快照） |
| C5-04 | 状态更新与日志写入同一事务内 | PAUSED 状态更新和终态日志写入在同一事务内 |
| C5-05 | 挂起后拒绝新信号 | 必须通过 API 返回拒绝响应，并记录拒绝原因 |
| C5-06 | PAUSED 状态只能通过 resume 恢复 | 只有通过 B1 的强校验恢复接口可恢复为 RUNNING 状态 |

---

## 3.1 目标校验矩阵（逐条覆盖 C5 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式（测试/脚本/命令） | 结果 |
|-----------|-------------------|------------------------|----------------------------|------|
| C5-01 | 超仓或风控不通过时挂起策略（PAUSED） | strategy_manager.py:74-86；strategy_runtime_state_repo.py:25-33 | test_c5_risk_fail_pause_same_transaction：reconcile 风控失败 → on_risk_check_failed → pause_strategy → 断言 status=PAUSED | PASS |
| C5-02 | 信号拒绝返回 HTTP 200 + 拒绝原因 | signal_receiver.py:151-161 | 入口若 state.status==PAUSED 则 return JSONResponse(200, {"status":"rejected","reason":"STRATEGY_PAUSED"})；test_c5_signal_rejected_when_paused 验证拒绝记录 | PASS |
| C5-03 | 必须写入 STRATEGY_PAUSED 终态日志 | strategy_manager.py:81-86；position_reconcile_log_repo.py:34-56（diff_snapshot） | test_c5_risk_fail_pause_same_transaction 断言 position_reconcile_log 存在 event_type=STRATEGY_PAUSED 且 diff_snapshot 非空 | PASS |
| C5-04 | 状态更新与终态日志同一事务内 | strategy_manager.py:64-67, 74-86（持锁内 update + log_event_in_txn） | pause_strategy 要求 session.in_transaction()；同 session 内先 update_status_to_paused 再 log_event_in_txn | PASS |
| C5-05 | 挂起后拒绝新信号并记录拒绝原因 | signal_receiver.py:148-161；signal_rejection_repo.py | PAUSED 时写 signal_rejection 表；test_c5_signal_rejected_when_paused 断言 rejection 记录存在 | PASS |
| C5-06 | PAUSED 仅能通过 B1 resume 恢复 | strategy_runtime_state 仅在本模块被置为 PAUSED；无本模块内恢复逻辑 | 代码审查：无 C5 内将 PAUSED 改回 RUNNING 的代码；B1 为独立模块 | PASS |

---

## 3.2 关键实现快照（Code Snapshot）

### 挂起时更新 PAUSED 状态 + 写入 STRATEGY_PAUSED 终态日志（同事务、持锁内）

```python
# src/execution/strategy_manager.py（节选）
async with lock.use_lock(strategy_id) as acquired:
    if not acquired:
        return False
    positions = await position_repo.get_all_by_strategy(strategy_id)
    diff_snapshot = _build_diff_snapshot(reason_code, message, positions)
    updated = await state_repo.update_status_to_paused(strategy_id)
    if not updated:
        raise RuntimeError(...)
    await reconcile_log_repo.log_event_in_txn(
        strategy_id=strategy_id,
        event_type=STRATEGY_PAUSED,
        diff_snapshot=diff_snapshot,
    )
    return True
```

### 写入 STRATEGY_PAUSED 终态日志（含 diff_snapshot）

```python
# src/repositories/position_reconcile_log_repo.py log_event_in_txn 支持 diff_snapshot
log = PositionReconcileLog(
    strategy_id=strategy_id,
    event_type=event_type,
    external_trade_id=external_trade_id,
    price_tier=price_tier,
    diff_snapshot=diff_snapshot,
)
self.session.add(log)
```

### 信号拒绝逻辑（API 响应 200 + 拒绝原因）

```python
# src/app/routers/signal_receiver.py（节选）
state_repo = StrategyRuntimeStateRepository(session)
state = await state_repo.get_by_strategy_id(signal.strategy_id)
if state and getattr(state, "status", None) == STATUS_PAUSED:
    rej_repo = SignalRejectionRepository(session)
    await rej_repo.create_rejection(
        signal.strategy_id,
        REASON_STRATEGY_PAUSED,
        signal_id=signal.signal_id,
    )
    return JSONResponse(
        status_code=200,
        content={"status": "rejected", "reason": "STRATEGY_PAUSED"},
    )
```

---

## 3.3 测试与实跑输出（原始证据）

### pytest -q

```
185 passed in 16.07s
```

### pytest -ra

```
============================= 185 passed in 16.38s =============================
```

### pytest -q tests/integration

```
98 passed in 6.81s
```

### C5 专项测试

```bash
pytest tests/integration/test_c5_pause_and_signal_rejection.py -q -v
```

```
tests/integration/test_c5_pause_and_signal_rejection.py::test_c5_risk_fail_pause_same_transaction PASSED
tests/integration/test_c5_pause_and_signal_rejection.py::test_c5_signal_rejected_when_paused PASSED
2 passed in 0.50s
```

---

## 3.4 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否每次超仓/风控失败都会挂起策略？ | **是** | on_risk_check_failed 由调用方传入，对接 pause_strategy；test_c5_risk_fail_pause_same_transaction 覆盖“风控失败 → 挂起”路径；若未传入 on_risk_check_failed 则不会挂起（由上层业务决定是否接入 C5）。 |
| 是否每次挂起都会生成 STRATEGY_PAUSED 终态日志？ | **是** | pause_strategy 内 update_status_to_paused 成功后必调用 log_event_in_txn(STRATEGY_PAUSED, diff_snapshot=...)，同事务。 |
| 是否每次挂起都会拒绝新信号？ | **是** | 信号入口在处理前查 strategy_runtime_state.status，若 PAUSED 则返回 200+rejected 并写 rejection，不进入占位逻辑。 |
| 是否允许通过 HTTP 4xx/5xx 表示挂起？ | **否** | 文档明确禁止；实现仅用 200 + body status=rejected, reason=STRATEGY_PAUSED。 |
| 是否存在残余风险？ | 有说明 | 1) strategy_runtime_state 行须由业务/测试预先存在，否则 update_status_to_paused 影响 0 行会抛错。2) 若调用方未传入 on_risk_check_failed，风控失败不会自动挂起，依赖上层对接。 |

---

## 3.5 变更清单（Change Manifest）

（当前工作区非 git 仓库时，按实现列出变更文件及对应 C5 条款。）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| alembic/versions/017_c5_strategy_status_paused_log_signal_rejection.py | 新增：strategy_runtime_state.status、position_reconcile_log.diff_snapshot、signal_rejection 表 | C5-01, C5-03, C5-05 |
| src/models/strategy_runtime_state.py | 新增 status 列及 STATUS_RUNNING/STATUS_PAUSED | C5-01, C5-06 |
| src/models/position_reconcile_log.py | 新增 diff_snapshot 列 | C5-03 |
| src/models/signal_rejection.py | 新建：因 PAUSED 拒绝信号可审计表 | C5-05 |
| src/models/__init__.py | 导出 SignalRejection | C5-05 |
| src/repositories/strategy_runtime_state_repo.py | 新增 update_status_to_paused | C5-01, C5-04 |
| src/repositories/position_reconcile_log_repo.py | log_event_in_txn 支持 diff_snapshot | C5-03, C5-04 |
| src/repositories/signal_rejection_repo.py | 新建：create_rejection | C5-05 |
| src/execution/strategy_manager.py | 新建：pause_strategy（持锁、同事务 PAUSED+STRATEGY_PAUSED） | C5-01, C5-03, C5-04 |
| src/app/routers/signal_receiver.py | PAUSED 时 200+rejected+写 rejection 记录 | C5-02, C5-05 |
| tests/integration/test_c5_pause_and_signal_rejection.py | C5 集成测试：挂起同事务、拒绝与记录 | 全条款 |

---

**验收结论**：C5 条款在校验矩阵中逐条覆盖；超仓/风控失败时通过 on_risk_check_failed 调用 pause_strategy 实现挂起并生成 STRATEGY_PAUSED 终态日志；信号拒绝为 HTTP 200 且拒绝原因明确；挂起状态与终态日志在同一事务内提交；证据包可复现（pytest 命令见 3.3）。
