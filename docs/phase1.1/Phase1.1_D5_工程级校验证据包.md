# Phase1.1 D5 工程级校验证据包

**模块**: D5 - 恢复成功全链路测试（PAUSED → RUNNING）  
**依据**: 《Phase1.1 开发交付包》D5、B1、C7 条款  
**日期**: 2026-02-05  

---

## 0. D5 条款对齐表

| Clause ID | Phase1.1 原文条款（保持原语义） | 对条款的理解（1 句话） |
|----------|----------------------------------|------------------------|
| D5-01 | 强校验通过时返回 2xx | 真实 B1 路由 POST /strategy/{id}/resume 返回 HTTP 200 |
| D5-02 | 策略状态变为可接收信号（如 RUNNING） | strategy_runtime_state.status 由 PAUSED 变为 RUNNING |
| D5-03 | DB 中存在对应 STRATEGY_RESUMED 记录 | position_reconcile_log 存在 event_type=STRATEGY_RESUMED |
| D5-04 | 可选：断言后续信号可被正常处理 | 恢复后 POST /webhook/tradingview 返回 200 且 status=accepted；D5.1 补丁：accepted 后 decision_order_map 存在与本次 webhook 对应的 RESERVED 占位记录 |
| D5-05 | 测试必须验证状态更新与 C7 终态日志的落库 | 断言 RUNNING + STRATEGY_RESUMED 存在 |
| D5-06 | 测试可重复运行且通过 | pytest 可重复执行通过 |

---

## 1. 目标校验矩阵（逐条覆盖 D5 Clause）

| Clause ID | Phase1.1 条款摘要 | 测试位置（文件:行号） | 校验方式（assert / 查询） | 结果 |
|----------|-------------------|------------------------|----------------------------|------|
| D5-01 | 强校验通过返回 2xx | test_resume_success_d5.py:107-110 | TestClient POST /strategy/{id}/resume → assert status_code==200, body.status==resumed | 通过 |
| D5-02 | 状态变为 RUNNING | test_resume_success_d5.py:112-117 | get_db_session → state_repo.get_by_strategy_id → assert status==RUNNING | 通过 |
| D5-03 | STRATEGY_RESUMED 落库 | test_resume_success_d5.py:119-123 | log_repo.list_by_strategy → event_type==STRATEGY_RESUMED，len>=1 | 通过 |
| D5-04 | 恢复后信号可被正常接收（含 D5.1 可交易证据） | test_resume_success_d5.py:125-156 | POST /webhook/tradingview → 200+accepted；以响应 decision_id 查 decision_order_map，断言存在且 strategy_id/signal_id/status=RESERVED 与本次 webhook 一致 | 通过 |
| D5-05 | 状态更新与 C7 终态日志 | test_b1_resume.py:127-160 + test_resume_success_d5.py 全链 | 同上 + 现有 test_b1_resume_success_2xx_and_strategy_resumed 验证同事务语义 | 通过 |
| D5-06 | 可重复运行且通过 | 全量 pytest | pytest -q 及单文件 pytest 多次执行 | 通过 |

---

## 2. 关键实现/测试快照（Code Snapshot）

### 2.1 可恢复状态构造（PAUSED、风控通过）

- **test_resume_success_d5.py** fixture `d5_resume_success_setup`：文件 DB + monkeypatch（DATABASE_URL、TV_WEBHOOK_SECRET、STRATEGY_ID、LOG_DIR）→ create_app() → 同一 DB 上插入 `strategy_runtime_state(strategy_id=D5_STRATEGY_ID, status=PAUSED)`，无超仓持仓（RiskConfig() 默认风控通过）。

### 2.2 真实 B1 恢复成功路径

```python
with TestClient(app) as client:
    response = client.post(f"/strategy/{strategy_id}/resume")
assert response.status_code == 200
assert response.json().get("status") == "resumed"
assert response.json().get("strategy_id") == strategy_id
```

### 2.3 状态 PAUSED → RUNNING 与 STRATEGY_RESUMED 终态日志

```python
async with get_db_session() as session:
    state = await state_repo.get_by_strategy_id(strategy_id)
    assert getattr(state, "status", None) == STATUS_RUNNING

    logs = await log_repo.list_by_strategy(strategy_id, limit=10)
    resumed_logs = [l for l in logs if getattr(l, "event_type", None) == STRATEGY_RESUMED]
    assert len(resumed_logs) >= 1
```

### 2.4 恢复后信号可被正常接收

```python
with TestClient(app) as client:
    signal_response = client.post(
        "/webhook/tradingview",
        content=payload_bytes,
        headers={"Content-Type": "application/json", "X-TradingView-Signature": signature},
    )
assert signal_response.status_code == 200
assert signal_response.json().get("status") == "accepted"
```

### 2.5 D5.1 补丁：恢复后可交易证据强化（DB 锚点）

