# PR16c：rehearsal 单一真源 + qty 精度按 symbol 覆盖 — 工程级校验证据包

## 1）变更摘要与边界

### 变更摘要
- **目标 1**：rehearsal 标记单一真源。唯一权威来源为 `execution_events.rehearsal` 列；`message` 不再包含可机读的 `"rehearsal=true/false"` 或 `"rehearsal="` 字样；message 仅保留自然语言描述（可选）。
- **目标 2**：qty 精度按 symbol 覆盖（不接 instruments API）。新增配置 `execution.qty_precision_by_symbol: dict[str, int]`（默认空）；下单/校验 qty 精度时优先取 symbol 对应精度，否则 fallback 到全局 `order_qty_precision`。Live 门禁增强：当 `is_live_endpoint=True`（或未来 live path）时，仅允许 `live_allowlist_symbols` 中的 symbol，且 allowlist 中每个 symbol 须在 `qty_precision_by_symbol` 中显式配置，否则启动 fail-fast（reason_code 清晰）。

### 边界
- **不扩大 scope**：不接外部 API、不改执行链路、不引入新交易能力。
- **不破坏**：PR16 多重 Live 门禁、参数校验、PR15b 闭环、现有测试全绿。

---

## 2）rehearsal 单一真源（证据）

| 项 | 说明 | 证据 |
|----|------|------|
| 权威来源 | `execution_events.rehearsal` 列 | 写入/读取均用该列 |
| message 不含 rehearsal= | message 不再追加 `" rehearsal=true"` 或 `"rehearsal=true"` | `ExecutionEventRepository.append_event` 已移除该逻辑 |
| 回归测试 | 生成 rehearsal 事件后断言 `event.rehearsal=True` 且 `event.message` 不包含 `"rehearsal="` | `tests/integration/test_pr16c_rehearsal_single_source.py`（2 条） |

---

## 3）qty 精度按 symbol 覆盖（证据）

| 配置 | 说明 |
|------|------|
| execution.qty_precision_by_symbol | dict[str, int]，默认 {}；symbol → 小数位上限 |
| execution.live_allowlist_symbols | list[str]，默认 []；is_live_endpoint 时仅允许此列表内 symbol |

**逻辑**：
- 校验 qty 精度时：`precision = qty_precision_by_symbol.get(symbol, order_qty_precision)`。
- 启动校验：`live_allowlist_symbols` 非空时，每个 symbol 须在 `qty_precision_by_symbol` 中，否则 `ConfigValidationError(LIVE_GATE_SYMBOL_PRECISION_MISSING)`。
- 运行时（is_live_endpoint=True）：`live_allowlist_symbols` 非空且 symbol 不在列表内 → `ORDER_REJECTED`，reason_code=`LIVE_GATE_SYMBOL_NOT_ALLOWED`。

**证据**：
- 单元：`tests/unit/execution/test_order_param_validator.py`（`test_validate_qty_precision_symbol_override_effective`、`test_validate_qty_precision_fallback_global`）。
- 集成：`tests/integration/test_pr16c_qty_precision_live_allowlist.py`（live_allowlist 中 symbol 缺精度配置 → fail-fast；全部配置则通过）。

---

## 4）新增/修改文件清单

| 类型 | 路径 | 说明 |
|------|------|------|
| 修改 | src/repositories/execution_event_repository.py | 移除 message 中追加 "rehearsal=true" 逻辑 |
| 修改 | src/models/execution_event.py | 注释更新：message 不再含 "rehearsal=" |
| 修改 | src/config/app_config.py | ExecutionConfig 增加 qty_precision_by_symbol、live_allowlist_symbols；解析与 validate 中 fail-fast |
| 修改 | src/execution/execution_engine.py | 精度取 qty_precision_by_symbol.get(symbol, order_qty_precision)；is_live_endpoint 时校验 live_allowlist_symbols |
| 修改 | src/common/reason_codes.py | 新增 LIVE_GATE_SYMBOL_PRECISION_MISSING、LIVE_GATE_SYMBOL_NOT_ALLOWED |
| 新增 | tests/integration/test_pr16c_rehearsal_single_source.py | rehearsal 单一真源回归（2 条） |
| 新增 | tests/integration/test_pr16c_qty_precision_live_allowlist.py | qty 精度 + live_allowlist 启动 fail-fast / 通过（2 条） |
| 修改 | tests/unit/execution/test_order_param_validator.py | 新增 symbol 覆盖精度生效、全局 fallback（2 条） |

