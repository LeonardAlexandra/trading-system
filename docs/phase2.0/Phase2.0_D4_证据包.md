# Phase2.0 D4 证据包（E2E-2.0 报告查询与排序稳定性验证）

## 修改文件清单
- 修改：`src/repositories/evaluation_report_repository.py`
- 修改：`src/application/phase2_main_flow_service.py`
- 新增：`tests/e2e/test_e2e_phase2_report_query.py`
- 新增：`docs/runlogs/phase20_d4_pytest_output.txt`
- 新增：`docs/runlogs/phase20_d4_pytest_output_with_markers.txt`
- 新增：`docs/Phase2.0_D4_证据包.md`

## 查询代码
### src/repositories/evaluation_report_repository.py
```python
"""
Phase2.0 C3/C4：EvaluationReport 仓储

- C3 范围：write(session, report_orm) 仅写入 evaluation_report 表；
- C4 范围：增加只读查询：
  - get_by_strategy_version(strategy_version_id)
  - get_by_evaluated_at(strategy_id, from_ts, to_ts)
  - get_by_param_version(param_version_id)

本仓储仅读写 Phase 2.0 自有表 evaluation_report；
禁止对 Phase 1.2 任何表执行写操作。
This API MUST NOT mutate any Phase 1.2 data.
"""
from datetime import datetime
from typing import List

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.evaluation_report import EvaluationReport


class EvaluationReportRepository:
    """
    评估报告仓储：C3 提供 write，C4 提供只读查询；
    仅读写 Phase 2.0 表 evaluation_report，不读写 Phase 1.2 表。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(self, report: EvaluationReport) -> None:
        """仅写入 evaluation_report 表；不触碰 Phase 1.2 表（蓝本 D.3）。"""
        self.session.add(report)

    async def get_by_strategy_version(
        self,
        strategy_version_id: str,
    ) -> List[EvaluationReport]:
        """
        按 strategy_version_id 查询评估结果列表。
        仅仅读取 evaluation_report。
        """
        stmt = (
            select(EvaluationReport)
            .where(EvaluationReport.strategy_version_id == strategy_version_id)
            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_evaluated_at(
        self,
        strategy_id: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> List[EvaluationReport]:
        """
        按 strategy_id 与 evaluated_at 时间范围查询评估结果。
        仅仅读取 evaluation_report。
        """
        stmt = (
            select(EvaluationReport)
            .where(
                EvaluationReport.strategy_id == strategy_id,
                EvaluationReport.evaluated_at >= from_ts,
                EvaluationReport.evaluated_at <= to_ts,
            )
            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_param_version(
        self,
        param_version_id: str,
    ) -> List[EvaluationReport]:
        """
        按 param_version_id 查询评估结果列表。
        仅仅读取 evaluation_report；baseline_version_id 仍仅引用 strategy_version。
        """
        stmt = (
            select(EvaluationReport)
            .where(EvaluationReport.param_version_id == param_version_id)
            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_baseline_version(
        self,
        baseline_version_id: str,
    ) -> List[EvaluationReport]:
        """
        按 baseline_version_id 查询评估结果列表。
        仅仅读取 evaluation_report；baseline_version_id 仅允许 strategy_version_id。
        """
        stmt = (
            select(EvaluationReport)
            .where(EvaluationReport.baseline_version_id == baseline_version_id)
            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
```

