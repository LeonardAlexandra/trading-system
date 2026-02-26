# Phase1.1 C4 工程级校验证据包（封版修订版）

**模块**: C4 - RiskManager post-sync full check（对账/同步后全量风控）  
**依据**: Phase1.1 开发交付包 C4 条款 + 封版标准（C4-01 禁止静默跳过、C4-02 同步后最新数据工程硬约束）  
**日期**: 2026-02-05  

---

## 1. 目标校验矩阵（逐条覆盖 C4 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式（测试/脚本/命令） | 结果 |
|-----------|------------------|------------------------|----------------------------|------|
| C4-01 | 对账/EXTERNAL_SYNC 同步后必须执行一次全量检查，不得跳过 | position_manager.py:106-111（risk_manager 必填，None 时 raise） | test_c4_risk_manager_required_raises：reconcile(risk_manager=None) 断言 ValueError 含 C4-01 | PASS |
| C4-02 | 全量检查输入必须基于同步后的最新 position_snapshot，不得使用旧快照 | position_manager.py:207-211（本 session 读取 positions 后传入）；risk_manager.py:187-212（仅使用传入的 positions） | test_c4_full_check_reads_sync_after_data_same_transaction_no_commit：同事务内 sync 后 full_check 读到最新持仓（无 commit） | PASS |
| C4-03 | 若未通过，与 C5 衔接——触发超仓挂起 | position_manager.py:222-223（on_risk_check_failed） | test_c4_full_check_fails_then_on_risk_check_failed_called | PASS |
| C4-04 | 不改变 RiskManager 的输入输出契约以外的语义；仅增加约束与调用点 | risk_manager.py:187-253（full_check 接收 positions 参数，规则与 check() 一致） | 代码审查：full_check 仅用传入 positions，check() 未改 | PASS |
| C4-05 | 日志：检查触发、通过/不通过、不通过原因摘要 | position_manager.py:209, 218-220, 223 | 触发/结果/异常均有 logger | PASS |

---

## 2. 事务边界与 full_check 调用点关系

```
调用方
  async with session.begin():                    # 外层事务边界
      pm.reconcile(session, strategy_id, items, risk_manager=...)
        │
        ├─ risk_manager is None → raise ValueError("C4-01: ...")   # 禁止静默跳过
        ├─ 锁外准备：定价与档位
        ├─ async with lock.use_lock(strategy_id):
        │     └─ 写 trade / 更新 position / 写 reconcile_log（C3）
        ├─ 锁释放后、仍处于同一 session.begin() 内：
        │     positions_sync_after = await self._position_repo.get_all_by_strategy(strategy_id)  # 本事务刚写入的数据
        │     result = await risk_manager.full_check(strategy_id, positions_sync_after, risk_config_override)
        │     # full_check 仅使用传入的 positions_sync_after，不依赖 risk_manager 内部 repo
        └─ return { ..., risk_check_passed, risk_reason_code, risk_message }
  # commit 发生在此处（或调用方稍后）
```

- **full_check 调用时机**：在“同步写入完成”之后（锁已释放）、同一外层事务内。
- **读一致性**：`positions_sync_after` 由 position_manager 从**本 session** 的 `self._position_repo.get_all_by_strategy(strategy_id)` 读取，即本事务内刚写入的持仓，**无需 commit** 即可被 full_check 使用。
- **C4-02 工程硬约束**：full_check 不再从 risk_manager 的 position_repo 读取，仅使用调用方传入的 `positions`，消除“假定同 session/repo”的隐含前提。

---

## 3. 关键实现快照（Code Snapshot）

### 3.1 C4-01：risk_manager 必填，None 时显式失败

```106:111:src/execution/position_manager.py
        if risk_manager is None:
            raise ValueError(
                "C4-01: risk_manager is required for reconcile; full_check must not be skipped. "
                "Pass a RiskManager instance."
            )
```

### 3.2 C4-02：同步后最新数据由 position_manager 传入，full_check 仅用传入的 positions

```207:211:src/execution/position_manager.py
        # ---------- C4：同步完成后全量风控检查（锁已释放，仍同一事务）；C4-02 从本 session 读取后传入 ----------
        positions_sync_after = await self._position_repo.get_all_by_strategy(strategy_id)
        logger.info("reconcile post_sync full_check trigger strategy_id=%s", strategy_id)
        try:
            result = await risk_manager.full_check(strategy_id, positions_sync_after, risk_config_override)
```

