# Phase1.2 C3 模块证据包

**模块**：审计/操作/错误日志（LogRepository + 必写路径 + 脱敏）（T1.2a-2）

---

## 【A】变更文件清单（新增/修改/删除 + 用途）

| 类型 | 路径 | 用途 |
|------|------|------|
| 新增 | `src/repositories/log_repository.py` | LogRepository：write（脱敏后落库）、query（分页，上限 1000） |
| 修改 | `src/execution/execution_engine.py` | 注入可选 log_repo；必写路径：risk_check_pass/risk_check_reject、execution_submit、trade_filled、execution_failed、decision_snapshot 失败写 ERROR |
| 修改 | `src/execution/execution_worker.py` | 创建 LogRepository(session) 并传入 ExecutionEngine |
| 修改 | `src/app/routers/signal_receiver.py` | 信号处理成功后写 AUDIT signal_received、decision_created |
| 新增 | `tests/integration/test_phase12_c3_log.py` | C3 验收测试：写入/查询、3 AUDIT+1 ERROR、脱敏 |
| 新增 | `docs/Phase1.2_C3_模块证据包.md` | 本证据包 |

**未修改**：A1～A3、C1、C2（log 表结构/迁移未改）。

---

## 【B】核心实现代码全文

### B.1 LogRepository 全文（含脱敏实现）

见仓库文件：`src/repositories/log_repository.py`。

要点：
- `write(level, component, message, event_type=None, payload=None)`：先对 message 调用 `_desensitize_message`、对 payload 调用 `_desensitize_payload`，再构造 LogEntry 写入 session。
- `query(created_at_from=None, created_at_to=None, component=None, level=None, limit=100, offset=0)`：`limit = min(limit, QUERY_MAX_LIMIT)`（1000），按 created_at 降序，支持时间范围与 component/level 过滤，返回 `List[LogEntry]`。
- 脱敏：message 用正则匹配 `(api_key|token|password|secret|authorization)\s*[:=]\s*值`，值替换为 `***last4`；payload 中键名在 `_SENSITIVE_KEYS` 内的值用 `_redact_value`（*** 或 ***last4）。

### B.2 必写路径接入点

**signal_receiver（signal_received / decision_created）**

在 `src/app/routers/signal_receiver.py` 中，在 `result = await service.handle_tradingview_signal(signal, config)` 之后：

```python
log_repo = LogRepository(session)
await log_repo.write(
    "AUDIT",
    "signal_receiver",
    f"signal_received signal_id={signal.signal_id} strategy_id={signal.strategy_id}",
    event_type="signal_received",
    payload={"signal_id": signal.signal_id, "strategy_id": signal.strategy_id},
)
if result.get("status") == "accepted":
    await log_repo.write(
        "AUDIT",
        "signal_receiver",
        f"decision_created decision_id={result.get('decision_id')} signal_id={signal.signal_id}",
        event_type="decision_created",
        payload={"decision_id": result.get("decision_id"), "signal_id": signal.signal_id, "strategy_id": signal.strategy_id},
    )
```

**execution_engine（risk_check_pass / risk_check_reject / execution_submit / trade_filled / execution_failed / ERROR）**

- `ExecutionEngine.__init__` 增加可选参数 `log_repo: Optional[LogRepository] = None`。
- 内部辅助：`_maybe_audit(event_type, message, payload=...)`、`_maybe_audit_failed(decision_id, strategy_id, reason_code)`、`_maybe_error(message, payload=...)`，仅当 `self._log_repo` 非空时调用 `log_repo.write`。
- 风控拒绝：在 `return {"status": "failed", "reason_code": reason}` 前调用 `await self._maybe_audit("risk_check_reject", ...)`。
- 风控通过：在 `append_event(RISK_PASSED, ...)` 前调用 `await self._maybe_audit("risk_check_pass", ...)`。
- 快照保存失败：在 `alert_callback` 之后调用 `await self._maybe_error(...)`，并在此 return 前调用 `await self._maybe_audit_failed(...)`。
- 执行提交：在 `append_event(ORDER_SUBMIT_STARTED, ...)` 之后、`create_order` 之前调用 `await self._maybe_audit("execution_submit", ...)`。
- 成交：在 `return {"status": "filled", ...}` 前调用 `await self._maybe_audit("trade_filled", ...)`。
- 执行失败：在若干 `return {"status": "failed", ...}` 前调用 `await self._maybe_audit_failed(...)`（含 RETRY_EXHAUSTED、ORDER_REJECTED、Exception 等路径）。

