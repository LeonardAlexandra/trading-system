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