accepted 之后新增 DB 断言，证明系统已进入处理流程（非仅 HTTP 200）：

- **锚点表**：`decision_order_map`（现有表，accepted 时 SignalApplicationService 写入 RESERVED 占位）。
- **定位方式**：响应体中的 `decision_id`、`signal_id`（与本次 webhook 一一对应）。
- **断言**：`DecisionOrderMapRepository.get_by_decision_id(decision_id)` 返回非空；`strategy_id`、`signal_id` 与本次请求一致；`status == RESERVED`。

```python
decision_id = signal_data.get("decision_id")
signal_id_from_response = signal_data.get("signal_id")
async with get_db_session() as session:
    dom_repo = DecisionOrderMapRepository(session)
    dom_row = await dom_repo.get_by_decision_id(decision_id)
assert dom_row is not None
assert dom_row.strategy_id == strategy_id
assert dom_row.signal_id == signal_id_from_response
assert getattr(dom_row, "status", None) == RESERVED
```

---

## 3. 测试与实跑输出（原始证据）

### 3.1 仅跑 D5 测试文件（含 D5.1 断言）

```bash
cd trading_system && python -m pytest tests/integration/test_resume_success_d5.py -v --tb=short
```

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0 -- /Users/zhangkuo/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 1 item

tests/integration/test_resume_success_d5.py::test_d5_resume_success_then_running_and_strategy_resumed_and_signal_accepted PASSED [100%]

============================== 1 passed in 0.44s ===============================
```

### 3.1b pytest -v 原始输出（D5.1 补丁后）

```bash
python -m pytest -v tests/integration/test_resume_success_d5.py
```

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 1 item

tests/integration/test_resume_success_d5.py::test_d5_resume_success_then_running_and_strategy_resumed_and_signal_accepted PASSED [100%]

============================== 1 passed in 0.44s ===============================
```

### 3.2 pytest -q（全量）

```bash
python -m pytest -q
```

```
........................................................................ [ 35%]
........................................................................ [ 70%]
...........................................................              [100%]
203 passed in 8.09s
```

### 3.3 与 D5 相关的 B1 成功用例（同事务语义）

```bash
python -m pytest tests/integration/test_b1_resume.py::test_b1_resume_success_2xx_and_strategy_resumed -v
```

- 直接调用 `resume_strategy`，验证 outcome=="ok"、状态 RUNNING、STRATEGY_RESUMED 存在，与 D5 全链路（真实 B1 路由 + 信号接收）互补。

---

## 4. 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否真实走 B1 恢复成功路径？ | **是** | TestClient POST /strategy/{id}/resume，未绕过路由 |
| 强校验是否通过？ | **是** | 构造 PAUSED + 无超仓，RiskConfig() 默认风控通过 |
| 状态是否由 PAUSED → RUNNING？ | **是** | 断言 strategy_runtime_state.status == RUNNING |
| 是否写入 STRATEGY_RESUMED 终态日志？ | **是** | 断言 position_reconcile_log 存在 event_type=STRATEGY_RESUMED |
| 恢复后信号是否可被正常接收？ | **是** | POST /webhook/tradingview 返回 200 且 status=accepted；D5.1：decision_order_map 存在对应 RESERVED 占位（decision_id/signal_id/strategy_id 一致） |
| 测试是否可重复运行且通过？ | **是** | pytest 全量 203 passed，单文件 1 passed |

---

## 5. 变更清单（Change Manifest）

| 文件 | 变更类型 | 说明 | 对应 Clause |
|------|----------|------|-------------|
| tests/integration/test_resume_success_d5.py | 新增/补丁 | D5 全链路 + D5.1：恢复成功 → RUNNING + STRATEGY_RESUMED → 信号 accepted + decision_order_map RESERVED 占位断言 | D5-01～D5-06、D5.1 |
| docs/Phase1.1_D5_工程级校验证据包.md | 新增 | D5 工程级校验证据包（本文件） | 验收输入 |

**已有且未改**：test_b1_resume.py 中 test_b1_resume_success_2xx_and_strategy_resumed 继续作为 B1/C7 同事务与状态/日志落库的补充验证。

---

## 6. 放行自检

- [x] 严格对齐《Phase1.1 开发交付包》D5  
- [x] 真实走 B1 恢复成功路径（强校验通过）  
- [x] 验证状态 PAUSED → RUNNING  
- [x] 验证写入 STRATEGY_RESUMED 终态日志  
- [x] 验证恢复后信号可被正常接收  
- [x] D5.1 补丁：accepted 后 DB 断言 decision_order_map 占位记录，增强「恢复后可交易」证据强度  
- [x] 工程级校验证据包完整、可复现  

**结论**：D5 满足《Phase1.1 开发交付包》验收口径；D5.1 补丁已增强 D5-04 证据强度，可放行。