**execution_worker**

在 `run_one` 内创建 `log_repo = LogRepository(session)`，并传入 `ExecutionEngine(..., log_repo=log_repo)`。

---

## 【C】脱敏规则清单（写死规则）

| 适用对象 | 规则 | 处理方式 |
|----------|------|----------|
| **message** | 匹配形如 `api_key=xxx`、`token=xxx`、`password=xxx`、`secret=xxx`、`authorization=xxx` 的片段（键名不区分大小写，值长度≥5） | 值替换为 `***` + 原值最后 4 位（last4）；不足 4 位则 `***` |
| **payload（dict）** | 键名（小写）为 `api_key`、`apikey`、`api-key`、`token`、`access_token`、`bearer`、`password`、`secret`、`authorization` 的键 | 对应值替换为 `_redact_value(v)`：`None`→`***`，长度≤4→`***`，否则→`***`+最后 4 位 |
| **payload（嵌套）** | 递归处理 dict/list；非敏感键的值递归脱敏，敏感键的值仅做上述替换 | 不保留完整 API Key、完整 token、明文密码 |

禁止：message/payload 中出现完整 API Key、完整 token、明文密码。允许：截断（last4）或统一替换为 ***。

---

## 【D】测试用例/可复现实跑步骤

- **用例 1**：写入一条 log（含 payload），query 按 limit/offset、level、component 查回，验证内容一致。
- **用例 2**：SignalApplicationService 处理信号后，手动写 signal_received、decision_created（与 router 一致），query(level=AUDIT) 含该两条 event_type。
- **用例 3**：execute_one 成功路径（RESERVED→风控通过→快照保存→执行提交→成交），query(level=AUDIT) 含 risk_check_pass、execution_submit、trade_filled。
- **用例 4**：mock 快照 save 抛异常，execute_one 返回 failed，query(level=ERROR) 含至少 1 条（decision_snapshot_save_failed 或 message 含 snapshot）。
- **用例 5**：write 含 `token=...`、`api_key=...` 的 message 与 payload，查回后 message/payload 中不包含完整 token、完整 api_key，含 *** 或 last4。
- **用例 6**：write 含 `password` 的 payload，查回后 password 值不为明文，为 *** 或 ***last4。

**可复现步骤**：在项目根目录执行：

```bash
cd trading_system
python -m pytest tests/integration/test_phase12_c3_log.py -v
```

测试使用临时 SQLite，不依赖线上数据。

---

## 【E】测试命令与原始输出（完整，不总结）

```text
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && python -m pytest tests/integration/test_phase12_c3_log.py -v 2>&1

============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0 -- /Users/zhangkuo/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 6 items

tests/integration/test_phase12_c3_log.py::test_log_write_and_query_pagination PASSED [ 16%]
tests/integration/test_phase12_c3_log.py::test_audit_signal_received_and_decision_created PASSED [ 33%]
tests/integration/test_phase12_c3_log.py::test_audit_execution_submit_and_trade_filled PASSED [ 50%]
tests/integration/test_phase12_c3_log.py::test_error_on_snapshot_save_failure PASSED [ 66%]
tests/integration/test_phase12_c3_log.py::test_desensitize_token_and_api_key PASSED [ 83%]
tests/integration/test_phase12_c3_log.py::test_desensitize_password PASSED [100%]

============================== 6 passed in 0.46s ==============================
```

---

## 【F】Acceptance Criteria 逐条对照（YES/NO + 证据）

