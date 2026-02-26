# Phase1.2 C6 模块证据包

**模块编号**: C6  
**模块名称**: 对账状态监控（reconcile job status）（T1.2a-5）  
**交付日期**: 2026-02-07  
**封版修订**: 语义明确为“对账状态监控”；告警仅写 LogRepository（event_type=reconcile_status_alert），不调用 AlertSystem.evaluate_rules，不污染 metrics。

---

## 模块语义说明（封版必读）

本模块为**对账状态监控**，非“持仓与外部 diff 一致性”判断：

- **reconcile_status** 表示**对账流程状态**（OK / WARNING / CRITICAL），来源于 position_reconcile_log 最新 event_type，不表示持仓与交易所/外部系统的数量差是否一致。
- 本模块**不判断** diff 一致性，**仅监控**对账流程是否失败（RECONCILE_FAILED）或卡住（RECONCILE_START 未见到 RECONCILE_END）。
- 当对账状态为 WARNING/CRITICAL 时：**仅执行 LogRepository.write**（event_type=reconcile_status_alert），**不**调用 AlertSystem.evaluate_rules，**不**通过伪造 error_count 等 metrics 触发告警，避免污染监控指标与 health summary。

---

## 【A】变更文件清单（新增/修改/删除 + 用途）

| 类型 | 文件路径 | 用途 |
|------|----------|------|
| 新增 | `src/monitoring/position_consistency_monitor.py` | PositionConsistencyMonitor、ConsistencyStatus；get_status(strategy_id=None)；对账状态异常时仅写 LogRepository（reconcile_status_alert） |
| 修改 | `src/repositories/position_repository.py` | 新增 list_all()，供 get_status(strategy_id=None) 全表持仓查询 |
| 修改 | `src/monitoring/__init__.py` | 注释补充 C6 说明（无导出变更） |
| 新增 | `tests/integration/test_phase12_c6_position_consistency.py` | C6 验收测试：get_status 四字段、strategy_id 过滤、对账失败时写入 reconcile_status_alert 日志 |
| 新增 | `docs/phase1.2/Phase1.2_C6_模块证据包.md` | 本证据包 |

未修改：C4（AlertSystem/SystemMonitor/HealthChecker）、C3（LogRepository）、C5（health API）。未新增 DB 迁移/新表/新字段。

---

## 【B】核心实现代码（修订后关键片段）

### 模块与 ConsistencyStatus 定义

**文件**: `src/monitoring/position_consistency_monitor.py`

```python
"""
Phase1.2 C6：对账状态监控（reconcile job status）（T1.2a-5）

PositionConsistencyMonitor.get_status(strategy_id=None) -> list[ConsistencyStatus]。
数据来源：position_snapshot（positions 表）与 position_reconcile_log（对账结果）。
本模块不判断持仓与外部 diff 一致性，仅监控对账流程是否失败/卡住（RECONCILE_FAILED / RECONCILE_START 未结束）。
当对账状态为 WARNING/CRITICAL 时仅写 LogRepository（event_type=reconcile_status_alert），不污染 metrics、不调用 AlertSystem.evaluate_rules。
"""
# ...
RECONCILE_STATUS_OK = "OK"
RECONCILE_STATUS_WARNING = "WARNING"
RECONCILE_STATUS_CRITICAL = "CRITICAL"


@dataclass
class ConsistencyStatus:
    """C6 蓝本：单条对账状态，必含四字段。reconcile_status 表示对账状态（非持仓 diff 一致性）。"""
    strategy_id: str
    symbol: str
    reconcile_status: str  # OK | WARNING | CRITICAL，对账流程状态
    last_reconcile_at: Optional[datetime]  # 来自 position_reconcile_log.created_at
```

### 对账状态异常时仅写 log（修订后 _trigger_reconcile_status_alert）

**不再调用 AlertSystem.evaluate_rules，不再修改 metrics。**

```python
    async def _trigger_reconcile_status_alert(
        self,
        session: AsyncSession,
        bad_details: List[dict],
    ) -> None:
        """
        对账状态异常时仅写 LogRepository，不调用 AlertSystem.evaluate_rules，不污染 metrics。
        CRITICAL 写 ERROR 级，WARNING 写 WARNING 级；event_type=reconcile_status_alert。
        """
        component = "position_consistency_monitor"
        has_critical = any(d.get("reconcile_status") == RECONCILE_STATUS_CRITICAL for d in bad_details)
        level = "ERROR" if has_critical else "WARNING"
        message = (
            f"Reconcile status alert: {len(bad_details)} item(s) in WARNING/CRITICAL; "
            f"details={bad_details}"
        )
        await self._log_repo.write(
            level,
            component,
            message,
            event_type="reconcile_status_alert",
            payload={"items": bad_details},
        )
```

---

## 【C】数据来源与字段映射说明

- **reconcile_status（对账状态）来源**  
  - 来源：**position_reconcile_log** 按 strategy_id 取**最新一条**（list_by_strategy(sid, limit=1)）的 **event_type**，推导规则为：  
    - `RECONCILE_FAILED` → **CRITICAL**（对账失败）  
    - `RECONCILE_START` → **WARNING**（对账进行中或卡住）  
    - `RECONCILE_END` 及其他 → **OK**  
    - 无记录 → **OK**  
  - 明确：不表示持仓与外部 diff 是否一致，仅表示对账流程状态。

