# C6 工程级校验证据包

**模块**：C6 - STRATEGY_PAUSED 终态日志（含差异快照）  
**真理源**：《Phase1.1 开发交付包》C6 条款，无增删改。

---

## 0. C6 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 对条款的理解（1 句话） |
|-----------|----------------------------------|------------------------|
| C6-01 | 在写入 STRATEGY_PAUSED 终态日志时，除必要元数据外，必须包含「差异快照」；内容可为当前持仓、风控阈值、超出项、或标准化 diff 结构（与 B1 diff 可复用） | 终态日志必须包含结构化差异快照，不允许仅文本描述 |
| C6-02 | 存储形式：数据库表的 JSON 字段或结构化列；格式固定、可解析；差异快照格式固定、可被工具或 B1 的 diff 逻辑复用/对比 | 差异快照为固定格式、可解析，与 B1 diff 可复用 |
| C6-03 | 与 C5 的衔接：该日志与 PAUSED 状态更新在同一事务内写入；与 C5 同一事务约束不变 | 日志与 PAUSED 状态更新必须在同一事务内提交 |
| C6-04 | 以数据库中的 STRATEGY_PAUSED 终态日志记录为准；差异快照内容以写入时的状态为准，不再事后修改 | 真理源为 DB 终态日志；快照内容以写入时状态为准 |
| C6-05 | （Phase1.1 全文档约定）日志/快照不含敏感数据（如 C1 锁日志、B1 diff 摘要、配置 snapshot 禁止包含 webhook secret、raw payload） | 差异快照不得包含账户、余额、secret、raw payload 等敏感信息 |

---

## 3.1 目标校验矩阵（逐条覆盖 C6 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式（测试/脚本/命令） | 结果 |
|-----------|-------------------|------------------------|----------------------------|------|
| C6-01 | 终态日志必须包含差异快照，不允许仅文本描述 | strategy_manager.py:52-62 _build_diff_snapshot；81-86 log_event_in_txn(diff_snapshot=...) | test_c6_strategy_paused_has_non_empty_parseable_diff_snapshot 断言 diff_snapshot 非空且含 reason_code/message/positions | PASS |
| C6-02 | 格式固定、可解析，与 B1 diff 可复用 | strategy_manager.py:17-24 DIFF_SNAPSHOT_REQUIRED_KEYS、schema 注释；_build_diff_snapshot 输出 JSON | 同上：json.loads(diff_snapshot) 且包含全部 DIFF_SNAPSHOT_REQUIRED_KEYS | PASS |
| C6-03 | 与 C5 同一事务内写入 | strategy_manager.py:64-67, 74-86（持锁内先 update_status_to_paused 再 log_event_in_txn） | C5 测试 test_c5_risk_fail_pause_same_transaction 已验证同事务；pause_strategy 要求 session.in_transaction() | PASS |
| C6-04 | 差异快照以写入时状态为准，不再事后修改 | position_reconcile_log.diff_snapshot 写入后无更新逻辑；仅 C5 挂起时写入 | 代码审查：无对已写入 diff_snapshot 的 UPDATE | PASS |
| C6-05 | 不包含敏感数据 | strategy_manager.py:21-22 禁止字段约定；_build_diff_snapshot 仅组 reason_code/message/positions | test_c6_diff_snapshot_contains_no_sensitive_keys 断言无 account_id/balance/secret 等键 | PASS |

---

## 3.2 关键实现快照（Code Snapshot）

### 差异快照 schema（预定义字段，与 B1 diff 可复用）

```python
# src/execution/strategy_manager.py（节选）

# C6 差异快照 schema（预定义字段，不得超出；与 B1 diff 可复用部分结构）
# - reason_code: str, 风控/挂起原因码
# - message: str, 说明文本，最大 DIFF_SNAPSHOT_MAX_MESSAGE_LEN 字符
# - positions: list[{symbol, side, quantity}] 当前持仓摘要（不含敏感数据）
# 禁止包含：账户 ID、余额、webhook secret、raw payload、签名等敏感信息
DIFF_SNAPSHOT_MAX_MESSAGE_LEN = 500
DIFF_SNAPSHOT_REQUIRED_KEYS = frozenset({"reason_code", "message", "positions"})
```