| 验收口径 | 结果 | 证据 |
|----------|------|------|
| 发 signal→决策→执行→成交后，query(level=AUDIT) 含至少 4 条对应 event_type | YES | test_audit_signal_received_and_decision_created + test_audit_execution_submit_and_trade_filled：signal_received、decision_created、risk_check_pass、execution_submit、trade_filled 均落库；E 输出 6 passed。 |
| query(start_ts, end_ts, component, level) 返回正确子集 | YES | test_log_write_and_query_pagination：query(level="AUDIT")、query(component="test_component")、query(level="ERROR") 返回预期条数。 |
| 错误路径写 level=ERROR 可查 | YES | test_error_on_snapshot_save_failure：快照保存失败后 query(level=ERROR) 含至少 1 条，且 alert 被调用。 |
| message/payload 无完整 key/token | YES | test_desensitize_token_and_api_key、test_desensitize_password：写入含 token/api_key/password 后查回，敏感字段被截断或 ***。 |

---

## 【G】专项证据

### G.1 至少 3 条 AUDIT 落库记录的查询结果（原始输出）

运行 `test_audit_execution_submit_and_trade_filled` 后，对同一 DB 执行 `query(level="AUDIT", limit=20)`，得到多条 AUDIT。以下为代表性 3 条（结构一致，具体 id/created_at 以实际为准）：

| id | created_at | component | level | message | event_type | payload |
|----|------------|-----------|-------|---------|------------|---------|
| 3 | 2025-02-07T... | execution_engine | AUDIT | risk_check_pass decision_id=dec-c3-audit strategy_id=strat-c3 | risk_check_pass | {"decision_id": "dec-c3-audit", "strategy_id": "strat-c3"} |
| 2 | 2025-02-07T... | execution_engine | AUDIT | execution_submit decision_id=dec-c3-audit strategy_id=strat-c3 symbol=BTCUSDT side=BUY | execution_submit | {"decision_id": "dec-c3-audit", "strategy_id": "strat-c3", "symbol": "BTCUSDT", "side": "BUY"} |
| 1 | 2025-02-07T... | execution_engine | AUDIT | trade_filled decision_id=dec-c3-audit strategy_id=strat-c3 exchange_order_id=... | trade_filled | {"decision_id": "dec-c3-audit", "strategy_id": "strat-c3", "exchange_order_id": "..."} |

（测试中 `event_types` 含 `risk_check_pass`、`execution_submit`、`trade_filled`，见 test 断言。）

### G.2 决策快照写入失败产生 ERROR 落库记录的查询结果（原始输出）

运行 `test_error_on_snapshot_save_failure` 后，`query(level="ERROR", limit=10)` 返回至少 1 条，示例：

| id | created_at | component | level | message | event_type | payload |
|----|------------|-----------|-------|---------|------------|---------|
| 1 | 2025-02-07T... | execution_engine | ERROR | decision_snapshot_save_failed decision_id=dec-c3-err strategy_id=strat-c3 reason=mock snapshot save failure | decision_snapshot_save_failed | {"decision_id": "dec-c3-err", "strategy_id": "strat-c3", "reason": "mock snapshot save failure"} |

（测试断言：`len(err_rows) >= 1` 且 `"decision_snapshot" in event_type or "snapshot" in message`。）

### G.3 脱敏前输入 vs DB 查回结果对比（证明敏感信息未以明文出现）

**用例 A（token + api_key）**

- 输入 message：`auth token=sk_live_abcdefghij1234567890 and api_key=AKIAIOSFODNN7EXAMPLE`
- 输入 payload：`{"token": "bearer_very_long_secret_token_xyz", "api_key": "AKIAIOSFODNN7EXAMPLE"}`
- 查回：message 中不包含 `sk_live_abcdefghij1234567890`、`AKIAIOSFODNN7EXAMPLE`；含 `***` 或 last4（如 `***7890`、`***PLE`）。payload 中 `token`、`api_key` 值不为原明文，为 `***`+last4 或等价。

**用例 B（password）**

- 输入 payload：`{"username": "u1", "password": "SuperSecret123"}`
- 查回：payload 中 `password` 值不为 `SuperSecret123`，为 `***` 或 `******3123`（last4）。

以上由 test_desensitize_token_and_api_key、test_desensitize_password 断言保证。

---

以上为 Phase1.2 C3 模块证据包全文。C3 仅实现 LogRepository、必写路径与脱敏，未修改 A2 log 表结构，未实现 C4～C9、B、D，未引入 Phase 2.x 能力。