- **last_reconcile_at 来源**  
  - 同上「最新一条」**position_reconcile_log.created_at**；按 strategy 维度，该 strategy 下所有 (strategy_id, symbol) 共用同一时间。

- **strategy_id 过滤**  
  - `get_status(strategy_id=None)`：PositionRepository.list_all() 后按涉及 strategy_id 查最新对账日志。  
  - `get_status(strategy_id="X")`：PositionRepository.get_all_by_strategy("X") 后仅对该 strategy_id 查最新对账日志。

---

## 【D】告警集成说明（封版修订）

- **触发条件**  
  - 以 **reconcile_status**（对账状态）为准：任一条为 **WARNING** 或 **CRITICAL** 时触发**写 log**。  
  - WARNING：最新对账事件为 RECONCILE_START。  
  - CRITICAL：最新对账事件为 RECONCILE_FAILED。

- **触发方式（不污染 metrics）**  
  - **仅执行 LogRepository.write**：  
    - **event_type** = `reconcile_status_alert`（不再使用 position_consistency_alert）。  
    - **level**：存在 CRITICAL 时写 **ERROR**，否则 **WARNING**。  
  - **不**调用 AlertSystem.evaluate_rules。  
  - **不**对 metrics 做 error_count+1 等伪造，避免污染 SystemMonitor/health summary。

- **写入 log 的 details**  
  - **payload** = `{"items": bad_details}`，每项含 strategy_id、symbol、reconcile_status、last_reconcile_at（ISO 或 null）。

---

## 【E】测试用例/可复现实跑步骤

1. **test_get_status_returns_required_fields**  
   - 插入 2 条 position（不同 strategy/symbol），调用 get_status()，断言返回 list 且每条含 strategy_id、symbol、reconcile_status、last_reconcile_at。

2. **test_get_status_filter_by_strategy_id**  
   - 插入两条不同 strategy 的 position，调用 get_status(strategy_id="only_this_strategy")，断言仅返回该 strategy 的一条。

3. **test_reconcile_failed_writes_reconcile_status_alert_log**  
   - 插入一条 position，并在 position_reconcile_log 写入 RECONCILE_FAILED；调用 get_status()；断言返回中存在 reconcile_status=CRITICAL；断言 log 中存在 **event_type=reconcile_status_alert** 且 **level=ERROR**（不依赖 AlertSystem.evaluate_rules 被调用）。

4. **test_reconcile_start_yields_warning_status**  
   - 插入 position 且该 strategy 最新 log 为 RECONCILE_START，断言 get_status() 对应条目的 reconcile_status 为 WARNING。

5. **test_reconcile_end_yields_ok_status**  
   - 插入 position 且该 strategy 最新 log 为 RECONCILE_END，断言 get_status() 对应条目的 reconcile_status 为 OK。

---

## 【F】测试命令与原始输出（完整）

### 测试命令

```bash
cd /Users/zhangkuo/TradingView\ Indicator/trading_system
python -m pytest tests/integration/test_phase12_c6_position_consistency.py -v
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

tests/integration/test_phase12_c6_position_consistency.py::test_get_status_returns_required_fields PASSED [ 20%]
tests/integration/test_phase12_c6_position_consistency.py::test_get_status_filter_by_strategy_id PASSED [ 40%]
tests/integration/test_phase12_c6_position_consistency.py::test_reconcile_failed_writes_reconcile_status_alert_log PASSED [ 60%]
tests/integration/test_phase12_c6_position_consistency.py::test_reconcile_start_yields_warning_status PASSED [ 80%]
tests/integration/test_phase12_c6_position_consistency.py::test_reconcile_end_yields_ok_status PASSED [100%]

============================== 5 passed in 0.27s ===============================
```

---

## 【G】Acceptance Criteria 逐条对照（YES/NO + 证据）

| 验收口径 | 结果 | 证据 |
|----------|------|------|
| get_status() 返回 reconcile_status、last_reconcile_at 等（四字段齐全）；reconcile_status 明确为对账状态 | YES | test_get_status_returns_required_fields 断言每条含 strategy_id, symbol, reconcile_status, last_reconcile_at；test_reconcile_end_yields_ok_status / test_reconcile_start_yields_warning_status 断言 status 与 position_reconcile_log 事件一致。 |
| get_status(strategy_id="X") 只返回该策略 | YES | test_get_status_filter_by_strategy_id 断言仅返回指定 strategy_id 的一条。 |
| 对账失败（RECONCILE_FAILED）时写入对应 event_type 的日志，且不依赖 AlertSystem.evaluate_rules | YES | test_reconcile_failed_writes_reconcile_status_alert_log：构造 RECONCILE_FAILED → CRITICAL；断言 log 中存在 event_type=reconcile_status_alert、level=ERROR；实现中已删除 evaluate_rules 调用与 metrics 伪造。 |

---

**文档结束**