### 差异快照生成逻辑（非空、可解析；失败则抛异常以回滚事务）

```python
def _build_diff_snapshot(reason_code: str, message: str, positions: List[Any]) -> str:
    positions_summary = [
        {"symbol": getattr(p, "symbol", None), "side": getattr(p, "side", None), "quantity": str(getattr(p, "quantity", 0))}
        for p in positions
    ]
    payload = {
        "reason_code": reason_code or "",
        "message": (message or "")[:DIFF_SNAPSHOT_MAX_MESSAGE_LEN],
        "positions": positions_summary,
    }
    try:
        out = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        logger.exception("C6: diff_snapshot build failed: %s", e)
        raise RuntimeError(f"C6: diff_snapshot must be serializable: {e!s}") from e
    if not out or not out.strip():
        raise RuntimeError("C6: diff_snapshot must be non-empty")
    return out
```

### 锁内 PAUSED 状态更新 + STRATEGY_PAUSED 日志写入（同事务）

```python
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

---

## 3.3 测试与实跑输出（原始证据）

### pytest -q

```
........................................................................ [ 38%]
........................................................................ [ 77%]
...........................................                              [100%]
187 passed, 1 warning in 10.78s
```

### pytest -ra

```
======================= 187 passed, 4 warnings in 10.46s =======================
```

### pytest -q tests/integration

```
100 passed in 6.74s
```

### C6 专项测试

```bash
pytest tests/integration/test_c6_diff_snapshot.py -q -v
```

```
tests/integration/test_c6_diff_snapshot.py::test_c6_strategy_paused_has_non_empty_parseable_diff_snapshot PASSED
tests/integration/test_c6_diff_snapshot.py::test_c6_diff_snapshot_contains_no_sensitive_keys PASSED
2 passed in 0.19s
```

---

## 3.4 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否每次挂起都会生成 STRATEGY_PAUSED 终态日志？ | **是** | pause_strategy 在 update_status_to_paused 成功后必调用 log_event_in_txn(STRATEGY_PAUSED, diff_snapshot=...)，且 _build_diff_snapshot 失败会抛异常导致事务回滚，不会出现「有状态无日志」 |
| 是否记录了完整的差异快照，并且能够解析？ | **是** | 每次写入前 _build_diff_snapshot 生成 JSON，含 reason_code、message、positions；非空校验与 json.dumps 异常会抛错；test_c6 断言 json.loads 及 DIFF_SNAPSHOT_REQUIRED_KEYS |
| 是否确保 PAUSED 状态更新与日志写入在同一事务内？ | **是** | pause_strategy 要求 session.in_transaction()，持锁内先 update 再 log_event_in_txn，同一 session 同一事务 |
| 是否存在敏感数据泄露的风险？ | **否** | 差异快照仅包含 reason_code、message、positions（symbol/side/quantity）；禁止字段在注释与测试中约定并校验 |
| 是否存在残余风险？ | 有说明 | 若 on_risk_check_failed 未接入或未调用 pause_strategy，则不会产生 STRATEGY_PAUSED 日志（属 C5 对接责任）。差异快照当前未包含「风控阈值/超出项」数值，因 C4 回调仅传 reason_code/message；后续若需可扩展 payload 字段并在 schema 中补充约定。 |

---

## 3.5 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| src/execution/strategy_manager.py | C6 schema 常量与注释、_build_diff_snapshot 非空/异常语义及禁止敏感数据约定 | C6-01, C6-02, C6-04, C6-05 |
| tests/integration/test_c6_diff_snapshot.py | C6 集成测试：非空可解析、必填字段、无敏感键 | C6-01, C6-02, C6-05 |
| docs/C6_工程级校验证据包.md | 本证据包：条款表、校验矩阵、快照、测试输出、回归声明、变更清单 | 全条款 |

---

**验收结论**：C6 条款在校验矩阵中逐条覆盖；STRATEGY_PAUSED 终态日志含非空、可解析的差异快照且字段与文档一致；状态更新与日志写入在同一事务内；差异快照不包含敏感数据；证据包可复现（pytest 命令见 3.3）。