### src/application/phase2_main_flow_service.py（查询入口）
```python
"""
Phase2.0 D1：主流程应用层入口（非 HTTP）。

封装事务边界：strategy/version/time_range -> compute -> evaluate -> commit。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.phase2.evaluation_config import EvaluatorConfig
from src.phase2.evaluation_report_result import EvaluationReportResult
from src.phase2.evaluator import Evaluator
from src.phase2.metrics_calculator import MetricsCalculator
from src.repositories.evaluation_report_repository import EvaluationReportRepository
from src.repositories.metrics_snapshot_repository import MetricsRepository
from src.repositories.trade_repo import TradeRepository


class Phase2MainFlowService:
    """D1 应用层主流程入口，负责会话与事务边界。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def run_main_flow(
        self,
        *,
        strategy_id: str,
        strategy_version_id: str,
        param_version_id: Optional[str],
        period_start: datetime,
        period_end: datetime,
        config: Optional[EvaluatorConfig] = None,
    ) -> EvaluationReportResult:
        async with self._session_factory() as session:
            trade_repo = TradeRepository(session)
            metrics_repo = MetricsRepository(session)
            report_repo = EvaluationReportRepository(session)
            calc = MetricsCalculator(trade_repo)
            evaluator = Evaluator(calc, metrics_repo, report_repo)
            result = await evaluator.evaluate(
                strategy_id=strategy_id,
                strategy_version_id=strategy_version_id,
                param_version_id=param_version_id,
                period_start=period_start,
                period_end=period_end,
                config=config,
            )
            await session.commit()
            return result

    async def query_by_strategy_version(self, strategy_version_id: str):
        async with self._session_factory() as session:
            repo = EvaluationReportRepository(session)
            return await repo.get_by_strategy_version(strategy_version_id)

    async def query_by_evaluated_at(self, strategy_id: str, from_ts: datetime, to_ts: datetime):
        async with self._session_factory() as session:
            repo = EvaluationReportRepository(session)
            return await repo.get_by_evaluated_at(strategy_id, from_ts, to_ts)

    async def query_by_param_version(self, param_version_id: str):
        async with self._session_factory() as session:
            repo = EvaluationReportRepository(session)
            return await repo.get_by_param_version(param_version_id)

    async def query_by_baseline_version(self, baseline_version_id: str):
        async with self._session_factory() as session:
            repo = EvaluationReportRepository(session)
            return await repo.get_by_baseline_version(baseline_version_id)
```

## ORDER BY 语句代码片段
```python
47:            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
69:            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
85:            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
101:            .order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id))
```

