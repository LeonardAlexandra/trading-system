# Phase2.0 D1 证据包（E2E-2.0 主流程可验证点）

## 模块名称与目标
- 模块：D1（E2E-2.0 主流程可验证点）
- 目标：strategy + version + time_range → MetricsCalculator.compute → Evaluator.evaluate → 报告持久化 → 报告查询闭环。

## 修改/新增文件清单
- 新增：`src/application/phase2_main_flow_service.py`
- 修改：`src/application/__init__.py`
- 修改：`tests/e2e/test_e2e_phase2_main_flow.py`
- 更新：`docs/runlogs/phase20_d1_pytest_output.txt`
- 更新：`docs/runlogs/phase20_d1_pytest_output_with_markers.txt`
- 更新：`docs/Phase2.0_D1_证据包.md`

## 入口形态说明（任务2-B）
- 当前项目未提供 Phase2.0 主流程 HTTP 路由（`src/app/main.py` 仅注册 webhook/resume/trace/health/dashboard/audit）。
- 依据 D1 真理源可验证点，闭环定义为 `compute -> evaluate -> 持久化 -> 查询`，未要求 HTTP 形态；因此采用应用层 Service/UseCase 入口承载。
- 新增入口：`Phase2MainFlowService.run_main_flow(...)`，在入口层统一管理 `session` 与 `commit` 事务边界。

## 核心实现代码
### src/application/phase2_main_flow_service.py
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
```

### tests/e2e/test_e2e_phase2_main_flow.py
```python
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.phase2_main_flow_service import Phase2MainFlowService
from src.database.connection import Base
from src.models.decision_snapshot import DecisionSnapshot
from src.models.execution_event import ExecutionEvent
from src.models.log_entry import LogEntry
from src.models.trade import Trade
from src.phase2.evaluation_config import EvaluatorConfig
from src.phase2.metrics_calculator import MetricsCalculator
from src.repositories.trade_repo import TradeRepository
import src.models  # noqa: F401


