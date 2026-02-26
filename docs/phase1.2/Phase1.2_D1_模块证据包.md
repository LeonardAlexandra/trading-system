# Phase1.2 D1 模块证据包：E2E-1 完整链路可验证点

## 模块名称与目标

| 项目 | 内容 |
|------|------|
| 模块编号 | D1 |
| 模块名称 | E2E-1 完整链路可验证点 |
| 目标 | 验证端到端：Webhook 信号 → decision → 同事务 decision_snapshot → 执行并成交 → 按 signal_id/decision_id 查询得完整链路（含 decision_snapshot）；trace_status=COMPLETE。 |

---

## 本模块涉及的变更文件清单（新增 / 修改 / 删除）

| 类型 | 路径 |
|------|------|
| 修改 | `src/execution/execution_engine.py` |
| 修改 | `src/execution/execution_worker.py` |
| 修改 | `tests/integration/test_phase12_d1_e2e_core_flow.py` |
| 修改 | `docs/Phase1.2_D1_模块证据包.md`（本文件） |
| 新增 | `docs/runlogs/d1_e2e_complete_flow_pytest.txt` |

---

## 本模块的核心实现代码（关键函数或完整文件）

### 1. 执行成交时写入 trade 表（execution_engine.py）

在 Phase1.1 C2 阶段3（PENDING_EXCHANGE → FILLED）中，当 `_trade_repo` 已注入时，在更新 decision_order_map 为 FILLED 后、写入 EV_FILLED 事件前，插入一条 SIGNAL 来源的 trade 记录，使 trace 可达 COMPLETE。

**关键片段：**

```python
# D1：信号驱动成交时写入 trade 表，使 trace 可达 COMPLETE
if self._trade_repo is not None:
    avg_price = getattr(result, "avg_price", None)
    price = avg_price if avg_price is not None else Decimal("0")
    filled_qty = getattr(result, "filled_qty", None) or qty_decimal
    trade_id = f"{decision_id}-fill"
    trade = Trade(
        trade_id=trade_id,
        strategy_id=strategy_id,
        source_type=SOURCE_TYPE_SIGNAL,
        external_trade_id=None,
        signal_id=decision.signal_id,
        decision_id=decision_id,
        execution_id=decision_id,
        symbol=symbol,
        side=side or "BUY",
        quantity=filled_qty,
        price=price,
        slippage=Decimal("0"),
        realized_pnl=Decimal("0"),
        executed_at=now,
        is_simulated=False,
    )
    await self._trade_repo.create(trade)
```

**ExecutionEngine 构造增加可选参数：**

- `trade_repo: Optional[TradeRepository] = None`，赋值 `self._trade_repo = trade_repo`。

### 2. Worker 注入 TradeRepository（execution_worker.py）

在 `run_one` 内创建 `TradeRepository(session)`，并传入 `ExecutionEngine(..., trade_repo=trade_repo)`。

---

## 本模块对应的测试用例与可复现实跑步骤

- **测试用例**：`tests/integration/test_phase12_d1_e2e_core_flow.py::test_d1_e2e_core_flow`
- **可复现步骤**：
  1. 在项目根目录 `trading_system/` 下执行：`python3 -m pytest tests/integration/test_phase12_d1_e2e_core_flow.py -v`
  2. 无需额外数据或环境；测试使用临时 SQLite 与 fixture 提供的配置与 Webhook 密钥。

---

## 测试命令与原始输出结果

**实际执行的命令：**

```bash
python3 -m pytest tests/integration/test_phase12_d1_e2e_core_flow.py -v
```

**命令的真实输出：**

见 **`docs/runlogs/d1_e2e_complete_flow_pytest.txt`**。内容为完整 pytest 输出：1 collected，1 passed，约 4.85s。

---

## 与本模块 Acceptance Criteria / 可验证点的逐条对照说明

### 验收口径（交付包原文）

- 发送 Webhook 后，DB 有 1 条 trade 和 1 条 decision_snapshot，且 decision_id 一致。
- `get_trace_by_signal_id` / `get_trace_by_decision_id` 返回 200 且含五节点，`trace_status=COMPLETE`，`missing_nodes` 为空。

### 可验证点逐条对照

| 可验证点 | 结果 | 证据 |
|----------|------|------|
| 发送一条 Webhook 信号后，DB 有 1 条 trade、1 条 decision_snapshot，且 decision_id 一致 | YES | 测试步骤 3：用 sqlite3 查询 `decision_snapshot` 与 `trade` 表，断言各 1 条且 `trade.decision_id == decision_id`。 |
| get_trace_by_decision_id 返回 TraceResult；trace_status=COMPLETE；missing_nodes 为空 | YES | 测试步骤 4：GET `/api/trace/decision/{decision_id}` 断言 200、`trace_status == "COMPLETE"`、`missing_nodes == []`，且响应含五节点（signal, decision, decision_snapshot, execution, trade）。 |
| get_trace_by_signal_id 返回 TraceResult；trace_status=COMPLETE；missing_nodes 为空 | YES | 测试步骤 5：从 decision_order_map 取 signal_id，GET `/api/trace/signal/{signal_id}` 断言 200、`trace_status == "COMPLETE"`、`missing_nodes == []`，且响应含五节点。 |

### 验收结论

- 发送 Webhook 后 DB 有 1 条 trade、1 条 decision_snapshot 且 decision_id 一致：**满足**（由 execution_engine 在 FILLED 时写入 trade，测试断言 DB 状态）。
- get_trace_by_signal_id / get_trace_by_decision_id 返回 200、含五节点、trace_status=COMPLETE、missing_nodes 为空：**满足**（测试对两接口均做上述断言）。
- 完整链路验证结果：Webhook → decision → decision_snapshot（同事务/worker 内）→ 执行并成交（含 trade 写入）→ 按 signal_id/decision_id 查询得完整链路，trace_status=COMPLETE：**满足**。

---

**证据包完成。D1 E2E-1 完整链路可验证点已逐条落实并可通过上述测试与 runlog 复现。**