## E2E 测试代码
文件：`tests/e2e/test_e2e_phase2_report_query.py`
```python
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.phase2_main_flow_service import Phase2MainFlowService
from src.database.connection import Base
from src.models.decision_snapshot import DecisionSnapshot
from src.models.evaluation_report import EvaluationReport
from src.models.execution_event import ExecutionEvent
from src.models.log_entry import LogEntry
from src.models.trade import Trade
from src.repositories.evaluation_report_repository import EvaluationReportRepository
import src.models  # noqa: F401


def _dt(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


@pytest.fixture
async def d4_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _phase12_counts(session: AsyncSession) -> dict[str, int]:
    return {
        "trade": int((await session.execute(select(func.count()).select_from(Trade))).scalar() or 0),
        "decision_snapshot": int((await session.execute(select(func.count()).select_from(DecisionSnapshot))).scalar() or 0),
        "execution_events": int((await session.execute(select(func.count()).select_from(ExecutionEvent))).scalar() or 0),
        "log": int((await session.execute(select(func.count()).select_from(LogEntry))).scalar() or 0),
    }


@pytest.mark.asyncio
async def test_e2e_phase2_report_query(d4_session_factory):
    service = Phase2MainFlowService(d4_session_factory)
    strategy_id = "D4-STRATEGY"
    strategy_version = "D4-V-1"
    baseline_version = "D4-V-BASE"
    param_version = "D4-P-1"

    t0 = _dt(2025, 4, 1, 10, 0, 0)
    t1 = _dt(2025, 4, 1, 10, 5, 0)
    t2 = _dt(2025, 4, 1, 10, 7, 0)
    t2_same = _dt(2025, 4, 1, 10, 10, 0)

    async with d4_session_factory() as session:
        counts_before = await _phase12_counts(session)
        repo = EvaluationReportRepository(session)
        # 插入 3 条不同 evaluated_at
        rows = [
            EvaluationReport(
                strategy_id=strategy_id,
                strategy_version_id=strategy_version,
                param_version_id=param_version,
                evaluated_at=t0,
                period_start=t0 - timedelta(hours=1),
                period_end=t0,
                objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
                constraint_definition={"max_drawdown_pct": 100.0, "min_trade_count": 1, "max_risk_exposure": 100.0, "custom": None},
                baseline_version_id=baseline_version,
                conclusion="pass",
                comparison_summary={"delta": {"trade_count": 1}},
                metrics_snapshot_id=None,
            ),
            EvaluationReport(
                strategy_id=strategy_id,
                strategy_version_id=strategy_version,
                param_version_id=param_version,
                evaluated_at=t1,
                period_start=t1 - timedelta(hours=1),
                period_end=t1,
                objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
                constraint_definition={"max_drawdown_pct": 100.0, "min_trade_count": 1, "max_risk_exposure": 100.0, "custom": None},
                baseline_version_id=baseline_version,
                conclusion="pass",
                comparison_summary={"delta": {"trade_count": 2}},
                metrics_snapshot_id=None,
            ),
            EvaluationReport(
                strategy_id=strategy_id,
                strategy_version_id=strategy_version,
                param_version_id=param_version,
                evaluated_at=t2,
                period_start=t2 - timedelta(hours=1),
                period_end=t2,
                objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
                constraint_definition={"max_drawdown_pct": 100.0, "min_trade_count": 1, "max_risk_exposure": 100.0, "custom": None},
                baseline_version_id=baseline_version,
                conclusion="pass",
                comparison_summary={"delta": {"trade_count": 2}},
                metrics_snapshot_id=None,
            ),
        ]
        for r in rows:
            await repo.write(r)
        # 插入 2 条同 evaluated_at（排序稳定性）
        same_time_1 = EvaluationReport(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version,
            param_version_id=param_version,
            evaluated_at=t2_same,
            period_start=t2_same - timedelta(hours=1),
            period_end=t2_same,
            objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
            constraint_definition={"max_drawdown_pct": 100.0, "min_trade_count": 1, "max_risk_exposure": 100.0, "custom": None},
            baseline_version_id=baseline_version,
            conclusion="pass",
            comparison_summary={"delta": {"trade_count": 3}},
            metrics_snapshot_id=None,
        )
        same_time_2 = EvaluationReport(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version,
            param_version_id=param_version,
            evaluated_at=t2_same,
            period_start=t2_same - timedelta(hours=1),
            period_end=t2_same,
            objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
            constraint_definition={"max_drawdown_pct": 100.0, "min_trade_count": 1, "max_risk_exposure": 100.0, "custom": None},
            baseline_version_id=baseline_version,
            conclusion="pass",
            comparison_summary={"delta": {"trade_count": 4}},
            metrics_snapshot_id=None,
        )
        await repo.write(same_time_1)
        await repo.write(same_time_2)
        await session.commit()
        same_id_1 = int(same_time_1.id)
        same_id_2 = int(same_time_2.id)

    print("D4_PHASE12_COUNTS_BEFORE=" + json.dumps(counts_before, ensure_ascii=False, sort_keys=True))

    # 查询阶段只读拦截
    phase12_write_sql: list[str] = []
    phase12_tables = ("trade", "decision_snapshot", "execution_events", "log")

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        sql = " ".join((statement or "").strip().split())
        lowered = sql.lower()
        is_write = lowered.startswith("insert") or lowered.startswith("update") or lowered.startswith("delete") or lowered.startswith("replace")
        if is_write and any(f" {tbl} " in f" {lowered} " or f" {tbl}(" in f" {lowered} " for tbl in phase12_tables):
            phase12_write_sql.append(sql)

    event.listen(d4_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        by_strategy = await service.query_by_strategy_version(strategy_version)
        by_time = await service.query_by_evaluated_at(strategy_id, t0 - timedelta(minutes=1), t2_same + timedelta(minutes=1))
        by_param = await service.query_by_param_version(param_version)
        by_baseline = await service.query_by_baseline_version(baseline_version)

        empty_strategy = await service.query_by_strategy_version("D4-NOT-EXIST")
        empty_param = await service.query_by_param_version("D4-P-NOT-EXIST")
        empty_time = await service.query_by_evaluated_at("D4-NOT-EXIST-STRATEGY", t0, t2_same)
    finally:
        event.remove(d4_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)

    print(f"D4_PHASE12_WRITE_SQL_COUNT={len(phase12_write_sql)}")
    assert len(phase12_write_sql) == 0

    # 1) strategy_version 查询
    assert len(by_strategy) == 5
    # 2) evaluated_at 范围查询
    assert len(by_time) == 5
    # 3) param_version 查询
    assert len(by_param) == 5
    # 4) baseline_version 查询
    assert len(by_baseline) == 5
    assert all(r.baseline_version_id == baseline_version for r in by_baseline)

    # 排序稳定性：evaluated_at DESC, id DESC
    expected_same_order = [max(same_id_1, same_id_2), min(same_id_1, same_id_2)]
    same_time_ids = [
        int(r.id)
        for r in by_strategy
        if r.evaluated_at.replace(tzinfo=timezone.utc) == t2_same
    ]
    assert same_time_ids == expected_same_order

    overall_order = [(r.evaluated_at.isoformat(), int(r.id)) for r in by_strategy]
    print("D4_SORTED_RESULTS=" + json.dumps(overall_order, ensure_ascii=False))

    # 空结果边界
    assert empty_strategy == []
    assert empty_param == []
    assert empty_time == []

    # baseline_version_id 合法性未破坏
    assert all(r.baseline_version_id is None or r.baseline_version_id.startswith("D4-V-") for r in by_strategy)

    async with d4_session_factory() as session:
        counts_after = await _phase12_counts(session)
    print("D4_PHASE12_COUNTS_AFTER=" + json.dumps(counts_after, ensure_ascii=False, sort_keys=True))
    assert counts_after == counts_before
```