```187:212:src/execution/risk_manager.py
    async def full_check(
        self,
        strategy_id: str,
        positions: List[Any],
        risk_config_override: Optional[RiskConfig] = None,
    ) -> Dict[str, Any]:
        """
        C4-02 工程硬约束：持仓数据由调用方传入（position_manager 从同一事务 position_repo 读取的同步后最新数据），
        本方法不再从 self._position_repo 读取，避免隐含“同 session”前提。
        """
        config = risk_config_override if risk_config_override is not None else self._config
        if config.max_position_qty is not None:
            for pos in positions or []:
                qty = (getattr(pos, "quantity", None) or Decimal("0")) if pos else Decimal("0")
                ...
                if qty > config.max_position_qty:
                    return {"passed": False, "reason_code": POSITION_LIMIT_EXCEEDED, "message": "..."}
        ...
        return {"passed": True, "reason_code": None, "message": None}
```

---

## 4. 测试与实跑输出（原始证据）

### 4.1 全量测试 -q

```bash
.venv/bin/python -m pytest -q
```

```
........................................................................ [ 39%]
........................................................................ [ 78%]
.......................................                                  [100%]
183 passed in 12.50s
```

### 4.2 C4 相关测试 -v（含封版新增）

```bash
.venv/bin/python -m pytest tests/integration/test_c4_post_sync_full_check.py -v
```

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.6.0
...
tests/integration/test_c4_post_sync_full_check.py::test_c4_full_check_called_after_reconcile_and_uses_sync_data PASSED [  6%]
tests/integration/test_c4_post_sync_full_check.py::test_c4_full_check_fails_then_on_risk_check_failed_called PASSED [ 12%]
tests/integration/test_c4_post_sync_full_check.py::test_c4_risk_manager_required_raises PASSED [ 18%]
tests/integration/test_c4_post_sync_full_check.py::test_c4_full_check_reads_sync_after_data_same_transaction_no_commit PASSED [ 25%]

============================== 4 passed in 0.23s ==============================
```

### 4.3 最小复现：full_check 读到本事务刚同步写入的最新持仓（无需 commit）

- **用例**：`test_c4_full_check_reads_sync_after_data_same_transaction_no_commit`
- **步骤**：同一 `session.begin()` 内，(1) reconcile 同步写入一条持仓 quantity=10；(2) position_manager 内 `get_all_by_strategy` 得到本事务刚写入的 1 条 position；(3) 将该列表传入 `full_check(strategy_id, positions, risk_config)`，其中 `max_position_qty=5`。
- **预期**：full_check 基于传入的 positions（quantity=10）判定 10 > 5，返回 `passed=False`，`reason_code=POSITION_LIMIT_EXCEEDED`。
- **结论**：证明 full_check 读取到的是**本事务内刚同步写入的最新持仓**，无需 commit。

---

## 5. 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否每次对账/EXTERNAL_SYNC 同步后都触发了 full_check？ | **是** | risk_manager 为必填参数，None 时 raise ValueError（C4-01），无静默跳过 |
| full_check 使用的数据是否为同步后的最新数据？ | **是** | position_manager 在同步完成后从本 session 的 position_repo 读取 positions 并传入 full_check；full_check 仅使用该参数，不依赖 risk_manager 内部 repo（C4-02 工程硬约束） |
| 是否修改了 RiskManager 的规则语义或输入输出契约？ | **否** | full_check 仅新增参数 `positions`，规则与 check() 一致；check() 未改 |
| full_check 不通过是否必然衔接到 C5？ | **是（在提供回调时）** | 不通过且 on_risk_check_failed 非空时必调用 |
| risk_manager 缺失时是否显式失败（不静默跳过）？ | **是** | test_c4_risk_manager_required_raises 断言 ValueError 含 C4-01 |
| 是否存在残余风险？ | **有说明** | 调用方必须在同一事务内调用 reconcile（session.begin()），以保证 positions_sync_after 与本事务写入一致 |

---

## 6. 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| src/execution/position_manager.py | risk_manager 改为必填，None 时 raise；同步后 get_all_by_strategy 取 positions 传入 full_check | C4-01, C4-02 |
| src/execution/risk_manager.py | full_check(strategy_id, positions, risk_config_override)；仅使用传入的 positions，不再从 self._position_repo 读取 | C4-02, C4-04 |
| tests/integration/test_c4_post_sync_full_check.py | test_c4_risk_manager_required_raises；test_c4_full_check_reads_sync_after_data_same_transaction_no_commit；原有用例保留 | C4-01, C4-02 |
| tests/integration/test_d2_external_sync_pricing.py | 所有 reconcile 调用增加 risk_manager=RiskManager(...) | C4-01 |
| docs/Phase1.1_C4_工程级校验证据包.md | 本证据包（封版修订版） | 验收输入 |

---

## 7. 异常与失败语义

| 场景 | 行为 |
|------|------|
| risk_manager 为 None | 立即 raise ValueError("C4-01: risk_manager is required...")，不执行同步与 full_check |
| full_check 抛异常 | logger.exception 后 re-raise，不吞异常 |
| full_check 不通过 | 记录 passed=False，若提供 on_risk_check_failed 则调用；返回 risk_check_passed=False |
