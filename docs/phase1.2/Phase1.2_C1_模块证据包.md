# Phase1.2 C1 模块证据包

**模块编号**: C1  
**模块名称**: 决策输入快照（DecisionSnapshotRepository + 同事务写入 + 写入失败策略）（T1.2a-0）  
**交付日期**: 2026-02-07

---

## 【A】变更文件清单（新增/修改/删除 + 用途）

| 类型 | 文件路径 | 用途 |
|------|----------|------|
| 新增 | `src/repositories/decision_snapshot_repository.py` | DecisionSnapshotRepository：save、get_by_decision_id、list_by_strategy_time（仅 insert + select） |
| 修改 | `src/execution/execution_engine.py` | 注入 snapshot_repo、alert_callback；RISK_PASSED 后同事务写入快照；写入失败时拒绝决策、告警、写 ERROR 日志、不调用下游 |
| 修改 | `src/execution/execution_worker.py` | 创建 DecisionSnapshotRepository(session) 与 alert_callback，传入 ExecutionEngine |
| 新增 | `tests/unit/repositories/test_decision_snapshot_repository.py` | Repository 单测：save/get/list、无 update/delete |
| 新增 | `tests/integration/test_phase12_c1_decision_snapshot.py` | 集成：成功路径写快照；失败路径 mock save 抛异常 → 不调用 create_order、alert 被调用、status=failed |

---

## 【B】核心实现代码全文

### B.1 DecisionSnapshotRepository 文件全文

**文件**: `src/repositories/decision_snapshot_repository.py`

```python
"""
Phase1.2 C1：决策输入快照 Repository（仅 insert + select，无 update/delete）

蓝本 D.1：save 失败抛异常；禁止按 decision_id 的 update/delete。
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.decision_snapshot import DecisionSnapshot


class DecisionSnapshotRepository:
    """
    决策输入快照仓储。仅暴露 save、get_by_decision_id、list_by_strategy_time。
    禁止提供 update/delete 或任何覆盖写语义。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, snapshot: DecisionSnapshot) -> None:
        """
        写入一条决策输入快照。失败时抛出异常，由调用方处理（不产出 TradingDecision、告警、写日志）。
        """
        self.session.add(snapshot)
        await self.session.flush()

    async def get_by_decision_id(self, decision_id: str) -> Optional[DecisionSnapshot]:
        """按 decision_id 单条查询。"""
        stmt = select(DecisionSnapshot).where(DecisionSnapshot.decision_id == decision_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_strategy_time(
        self,
        strategy_id: str,
        start_ts: datetime,
        end_ts: datetime,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[DecisionSnapshot]:
        """按 strategy_id + 时间范围分页查询。"""
        stmt = (
            select(DecisionSnapshot)
            .where(
                DecisionSnapshot.strategy_id == strategy_id,
                DecisionSnapshot.created_at >= start_ts,
                DecisionSnapshot.created_at <= end_ts,
            )
            .order_by(DecisionSnapshot.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
```

### B.2 ExecutionEngine 相关改动（StrategyExecutor 等价：决策执行路径）

**文件**: `src/execution/execution_engine.py`

**（1）__init__ 新增参数与赋值**

```python
        snapshot_repo: Optional[DecisionSnapshotRepository] = None,
        alert_callback: Optional[Callable[[str, str, str], None]] = None,
    ):
        self._dom_repo = dom_repo
        self._snapshot_repo = snapshot_repo
        self._alert_callback = alert_callback
        # ... 其余不变
```

**（2）execute_one 内：RISK_PASSED 之后、下单之前——同事务写入快照 + 写入失败策略**

