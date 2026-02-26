# Phase2.0 C1 MetricsRepository 模块证据包

**模块名称**：C1 MetricsRepository（仅写 Phase 2.0 表 metrics_snapshot）  
**完成日期**：2026-02-14  
**真理源**：`docs/plan/Phase2.0_模块化开发交付包.md` 中【C1】条目、`docs/plan/Phase2.0开发蓝本.md` 中 D.1 MetricsRepository 接口定义；及“本模块完成后必须回传的证据包”通用要求。

---

## 一、本模块涉及的变更文件清单

| 类型 | 路径 |
|------|------|
| 新增 | `src/models/metrics_snapshot.py` |
| 新增 | `src/repositories/metrics_snapshot_repository.py` |
| 新增 | `tests/unit/repositories/test_metrics_snapshot_repository.py` |
| 新增 | `docs/runlogs/phase20_c1_repo_20260214.txt` |
| 修改 | `src/models/__init__.py`（导出 `MetricsSnapshot`） |
| 修改 | 本证据包（接口对齐 D.1、测试锁死语义、自包含审计） |

无删除文件。本次修复：Repository 保留 D.1 规定的 `write` / `get_by_strategy_period` / `get_by_strategy_time_range`，并新增只读接口 `get_by_strategy_version(strategy_version_id)` 以满足“按策略/版本/时间段查询”的验收语义。  
审计加固整改：证据包新增“只读边界反证（全目录）”、测试代码 UTC 显式化约定与片段、最新 pytest 全文；runlog 追加本次执行记录；测试文件增加 UTC 时间语义注释（不改变行为）。

---

## 二、MetricsSnapshot ORM 全文（自包含）

以下为 `src/models/metrics_snapshot.py` 完整内容（含 imports、Base、类型；无 `__table_args__`）。