## pytest 原始输出
### 指定命令
命令：`pytest tests/e2e/test_e2e_phase2_report_query.py`
来源：`docs/runlogs/phase20_d4_pytest_output.txt`
```text
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 1 item

tests/e2e/test_e2e_phase2_report_query.py .                              [100%]

============================== 1 passed in 0.07s ===============================
```

### 含审计输出
命令：`pytest tests/e2e/test_e2e_phase2_report_query.py -s`
来源：`docs/runlogs/phase20_d4_pytest_output_with_markers.txt`
```text
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 1 item

tests/e2e/test_e2e_phase2_report_query.py D4_PHASE12_COUNTS_BEFORE={"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 0}
D4_PHASE12_WRITE_SQL_COUNT=0
D4_SORTED_RESULTS=[["2025-04-01T10:10:00", 5], ["2025-04-01T10:10:00", 4], ["2025-04-01T10:07:00", 3], ["2025-04-01T10:05:00", 2], ["2025-04-01T10:00:00", 1]]
D4_PHASE12_COUNTS_AFTER={"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 0}
.

============================== 1 passed in 0.07s ===============================
```

## 报告样本排序结果
```json
[["2025-04-01T10:10:00", 5], ["2025-04-01T10:10:00", 4], ["2025-04-01T10:07:00", 3], ["2025-04-01T10:05:00", 2], ["2025-04-01T10:00:00", 1]]
```

## Phase1.2 表行数前后对比
- BEFORE
```json
```
- AFTER
```json
{"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 0}
```

## 与 AC 逐条对照说明
- [x] 查询按 strategy_version_id 正确返回（5 条）。
- [x] 查询按 evaluated_at 正确返回（时间范围内 5 条）。
- [x] 查询按 param_version_id 正确返回（5 条）。
- [x] 排序稳定（相同 evaluated_at 的两条记录按 id DESC 稳定排序）。
- [x] 空查询不报错（不存在 strategy_version_id/param_version_id/时间范围均返回空数组）。
- [x] 显式 ORDER BY 存在（repository 查询均含 `order_by(desc(evaluated_at), desc(id))`）。
- [x] 无 Phase 1.2 写操作（`D4_PHASE12_WRITE_SQL_COUNT=0` 且前后行数一致）。