def _dt(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


@pytest.fixture
async def d1_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_phase12_data(session: AsyncSession, strategy_id: str) -> None:
    repo = TradeRepository(session)
    rows = [
        Trade(
            trade_id="D1-T1",
            strategy_id=strategy_id,
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            realized_pnl=Decimal("100"),
            executed_at=_dt(2025, 1, 10, 9, 0),
        ),
        Trade(
            trade_id="D1-T2",
            strategy_id=strategy_id,
            symbol="BTCUSDT",
            side="SELL",
            quantity=Decimal("1"),
            price=Decimal("51000"),
            realized_pnl=Decimal("20"),
            executed_at=_dt(2025, 1, 15, 9, 0),
        ),
        Trade(
            trade_id="D1-T3",
            strategy_id=strategy_id,
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("49000"),
            realized_pnl=Decimal("-40"),
            executed_at=_dt(2025, 1, 20, 9, 0),
        ),
    ]
    for row in rows:
        await repo.create(row)
    await session.commit()


async def _phase12_counts(session: AsyncSession) -> dict[str, int]:
    return {
        "trade": int((await session.execute(select(func.count()).select_from(Trade))).scalar() or 0),
        "decision_snapshot": int((await session.execute(select(func.count()).select_from(DecisionSnapshot))).scalar() or 0),
        "execution_events": int((await session.execute(select(func.count()).select_from(ExecutionEvent))).scalar() or 0),
        "log": int((await session.execute(select(func.count()).select_from(LogEntry))).scalar() or 0),
    }


@pytest.mark.asyncio
async def test_e2e_phase2_main_flow(d1_session_factory):
    strategy_id = "D1-STRATEGY"
    strategy_version_id = "D1-V1"
    param_version_id = "D1-P1"
    period_start = _dt(2025, 1, 1)
    period_end = _dt(2025, 1, 31, 23, 59)

    # seed（不计入拦截区间）
    async with d1_session_factory() as session:
        await _seed_phase12_data(session, strategy_id)
        counts_before = await _phase12_counts(session)
    print("D1_PHASE12_COUNTS_BEFORE=" + json.dumps(counts_before, ensure_ascii=False, sort_keys=True))

    # 先独立验证 MetricsCalculator.compute（B.2 五指标）
    async with d1_session_factory() as session:
        calc = MetricsCalculator(TradeRepository(session))
        metrics = await calc.compute(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            period_start=period_start,
            period_end=period_end,
        )
        assert metrics.trade_count == 3
        assert metrics.win_rate is not None
        assert metrics.realized_pnl is not None
        assert metrics.max_drawdown is not None
        # B.2 已声明：trade 缺少 open/close 时间字段时 avg_holding_time_sec 为 NULL
        assert metrics.avg_holding_time_sec is None

    # D1 主流程入口（应用层 Service/UseCase，包含事务边界）
    service = Phase2MainFlowService(d1_session_factory)
    cfg = EvaluatorConfig(
        objective_definition={
            "primary": "pnl",
            "primary_weight": 1.0,
            "secondary": [],
            "secondary_weights": [],
        },
        constraint_definition={
            "max_drawdown_pct": 1000,
            "min_trade_count": 1,
            "max_risk_exposure": None,
            "custom": None,
        },
        baseline_version_id=None,
    )

    # 主流程期间：Phase1.2 写入拦截器（compute 开始 -> evaluate+commit 结束）
    write_statements: list[str] = []
    phase12_write_violations: list[str] = []
    phase12_tables = ("trade", "decision_snapshot", "execution_events", "log")

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        sql = " ".join((statement or "").strip().split())
        lowered = sql.lower()
        if lowered.startswith("insert") or lowered.startswith("update") or lowered.startswith("delete") or lowered.startswith("replace"):
            write_statements.append(sql)
            if any(f" {tbl} " in f" {lowered} " or f" {tbl}(" in f" {lowered} " for tbl in phase12_tables):
                phase12_write_violations.append(sql)

    event.listen(d1_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        result = await service.run_main_flow(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            period_start=period_start,
            period_end=period_end,
            config=cfg,
        )
    finally:
        event.remove(d1_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)

    print(f"D1_PHASE12_WRITE_SQL_COUNT={len(phase12_write_violations)}")
    print(f"D1_TOTAL_WRITE_SQL_DURING_FLOW={len(write_statements)}")
    assert len(phase12_write_violations) == 0, "Phase1.2 write SQL detected during main flow"

    # 报告查询（三维）
    by_version = await service.query_by_strategy_version(strategy_version_id)
    by_time = await service.query_by_evaluated_at(
        strategy_id=strategy_id,
        from_ts=result.evaluated_at - timedelta(minutes=1),
        to_ts=result.evaluated_at + timedelta(minutes=1),
    )
    by_param = await service.query_by_param_version(param_version_id)
    print(
        "D1_QUERY_COUNTS="
        + json.dumps(
            {"strategy_version": len(by_version), "evaluated_at": len(by_time), "param_version": len(by_param)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    assert len(by_version) >= 1
    assert len(by_time) >= 1
    assert len(by_param) >= 1

    report = by_param[-1]
    sample = {
        "strategy_id": report.strategy_id,
        "strategy_version_id": report.strategy_version_id,
        "param_version_id": report.param_version_id,
        "evaluated_at": report.evaluated_at.isoformat(),
        "objective_definition": report.objective_definition,
        "constraint_definition": report.constraint_definition,
        "baseline_version_id": report.baseline_version_id,
        "conclusion": report.conclusion,
        "comparison_summary": report.comparison_summary,
    }
    print("D1_REPORT_SAMPLE_JSON=" + json.dumps(sample, ensure_ascii=False, sort_keys=True))

    # 0.2 Contract + 语义约束
    assert report.objective_definition is not None
    assert report.constraint_definition is not None
    assert report.baseline_version_id is None or report.baseline_version_id == strategy_version_id
    assert report.baseline_version_id != param_version_id
    assert report.conclusion is not None
    assert "建议参数" not in report.conclusion
    assert "写回" not in report.conclusion
    assert "优化" not in report.conclusion
    if report.comparison_summary is not None:
        s = json.dumps(report.comparison_summary, ensure_ascii=False)
        assert "建议参数" not in s
        assert "写回" not in s
        assert "优化" not in s

    async with d1_session_factory() as session:
        counts_after = await _phase12_counts(session)
    print("D1_PHASE12_COUNTS_AFTER=" + json.dumps(counts_after, ensure_ascii=False, sort_keys=True))
    assert counts_after == counts_before
```

## Phase1.2 只读边界强反证（任务1）
- seed 完成后开启 `before_cursor_execute` 写入拦截器。
- 拦截覆盖区间：`compute` 开始到 `evaluate + commit` 结束（入口 `run_main_flow` 全程）。
- 违规判定：SQL 以 `INSERT/UPDATE/DELETE/REPLACE` 开头且命中 Phase1.2 关键表（trade/decision_snapshot/execution_events/log）即违规。
- 结果：`D1_PHASE12_WRITE_SQL_COUNT=0`（主流程期间 Phase1.2 写 SQL 为 0）。

## B.2 五指标口径锁定（任务3）
- 文档依据（真理源）明确：`avg_holding_time_sec = AVG(close_time-open_time)，无 trade 或缺少时间字段时为 NULL`。
- 当前 `trade` 模型无 `open_time/close_time` 字段，因此 D1 测试锁死 `assert metrics.avg_holding_time_sec is None`，并在用例注释写明原因。

## pytest 原始输出
### 1) 指定命令
命令：`pytest tests/e2e/test_e2e_phase2_main_flow.py`
来源：`docs/runlogs/phase20_d1_pytest_output.txt`
```text
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 1 item

tests/e2e/test_e2e_phase2_main_flow.py .                                 [100%]

============================== 1 passed in 0.06s ===============================
```

### 2) 含审计输出（-s）
命令：`pytest tests/e2e/test_e2e_phase2_main_flow.py -s`
来源：`docs/runlogs/phase20_d1_pytest_output_with_markers.txt`
```text
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 1 item

tests/e2e/test_e2e_phase2_main_flow.py D1_PHASE12_COUNTS_BEFORE={"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 3}
D1_PHASE12_WRITE_SQL_COUNT=0
D1_TOTAL_WRITE_SQL_DURING_FLOW=2
D1_QUERY_COUNTS={"evaluated_at": 1, "param_version": 1, "strategy_version": 1}
D1_REPORT_SAMPLE_JSON={"baseline_version_id": null, "comparison_summary": null, "conclusion": "pass", "constraint_definition": {"custom": null, "max_drawdown_pct": 1000, "max_risk_exposure": null, "min_trade_count": 1}, "evaluated_at": "2026-02-26T08:04:41.306345", "objective_definition": {"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []}, "param_version_id": "D1-P1", "strategy_id": "D1-STRATEGY", "strategy_version_id": "D1-V1"}
D1_PHASE12_COUNTS_AFTER={"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 3}
.

============================== 1 passed in 0.06s ===============================
```

## 报告样本 JSON
```json
{"baseline_version_id": null, "comparison_summary": null, "conclusion": "pass", "constraint_definition": {"custom": null, "max_drawdown_pct": 1000, "max_risk_exposure": null, "min_trade_count": 1}, "evaluated_at": "2026-02-26T08:04:41.306345", "objective_definition": {"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []}, "param_version_id": "D1-P1", "strategy_id": "D1-STRATEGY", "strategy_version_id": "D1-V1"}
```

## 查询结果数量（-s 原始输出）
```json
{"evaluated_at": 1, "param_version": 1, "strategy_version": 1}
```

## Phase1.2 表行数前后对比
- BEFORE
```json
{"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 3}
```
- AFTER
```json
{"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 3}
```

## 写入拦截统计（-s 原始输出）
```text
D1_PHASE12_WRITE_SQL_COUNT=0
D1_TOTAL_WRITE_SQL_DURING_FLOW=2
```

## 与 AC 逐条对照说明
- [x] MetricsCalculator 返回 B.2 五指标。
- [x] Evaluator 产出并持久化报告。
- [x] 报告结构符合 0.2 Contract（objective_definition/constraint_definition/baseline_version_id/conclusion/comparison_summary）。
- [x] baseline_version_id 合法（null 或 strategy_version_id，且不指向 param_version_id）。
- [x] 无“建议参数/写回/优化”语义。
- [x] 可按 strategy_version_id 查询。
- [x] 可按 evaluated_at 查询。
- [x] 可按 param_version_id 查询。
- [x] 无 Phase1.2 写操作：主流程区间写入拦截统计 `D1_PHASE12_WRITE_SQL_COUNT=0`。
