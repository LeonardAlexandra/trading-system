import json
from datetime import datetime, timezone
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
from src.repositories.trade_repo import TradeRepository
import src.models  # noqa: F401


def _dt(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


@pytest.fixture
async def d2_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_trade_data(session: AsyncSession, strategy_id: str, rows: list[tuple[str, str]]) -> None:
    repo = TradeRepository(session)
    for trade_id, pnl in rows:
        await repo.create(
            Trade(
                trade_id=trade_id,
                strategy_id=strategy_id,
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("50000"),
                realized_pnl=Decimal(pnl),
                executed_at=_dt(2025, 2, 1, 9, 0),
            )
        )
    await session.commit()


async def _phase12_counts(session: AsyncSession) -> dict[str, int]:
    return {
        "trade": int((await session.execute(select(func.count()).select_from(Trade))).scalar() or 0),
        "decision_snapshot": int((await session.execute(select(func.count()).select_from(DecisionSnapshot))).scalar() or 0),
        "execution_events": int((await session.execute(select(func.count()).select_from(ExecutionEvent))).scalar() or 0),
        "log": int((await session.execute(select(func.count()).select_from(LogEntry))).scalar() or 0),
    }


@pytest.mark.asyncio
async def test_e2e_phase2_version_compare(d2_session_factory):
    strategy_base = "D2-STRATEGY-BASE"
    strategy_target = "D2-STRATEGY-TARGET"
    version_base = "D2-V-B"
    version_target = "D2-V-A"
    param_base = "D2-P-B"
    param_target = "D2-P-A"
    period_start = _dt(2025, 2, 1, 0, 0)
    period_end = _dt(2025, 2, 2, 0, 0)

    async with d2_session_factory() as session:
        # baseline 版本与 target 版本使用不同固定 trade 集，确保 comparison_summary 存在差异
        await _seed_trade_data(session, strategy_base, [("D2-T-B1", "10"), ("D2-T-B2", "-5")])
        await _seed_trade_data(session, strategy_target, [("D2-T-A1", "120"), ("D2-T-A2", "80"), ("D2-T-A3", "-10")])
        counts_before = await _phase12_counts(session)
    print("D2_PHASE12_COUNTS_BEFORE=" + json.dumps(counts_before, ensure_ascii=False, sort_keys=True))

    service = Phase2MainFlowService(d2_session_factory)

    baseline_cfg = EvaluatorConfig(
        objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
        constraint_definition={"max_drawdown_pct": 1000, "min_trade_count": 1, "max_risk_exposure": None, "custom": None},
        baseline_version_id=None,
    )
    compare_cfg = EvaluatorConfig(
        objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
        constraint_definition={"max_drawdown_pct": 1000, "min_trade_count": 1, "max_risk_exposure": None, "custom": None},
        baseline_version_id=version_base,
    )

    write_sql_phase12: list[str] = []
    phase12_tables = ("trade", "decision_snapshot", "execution_events", "log")

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        sql = " ".join((statement or "").strip().split())
        lowered = sql.lower()
        is_write = lowered.startswith("insert") or lowered.startswith("update") or lowered.startswith("delete") or lowered.startswith("replace")
        if is_write and any(f" {tbl} " in f" {lowered} " or f" {tbl}(" in f" {lowered} " for tbl in phase12_tables):
            write_sql_phase12.append(sql)

    event.listen(d2_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        # 先产出 baseline 版本快照/报告
        await service.run_main_flow(
            strategy_id=strategy_base,
            strategy_version_id=version_base,
            param_version_id=param_base,
            period_start=period_start,
            period_end=period_end,
            config=baseline_cfg,
        )
        # 再做版本对比：target vs baseline_version_id
        result = await service.run_main_flow(
            strategy_id=strategy_target,
            strategy_version_id=version_target,
            param_version_id=param_target,
            period_start=period_start,
            period_end=period_end,
            config=compare_cfg,
        )

        # 非法 baseline：param_version_id 作为 baseline_version_id 必须拒绝
        illegal_baseline_error = None
        try:
            await service.run_main_flow(
                strategy_id=strategy_target,
                strategy_version_id=version_target,
                param_version_id=param_target,
                period_start=period_start,
                period_end=period_end,
                config=EvaluatorConfig(
                    objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
                    constraint_definition={"max_drawdown_pct": 1000, "min_trade_count": 1, "max_risk_exposure": None, "custom": None},
                    baseline_version_id=param_target,
                ),
            )
        except Exception as exc:  # ValueError 由 Evaluator 抛出
            illegal_baseline_error = str(exc)
        assert illegal_baseline_error is not None
        print("D2_ILLEGAL_BASELINE_ERROR=" + illegal_baseline_error)
    finally:
        event.remove(d2_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)

    print(f"D2_PHASE12_WRITE_SQL_COUNT={len(write_sql_phase12)}")
    assert len(write_sql_phase12) == 0

    # 查询与持久化验证
    by_version = await service.query_by_strategy_version(version_target)
    by_param = await service.query_by_param_version(param_target)
    print(
        "D2_QUERY_COUNTS="
        + json.dumps(
            {"strategy_version": len(by_version), "param_version": len(by_param)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    assert len(by_version) >= 1
    assert len(by_param) >= 1

    report = by_param[-1]
    sample = {
        "strategy_id": report.strategy_id,
        "strategy_version_id": report.strategy_version_id,
        "param_version_id": report.param_version_id,
        "baseline_version_id": report.baseline_version_id,
        "conclusion": report.conclusion,
        "comparison_summary": report.comparison_summary,
    }
    print("D2_COMPARISON_SAMPLE_JSON=" + json.dumps(sample, ensure_ascii=False, sort_keys=True))

    assert report.baseline_version_id == version_base
    assert report.baseline_version_id != param_target
    assert report.comparison_summary is not None
    assert isinstance(report.comparison_summary, dict)
    delta = report.comparison_summary.get("delta") or {}
    assert "trade_count" in delta
    assert "realized_pnl" in delta
    assert "win_rate" in delta
    summary_str = json.dumps(report.comparison_summary, ensure_ascii=False)
    assert "建议参数" not in summary_str
    assert "优化" not in summary_str
    assert "写回" not in summary_str
    assert "建议参数" not in report.conclusion
    assert "优化" not in report.conclusion
    assert "写回" not in report.conclusion

    async with d2_session_factory() as session:
        counts_after = await _phase12_counts(session)
    print("D2_PHASE12_COUNTS_AFTER=" + json.dumps(counts_after, ensure_ascii=False, sort_keys=True))
    assert counts_after == counts_before