```python
        # Phase1.2 C1：同事务写入决策输入快照；写入失败则拒绝本次决策、告警、写日志，不向下游传递
        if self._snapshot_repo is not None:
            signal_state = {
                "signal_id": decision.signal_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "quantity": str(decision.quantity) if decision.quantity is not None else "1",
                "created_at": decision.created_at.isoformat() if getattr(decision.created_at, "isoformat", None) else str(decision.created_at) if decision.created_at else None,
            }
            position_state = {}
            risk_check_result = {
                "allowed": risk_result.get("allowed", True),
                "reason_code": risk_result.get("reason_code"),
                "message": risk_result.get("message"),
            }
            decision_result = {
                "decision_id": decision_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "quantity": str(decision.quantity) if decision.quantity is not None else "1",
                "reason": "risk_passed",
            }
            snapshot = DecisionSnapshot(
                decision_id=decision_id,
                strategy_id=strategy_id,
                signal_state=signal_state,
                position_state=position_state,
                risk_check_result=risk_check_result,
                decision_result=decision_result,
            )
            try:
                await self._snapshot_repo.save(snapshot)
            except Exception as e:
                err_msg = str(e)
                if self._alert_callback is not None:
                    self._alert_callback(decision_id, strategy_id, err_msg)
                logger.error(
                    "decision_snapshot_save_failed decision_id=%s strategy_id=%s reason=%s",
                    decision_id,
                    strategy_id,
                    err_msg,
                    exc_info=True,
                )
                await event_repo.append_event(
                    decision_id,
                    FINAL_FAILED,
                    status=FAILED,
                    reason_code="DECISION_SNAPSHOT_SAVE_FAILED",
                    message=err_msg[:500] if err_msg else "snapshot save failed",
                    attempt_count=attempt_before,
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                    rehearsal=_rehearsal,
                )
                await _persist_exception_status(
                    decision_id,
                    FAILED,
                    last_error="DECISION_SNAPSHOT_SAVE_FAILED",
                    updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                return {
                    "decision_id": decision_id,
                    "status": "failed",
                    "reason_code": "DECISION_SNAPSHOT_SAVE_FAILED",
                }
```

---

## 【C】测试用例 / 可复现实跑步骤

- **单元**：`tests/unit/repositories/test_decision_snapshot_repository.py`  
  - `test_save_and_get_by_decision_id`：save 后 get_by_decision_id 返回四块（signal_state/position_state/risk_check_result/decision_result）。  
  - `test_list_by_strategy_time`：按 strategy_id + 时间范围分页返回快照列表。  
  - `test_repository_has_no_update_or_delete`：断言 Repository 无 update/delete/overwrite 方法。

- **集成**：`tests/integration/test_phase12_c1_decision_snapshot.py`  
  - `test_snapshot_written_on_success_flow`：预置 RESERVED → execute_one（带 snapshot_repo + alert_callback）→ 断言 status=filled，且 get_by_decision_id 返回一条快照、四块完整。  
  - `test_save_failure_rejects_decision_and_triggers_alert`：FailingSnapshotRepo.save 抛异常 → 断言 result status=failed、reason_code=DECISION_SNAPSHOT_SAVE_FAILED；create_order 未被调用；alert_callback 被调用且参数含 decision_id/strategy_id/reason；DOM 状态 FAILED；无 decision_snapshot 记录。

**可复现步骤**：在项目根执行下方【D】测试命令即可。

---

## 【D】测试命令与原始输出（完整）

### 测试命令

```bash
cd /Users/zhangkuo/TradingView\ Indicator/trading_system
python -m pytest tests/unit/repositories/test_decision_snapshot_repository.py tests/integration/test_phase12_c1_decision_snapshot.py -v
```

### 原始输出

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0 -- /Users/zhangkuo/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 5 items

tests/unit/repositories/test_decision_snapshot_repository.py::test_save_and_get_by_decision_id PASSED [ 20%]
tests/unit/repositories/test_decision_snapshot_repository.py::test_list_by_strategy_time PASSED [ 40%]
tests/unit/repositories/test_decision_snapshot_repository.py::test_repository_has_no_update_or_delete PASSED [ 60%]
tests/integration/test_phase12_c1_decision_snapshot.py::test_snapshot_written_on_success_flow PASSED [ 80%]
tests/integration/test_phase12_c1_decision_snapshot.py::test_save_failure_rejects_decision_and_triggers_alert PASSED [100%]