---

## 5）回归不变式声明

- **rehearsal**：唯一权威来源为 DB 列 `rehearsal`；message 仅自然语言，不含 "rehearsal="。
- **精度**：symbol 在 qty_precision_by_symbol 时用该精度，否则用 order_qty_precision；live_allowlist_symbols 非空时须全量在 qty_precision_by_symbol 中（启动 fail-fast）。
- **Live 门禁**：is_live_endpoint 时 live_allowlist_symbols 非空则 symbol 须在列表内，否则 LIVE_GATE_SYMBOL_NOT_ALLOWED。

---

## 6）测试运行证据（pytest 原始输出）

**skipped / xfailed / warnings**：无；全部 passed。

### 6.1）pytest -q

```
........................................................................ [ 56%]
........................................................                 [100%]
128 passed in 2.73s
```

### 6.2）pytest -ra

```
tests/account/test_manager.py ...                                        [  2%]
tests/adapters/test_market_data.py .....                                 [  6%]
tests/execution/test_order_manager.py .......                            [ 11%]
tests/integration/test_app_startup_config_injection.py ..                [ 13%]
tests/integration/test_config_snapshot_event.py ...                      [ 15%]
tests/integration/test_execution_events.py ....                          [ 18%]
tests/integration/test_execution_worker.py ....                          [ 21%]
tests/integration/test_order_manager_audit.py ..                         [ 23%]
tests/integration/test_pr11_strategy_isolation.py .....                  [ 27%]
tests/integration/test_pr13_safety_valves.py ....                        [ 30%]
tests/integration/test_pr14a_live_gate_and_shared_state.py .....         [ 34%]
tests/integration/test_pr14b_okx_config_and_dry_run.py .....             [ 38%]
tests/integration/test_pr15b_okx_create_order_closed_loop.py ...          [ 40%]
tests/integration/test_pr16_incident_rehearsal.py .                      [ 41%]
tests/integration/test_pr16_live_gates.py .                              [ 42%]
tests/integration/test_pr16_param_validation.py ..                      [ 43%]
tests/integration/test_pr16c_qty_precision_live_allowlist.py ..          [ 45%]
tests/integration/test_pr16c_rehearsal_single_source.py ..               [ 46%]
tests/integration/test_risk_balance_gate.py .                            [ 47%]
tests/integration/test_risk_manager.py .....                             [ 51%]
tests/integration/test_tradingview_webhook.py .......                    [ 57%]
tests/integration/test_tradingview_webhook_config_validation.py .        [ 57%]
tests/risk/test_manager.py ...                                           [ 60%]
tests/unit/application/test_signal_service.py ...                        [ 62%]
tests/unit/common/test_event_schema_pr15b.py ....                        [ 65%]
tests/unit/execution/test_live_gate.py ......                            [ 70%]
tests/unit/execution/test_okx_adapter.py .........                       [ 77%]
tests/unit/execution/test_okx_client.py ......                            [ 82%]
tests/unit/execution/test_order_param_validator.py ............          [ 91%]
tests/unit/repositories/test_decision_order_map_repo.py ....             [ 94%]
tests/unit/repositories/test_dedup_signal_repo.py ....                   [ 97%]
tests/unit/repositories/test_orders_repo.py ...                          [100%]

============================= 128 passed in 2.81s ==============================
```

### 6.3）pytest -q tests/integration

```
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.6.0 -- .../trading_system/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
...
tests/integration/test_pr16c_qty_precision_live_allowlist.py::test_live_allowlist_symbols_missing_qty_precision_fail_fast PASSED [ 71%]
tests/integration/test_pr16c_qty_precision_live_allowlist.py::test_live_allowlist_symbols_all_have_precision_passes PASSED [ 72%]
tests/integration/test_pr16c_rehearsal_single_source.py::test_rehearsal_event_rehearsal_column_true_message_no_rehearsal_literal PASSED [ 74%]
tests/integration/test_pr16c_rehearsal_single_source.py::test_rehearsal_event_with_null_message_no_rehearsal_literal PASSED [ 76%]
...
============================== 59 passed in 2.46s ==============================
```

---

## 7）一键复现说明

```bash
cd trading_system
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -ra
.venv/bin/python -m pytest -q tests/integration
```

---

以上为 PR16c 工程级校验证据包。
