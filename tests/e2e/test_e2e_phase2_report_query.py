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