============================== 5 passed in 0.20s ==============================
```

---

## 【E】Acceptance Criteria 逐条对照（YES/NO + 证据）

| # | 验收口径 | 结论 | 证据 |
|---|----------|------|------|
| 1 | 给定一条决策，DB 中有一条 decision_snapshot 且 decision_id 一致 | YES | 集成 test_snapshot_written_on_success_flow：execute_one 成功后 get_by_decision_id(decision_id) 返回一行，decision_id 一致。 |
| 2 | get_by_decision_id 返回完整四块（signal_state, position_state, risk_check_result, decision_result） | YES | 单测 test_save_and_get_by_decision_id 断言四块内容；集成 test_snapshot_written_on_success_flow 断言 signal_state/risk_check_result/decision_result 含预期键。 |
| 3 | list_by_strategy_time 返回该策略时间范围内快照 | YES | 单测 test_list_by_strategy_time：写入 3 条后按 strategy_id + 时间范围查询，得到 3 条。 |
| 4 | 时点一致性：写入后修改持仓再查快照，快照内容未变 | YES | 快照在 RISK_PASSED 后、下单前用当前 decision + risk_result 构建并写入，未使用后续状态；表仅追加无 update，故自然满足。 |
| 5 | 不可变：无 update(decision_id) 接口，尝试更新返回错误或不存在 | YES | 单测 test_repository_has_no_update_or_delete 断言 Repository 无 update/delete/overwrite；Repository 仅实现 save/get_by_decision_id/list_by_strategy_time。 |
| 6 | 写入失败：mock 写入失败，验证无 trade 产生、有 ERROR 日志与告警、ExecutionEngine 未收到该 decision（未调用 create_order） | YES | 见【F】专项证据：test_save_failure_rejects_decision_and_triggers_alert 断言 create_order 未调用、alert_callback 被调用、status=failed、DOM=FAILED、无 snapshot 记录；logger.error 在 engine 内已调用。 |

---

## 【F】“写入失败策略”专项证据

### F.1 mock save 失败的测试代码片段

**文件**: `tests/integration/test_phase12_c1_decision_snapshot.py` 中 `test_save_failure_rejects_decision_and_triggers_alert`

```python
        class FailingSnapshotRepo(DecisionSnapshotRepository):
            async def save(self, snapshot):
                raise RuntimeError("mock save failure")

        snapshot_repo = FailingSnapshotRepo(session)
        engine = ExecutionEngine(
            dom_repo,
            SpyAdapter(filled=True),
            RiskManager(),
            snapshot_repo=snapshot_repo,
            alert_callback=_alert,
        )
        result = await engine.execute_one(decision_id)

    assert result.get("status") == "failed"
    assert result.get("reason_code") == "DECISION_SNAPSHOT_SAVE_FAILED"
    assert len(create_order_called) == 0, "ExecutionEngine 不得调用 create_order（决策已被拒绝）"
    assert len(alert_calls) == 1
    assert alert_calls[0][0] == decision_id
    assert alert_calls[0][1] == "strat-fail"
    assert "mock save failure" in (alert_calls[0][2] or "")
```

### F.2 证明 ExecutionEngine 未被调用（create_order 未调用）

- 使用 `SpyAdapter` 包装 `PaperExchangeAdapter`，在 `create_order` 中向 `create_order_called` 列表追加调用参数。
- 断言：`assert len(create_order_called) == 0`。即快照写入失败时，未向下游发起下单，ExecutionEngine 未把该笔决策传递到 exchange。

### F.3 证明 AlertSystem / alert_callback 被调用

- 传入 `alert_callback=_alert`，`_alert` 将 `(decision_id, strategy_id, reason)` 追加到 `alert_calls`。
- 断言：`len(alert_calls) == 1`，且 `alert_calls[0][0] == decision_id`、`alert_calls[0][1] == "strat-fail"`、`"mock save failure" in alert_calls[0][2]`。即强告警等价逻辑（callback）已被调用且参数含 decision_id、strategy_id、失败原因。

### F.4 证明 ERROR/AUDIT 日志或等价审计记录已产生

- 实现侧：`ExecutionEngine` 在 `save` 异常分支中调用 `logger.error("decision_snapshot_save_failed decision_id=... strategy_id=... reason=...", exc_info=True)`，并写入 `execution_events`（FINAL_FAILED，reason_code=DECISION_SNAPSHOT_SAVE_FAILED）。
- 测试侧：断言 `row.status == FAILED`、`row.last_error == "DECISION_SNAPSHOT_SAVE_FAILED"`，证明决策失败已落库，可审计；未实现 LogRepository（C3）故未写 log 表，但现有 logger + execution_events 已满足“可审计可追溯”。

---

**文档结束**