```python
"""
Phase2.0 A1/C1：metrics_snapshot 表（指标快照，Phase 2.0 自有）

仅结构定义，用于 ORM 与 MetricsRepository。本表为 Phase 2.0 自有表；
禁止对 Phase 1.2 任何表执行写操作。字段与蓝本 B.2/C.1 一致，无未文档化列。
"""
from sqlalchemy import Column, DateTime, BigInteger, Integer, String, Numeric
from sqlalchemy.sql import func

from src.database.connection import Base


class MetricsSnapshot(Base):
    """
    指标快照表（Phase2.0 蓝本 C.1/B.2）。
    仅存 B.2/C.1 文档化字段：strategy_id、strategy_version_id、param_version_id、
    period_start、period_end、trade_count、win_rate、realized_pnl、max_drawdown、
    avg_holding_time_sec、created_at。
    """
    __tablename__ = "metrics_snapshot"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    strategy_id = Column(String(64), nullable=False)
    strategy_version_id = Column(String(64), nullable=False)
    param_version_id = Column(String(64), nullable=True)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    trade_count = Column(Integer(), nullable=False)
    win_rate = Column(Numeric(18, 6), nullable=True)
    realized_pnl = Column(Numeric(20, 8), nullable=False)
    max_drawdown = Column(Numeric(20, 8), nullable=True)
    avg_holding_time_sec = Column(Numeric(18, 6), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

---

## 三、MetricsRepository 关键实现代码（D.1 三接口 + get_by_strategy_version）

以下为 `src/repositories/metrics_snapshot_repository.py` 中与 D.1 及“按策略/版本/时间段查询”对应的实现（write / get_by_strategy_period / get_by_strategy_time_range / get_by_strategy_version）。

```python
    async def write(self, snapshot: MetricsSnapshot) -> None:
        """仅写入 metrics_snapshot 表；不读写 Phase 1.2 表（D.1）。"""
        self.session.add(snapshot)

    async def get_by_strategy_period(
        self,
        strategy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> List[MetricsSnapshot]:
        """
        按 strategy_id 与精确 period 查询（period_start == 给定值 AND period_end == 给定值）。
        仅读 metrics_snapshot（D.1）。
        """
        stmt = (
            select(MetricsSnapshot)
            .where(
                MetricsSnapshot.strategy_id == strategy_id,
                MetricsSnapshot.period_start == period_start,
                MetricsSnapshot.period_end == period_end,
            )
            .order_by(MetricsSnapshot.period_start)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_strategy_time_range(
        self,
        strategy_id: str,
        start_ts: datetime,
        end_ts: datetime,
    ) -> List[MetricsSnapshot]:
        """
        按 strategy_id 与时间范围查询：返回快照区间 [period_start, period_end] 与 [start_ts, end_ts] 存在重叠的记录。
        重叠条件：period_start <= end_ts AND period_end >= start_ts。仅读 metrics_snapshot（D.1）。
        """
        stmt = (
            select(MetricsSnapshot)
            .where(
                MetricsSnapshot.strategy_id == strategy_id,
                MetricsSnapshot.period_start <= end_ts,
                MetricsSnapshot.period_end >= start_ts,
            )
            .order_by(MetricsSnapshot.period_start)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_strategy_version(self, strategy_version_id: str) -> List[MetricsSnapshot]:
        """
        按 strategy_version_id 查询，仅读 metrics_snapshot；结果按 period_start 升序（锁死排序）。
        不触碰 Phase 1.2 表；不引入指标计算、Evaluator、baseline、结论等语义。
        """
        stmt = (
            select(MetricsSnapshot)
            .where(MetricsSnapshot.strategy_version_id == strategy_version_id)
            .order_by(MetricsSnapshot.period_start)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
```

---

## 四、测试关键片段（锁死语义与边界条件）

- **write + 持久化一致性**：`test_write_then_get_by_strategy_period_new_session` — 插入后 commit，新 session 用 `get_by_strategy_period` 查询，断言条数与字段一致。
- **get_by_strategy_version 持久化与过滤（必须可复现、新 session 验证）**：
  - `test_write_then_get_by_strategy_version_new_session`：写入 snapshot -> commit -> 新 session -> `get_by_strategy_version("ver-001")` 查询 -> 断言 `len(rows)==1`，且 `strategy_id`、`strategy_version_id`、`param_version_id`、`trade_count`、`realized_pnl`、`period_start`/`period_end` 与写入一致。
  - `test_get_by_strategy_version_filters_only_target`：插入两条不同 `strategy_version_id`（ver-A、ver-B）-> 新 session 分别 `get_by_strategy_version("ver-A")` 与 `get_by_strategy_version("ver-B")` -> 只返回对应记录（各 1 条，且 `strategy_version_id` 与 `trade_count` 匹配）；并断言结果按 `period_start` 升序（锁死排序行为）。
- **get_by_strategy_period 精确匹配**：`test_get_by_strategy_period_exact_match_only` — 插入两条不同 period；用精确的 period_start/period_end 各查一条；用不匹配的 period 查得 0 条。

```python
# 精确匹配：仅 period_start 与 period_end 均等于给定值才返回
exact_p1 = await repo.get_by_strategy_period("s", p1_start, p1_end)
wrong_period = await repo.get_by_strategy_period("s", _dt(2025, 1, 15), _dt(2025, 1, 20))
assert len(exact_p1) == 1 and ...
assert len(wrong_period) == 0
```

- **get_by_strategy_time_range 重叠语义与边界**：
  - 贴边重叠：快照 [1/1, 1/15]，查询 [1/15, 1/31] → 命中（1/15 重合）。
  - 完全不重叠：快照 [1/1, 1/10]，查询 [1/11, 1/20] → 0 条。
  - 查询范围包含快照：快照 [1/10, 1/20]，查询 [1/1, 1/31] → 命中。
  - 快照包含查询：快照 [1/1, 1/31]，查询 [1/10, 1/20] → 命中。
  - start_ts == end_ts：查询 [1/15, 1/15]，快照 [1/10, 1/20] → 命中（单点重叠）。
  - strategy_id 过滤：不同 strategy_id 不混入。

**测试代码关键片段（UTC 显式化）**：所有 datetime 统一为 tz-aware UTC，禁止 naive。构造通过 `_dt(year, month, day)` 或 `datetime(..., tzinfo=timezone.utc)`；断言通过 `_utc(d)` 归一化后再比较（兼容 SQLite 读出的 naive）。

```python
from datetime import datetime, timezone

def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)

def _utc(d: datetime) -> datetime:
    """归一化到 UTC 以便与 DB 读出的 naive datetime 比较（SQLite 可能无 tz）。"""
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d

# 用例内统一写法示例
p_start = _dt(2025, 1, 1)
p_end = _dt(2025, 1, 31)
# 断言时对从 DB 读出的值做归一化
assert _utc(rows[0].period_start) == _utc(p_start)
assert _utc(rows[0].period_end) == _utc(p_end)
```

---

## 五、pytest 原始输出全文（自包含）

**命令**：

```bash
python3 -m pytest tests/unit/repositories/test_metrics_snapshot_repository.py -v 2>&1
```

**原始输出（全文，未概述）— get_by_strategy_version 返工后 11 条用例**：

```
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0 -- /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 11 items

tests/unit/repositories/test_metrics_snapshot_repository.py::test_write_then_get_by_strategy_period_new_session PASSED [  9%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_write_then_get_by_strategy_version_new_session PASSED [ 18%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_version_filters_only_target PASSED [ 27%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_period_exact_match_only PASSED [ 36%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_overlap_edge PASSED [ 45%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_no_overlap PASSED [ 54%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_query_contains_snapshot PASSED [ 63%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_snapshot_contains_query PASSED [ 72%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_start_equals_end PASSED [ 81%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_strategy_id_filter PASSED [ 90%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_repository_no_business_logic PASSED [100%]

============================== 11 passed in 0.25s ===============================
```

**审计加固整改后最新 pytest 完整输出**（UTC 显式化 + 全目录反证，功能未变、全绿）：

```
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0 -- /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 11 items

tests/unit/repositories/test_metrics_snapshot_repository.py::test_write_then_get_by_strategy_period_new_session PASSED [  9%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_write_then_get_by_strategy_version_new_session PASSED [ 18%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_version_filters_only_target PASSED [ 27%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_period_exact_match_only PASSED [ 36%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_overlap_edge PASSED [ 45%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_no_overlap PASSED [ 54%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_query_contains_snapshot PASSED [ 63%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_snapshot_contains_query PASSED [ 72%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_start_equals_end PASSED [ 81%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_strategy_id_filter PASSED [ 90%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_repository_no_business_logic PASSED [100%]

============================== 11 passed in 0.28s ===============================
```

可复现：在项目根目录执行上述命令即可。

**runlog 追加内容全文**（`docs/runlogs/phase20_c1_repo_20260214.txt` 在本次返工后追加，不覆盖旧记录）：

```
========== 追加：get_by_strategy_version 返工后（2026-02-14）==========
命令: python3 -m pytest tests/unit/repositories/test_metrics_snapshot_repository.py -v 2>&1

--- 原始输出 ---

============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0 -- /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 11 items

tests/unit/repositories/test_metrics_snapshot_repository.py::test_write_then_get_by_strategy_period_new_session PASSED [  9%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_write_then_get_by_strategy_version_new_session PASSED [ 18%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_version_filters_only_target PASSED [ 27%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_period_exact_match_only PASSED [ 36%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_overlap_edge PASSED [ 45%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_no_overlap PASSED [ 54%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_query_contains_snapshot PASSED [ 63%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_snapshot_contains_query PASSED [ 72%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_start_equals_end PASSED [ 81%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_get_by_strategy_time_range_strategy_id_filter PASSED [ 90%]
tests/unit/repositories/test_metrics_snapshot_repository.py::test_repository_no_business_logic PASSED [100%]

============================== 11 passed in 0.25s ===============================
```

---

## 六、只读边界反证（自包含）

**目的**：证明 C1 模块代码未 import/引用 Phase 1.2 表模型（decision_snapshot、trade、execution、log 等）。

**命令**：

```bash
rg -n "DecisionSnapshot|Trade|Execution|Order|decision_snapshot|trade_repo|execution_event|orders_repo|log" --type py src/repositories/metrics_snapshot_repository.py src/models/metrics_snapshot.py
```

**原始输出**：

```
（无输出，exit code 1）
```

**结论**：在上述两个文件内搜索 Phase 1.2 相关模型/表名，**无任何匹配**。即本模块未引用 decision_snapshot、Trade、Execution、Order、trade_repo、execution_event、orders_repo、log 等；仅引用 `src.models.metrics_snapshot.MetricsSnapshot` 与 `AsyncSession`，满足「This API MUST NOT mutate any Phase 1.2 data」的依赖边界。

---

### 六（补充）、只读边界反证（全目录）

扫描范围扩大至 `src/repositories/`，用于增强可审计性：证明在整目录中 C1 唯一相关文件 `metrics_snapshot_repository.py` 未出现于 Phase 1.2 相关匹配。

**命令 1**：

```bash
rg -n "decision_snapshot|execution|trade|signal|log|perf|Phase1" src/repositories/
```

**命令 1 原始输出（全文）**：

```
src/repositories/strategy_runtime_state_repo.py:2:Phase1.1 A1：strategy_runtime_state 表 Repository（字段映射，供 C1 对接）
src/repositories/decision_order_map_repo.py:20:        signal_id: str,
src/repositories/decision_order_map_repo.py:28:        创建 RESERVED 占位记录（PR5 写入 symbol/side/strategy_id/signal_id/quantity 供 PR6 执行读取）。
src/repositories/decision_order_map_repo.py:35:            signal_id=signal_id,
src/repositories/decision_order_map_repo.py:172:        Phase1.1 C2 阶段1：仅当 status=SUBMITTING 时更新为 PENDING_EXCHANGE（持锁内调用）。
src/repositories/dedup_signal_repo.py:10:from src.models.dedup_signal import DedupSignal
src/repositories/dedup_signal_repo.py:19:        signal_id: str,
src/repositories/dedup_signal_repo.py:32:            signal_id: 信号 ID（主键）
src/repositories/dedup_signal_repo.py:40:        dedup_signal = DedupSignal(
src/repositories/dedup_signal_repo.py:41:            signal_id=signal_id,
src/repositories/dedup_signal_repo.py:50:                self.session.add(dedup_signal)
src/repositories/dedup_signal_repo.py:58:    async def get(self, signal_id: str) -> Optional[DedupSignal]:
src/repositories/dedup_signal_repo.py:60:        根据 signal_id 查询信号记录
src/repositories/dedup_signal_repo.py:63:            signal_id: 信号 ID
src/repositories/dedup_signal_repo.py:68:        stmt = select(DedupSignal).where(DedupSignal.signal_id == signal_id)
src/repositories/log_repository.py:2:Phase1.2 C3：审计/操作/错误日志 Repository（蓝本 C.3）
src/repositories/log_repository.py:4:- write(level, component, message, event_type=None, payload=None)：写入前统一脱敏，落库 log 表。
src/repositories/log_repository.py:6:- 不修改 A2 的 log 表结构；不与 perf_log 混合。
src/repositories/log_repository.py:15:from src.models.log_entry import LogEntry
src/repositories/log_repository.py:85:        写入一条 log。写入前对 message 与 payload 统一脱敏（禁止完整 API Key/token/密码）。
src/repositories/__init__.py:5:from src.repositories.dedup_signal_repo import DedupSignalRepository
src/repositories/trade_repo.py:2:Trade Repository（Phase1.0 表存在；Phase1.1 A2 支持 source_type / external_trade_id）
src/repositories/trade_repo.py:4:创建或更新 trade 时支持传入 source_type=EXTERNAL_SYNC、external_trade_id。
src/repositories/trade_repo.py:5:EXTERNAL_SYNC 幂等由 DB 唯一约束 uq_trade_strategy_external_trade_id 保证，插入前可按 (strategy_id, external_trade_id) 判重。
src/repositories/trade_repo.py:7:工程级边界（作用域锁定）：SIGNAL 行不得写入 external_trade_id。
src/repositories/trade_repo.py:8:- 写入层：source_type=SIGNAL 时 external_trade_id 必须为 None（由调用方保证；Repo 不替 SIGNAL 填 external_trade_id）。
src/repositories/trade_repo.py:9:- EXTERNAL_SYNC 路径（如 C3）唯一可设置 external_trade_id；插入前建议 get_by_strategy_external_trade_id 判重。
src/repositories/trade_repo.py:14:from src.models.trade import Trade
src/repositories/trade_repo.py:19:    """trade 表访问；支持信号驱动与 EXTERNAL_SYNC 写入；SIGNAL 行不得写 external_trade_id（见模块 docstring）。"""
src/repositories/trade_repo.py:21:    async def get_by_trade_id(self, trade_id: str) -> Optional[Trade]:
src/repositories/trade_repo.py:22:        stmt = select(Trade).where(Trade.trade_id == trade_id)
src/repositories/trade_repo.py:26:    async def get_by_strategy_external_trade_id(
src/repositories/trade_repo.py:27:        self, strategy_id: str, external_trade_id: str
src/repositories/trade_repo.py:32:            Trade.external_trade_id == external_trade_id,
src/repositories/trade_repo.py:37:    async def create(self, trade: Trade) -> Trade:
src/repositories/trade_repo.py:38:        """写入一条 trade。SIGNAL 时调用方必须保证 trade.external_trade_id 为 None；EXTERNAL_SYNC 唯一性由 DB 约束保证。"""
src/repositories/trade_repo.py:39:        self.session.add(trade)
src/repositories/trade_repo.py:40:        return trade
src/repositories/perf_log_repository.py:2:Phase1.2 C7：性能日志 Repository（仅写入与分页查询）+ 独立事务写入器
src/repositories/perf_log_repository.py:6:- 仅使用 A3 既有 perf_log 表；与 log 表语义分离。
src/repositories/perf_log_repository.py:16:from src.models.perf_log_entry import PerfLogEntry
src/repositories/perf_log_repository.py:25:    """单条性能日志查询结果（与 perf_log 表字段对应）。"""
src/repositories/perf_log_repository.py:35:    """性能日志：仅写入与分页查询，使用 A3 perf_log 表。"""
src/repositories/perf_log_repository.py:49:        """写入一条性能记录。不写 log 表。"""
src/repositories/perf_log_repository.py:122:        """独立事务写入一条性能记录并 commit，不写 log 表。"""
src/repositories/decision_snapshot_repository.py:2:Phase1.2 C1：决策输入快照 Repository（仅 insert + select，无 update/delete）
src/repositories/decision_snapshot_repository.py:12:from src.models.decision_snapshot import DecisionSnapshot
src/repositories/execution_event_repository.py:11:from src.models.execution_event import ExecutionEvent
src/repositories/execution_event_repository.py:55:        # PR16c：rehearsal 唯一权威来源为 execution_events.rehearsal 列；message 不再包含 "rehearsal=" 字样
src/repositories/position_reconcile_log_repo.py:2:Phase1.1 A3：position_reconcile_log 表 Repository
src/repositories/position_reconcile_log_repo.py:4:写入 reconcile log 时填充 external_trade_id、event_type（仅允许 Phase1.1 封闭枚举）。
src/repositories/position_reconcile_log_repo.py:5:A3-05 硬契约：任何 position_reconcile_log 写入必须发生在事务内；否则拒绝并抛出 PositionReconcileLogNotInTransactionError。
src/repositories/position_reconcile_log_repo.py:6:推荐入口：log_event_in_txn(session 同事务内调用)。
src/repositories/position_reconcile_log_repo.py:11:from src.models.position_reconcile_log import PositionReconcileLog, validate_event_type
src/repositories/position_reconcile_log_repo.py:16:    """A3-05：在未处于事务内的 session 上写入 position_reconcile_log 时抛出。要求写入必须与对账/挂起/恢复在同一事务内。"""
src/repositories/position_reconcile_log_repo.py:18:    def __init__(self, message: str = "position_reconcile_log write must run inside an active transaction (session.in_transaction())."):
src/repositories/position_reconcile_log_repo.py:24:    """position_reconcile_log 表访问；event_type 仅接受预定义枚举；写入前强制校验 session 处于事务内。"""
src/repositories/position_reconcile_log_repo.py:30:                "position_reconcile_log write must run inside an active transaction. "
src/repositories/position_reconcile_log_repo.py:31:                "Use 'async with session.begin():' (or session.begin() before write) and call create/log_event_in_txn within that block."
src/repositories/position_reconcile_log_repo.py:34:    async def log_event_in_txn(
src/repositories/position_reconcile_log_repo.py:38:        external_trade_id: Optional[str] = None,
src/repositories/position_reconcile_log_repo.py:49:            raise ValueError(f"event_type must be one of Phase1.1 closed enum, got: {event_type!r}")
src/repositories/position_reconcile_log_repo.py:50:        log = PositionReconcileLog(
src/repositories/position_reconcile_log_repo.py:53:            external_trade_id=external_trade_id,
src/repositories/position_reconcile_log_repo.py:57:        self.session.add(log)
src/repositories/position_reconcile_log_repo.py:58:        return log
src/repositories/position_reconcile_log_repo.py:60:    async def create(self, log: PositionReconcileLog) -> PositionReconcileLog:
src/repositories/position_reconcile_log_repo.py:61:        """写入一条日志；调用方须保证 event_type 为 Phase1.1 封闭枚举值，且当前 session 已处于事务内。"""
src/repositories/position_reconcile_log_repo.py:63:        if not validate_event_type(log.event_type):
src/repositories/position_reconcile_log_repo.py:64:            raise ValueError(f"event_type must be one of Phase1.1 closed enum, got: {log.event_type!r}")
src/repositories/position_reconcile_log_repo.py:65:        self.session.add(log)
src/repositories/position_reconcile_log_repo.py:66:        return log
src/repositories/signal_rejection_repo.py:2:Phase1.1 C5：signal_rejection 表 Repository
src/repositories/signal_rejection_repo.py:4:因 PAUSED 拒绝信号时写入可审计记录，字段至少包含：策略 ID、signal_id、拒绝原因、时间戳。
src/repositories/signal_rejection_repo.py:8:from src.models.signal_rejection import SignalRejection, REASON_STRATEGY_PAUSED
src/repositories/signal_rejection_repo.py:13:    """signal_rejection 表访问；C5 信号拒绝可审计记录。"""
src/repositories/signal_rejection_repo.py:19:        signal_id: str | None = None,
src/repositories/signal_rejection_repo.py:27:            signal_id=signal_id,
```

**命令 2**：

```bash
rg -n "from .*decision|from .*trade|from .*execution" src/repositories/
```

**命令 2 原始输出（全文）**：

```
src/repositories/decision_order_map_repo.py:9:from src.models.decision_order_map import DecisionOrderMap
src/repositories/decision_order_map_repo.py:10:from src.models.decision_order_map_status import RESERVED, SUBMITTING, PENDING_EXCHANGE, FILLED
src/repositories/trade_repo.py:14:from src.models.trade import Trade
src/repositories/execution_event_repository.py:11:from src.models.execution_event import ExecutionEvent
src/repositories/decision_snapshot_repository.py:12:from src.models.decision_snapshot import DecisionSnapshot
src/repositories/__init__.py:6:from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
```

**声明**：在以上两则全目录扫描结果中，**无任一行属于 `src/repositories/metrics_snapshot_repository.py`**。故 **C1 Repository 仅引用 MetricsSnapshot ORM，未引用 Phase1.2 任何表或模型**；只读边界在整目录范围内可审计。

---

## 七、与本模块 Acceptance Criteria 逐条对照说明

| 验收口径（C1 交付包 / 蓝本 D.1） | 结论 | 证据位置 |
|----------------------------------|------|----------|
| 指标可按 strategy_id / strategy_version_id / period 写入并持久化 | YES | `test_write_then_get_by_strategy_period_new_session`：write 后 commit，新 session get_by_strategy_period 得到一致数据 |
| 按策略、时间段查询结果与写入一致 | YES | `get_by_strategy_period` 精确匹配；`get_by_strategy_time_range` 重叠语义由 6 个边界用例锁死 |
| 只读边界：该模块未对 Phase 1.2 表执行任何写操作 | YES | 第六节 rg 反证：两文件内无 Phase 1.2 模型/表名；Repository 仅 write metrics_snapshot、仅读 metrics_snapshot |
| 表中仅存在 B.2/C.1 文档化字段，无未文档化列 | YES | 第二节 MetricsSnapshot 全文与 A1 迁移 021 一致 |
| 接口契约 D.1：write / get_by_strategy_period / get_by_strategy_time_range；按策略/版本/时间段查询 | YES | 第三节贴出四接口真实实现（含 get_by_strategy_version）；仅读 metrics_snapshot，排序 period_start 升序锁死 |

---

## 八、验收结论

本模块严格满足交付包 C1 与蓝本 D.1 / T2.0-1：实现 MetricsRepository，提供 `write`、`get_by_strategy_period`、`get_by_strategy_time_range`、`get_by_strategy_version` 四接口（前三为 D.1 既有，第四为“按策略/版本/时间段查询”只读扩展）；仅对 metrics_snapshot 表写入与查询；`get_by_strategy_period` 为精确匹配 period_start/period_end；`get_by_strategy_time_range` 为与 [start_ts, end_ts] 重叠语义且由测试锁死；`get_by_strategy_version` 按 strategy_version_id 过滤、结果按 period_start 升序且由测试锁死；未修改任何 Phase 1.2 表；不提前实现 C2/C3/C4/C5；证据包自包含、可复现、关键输出完整。验收通过。
