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
async def d3_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_trades(session: AsyncSession, strategy_id: str, pnls: list[str]) -> None:
    repo = TradeRepository(session)
    for i, pnl in enumerate(pnls, start=1):
        await repo.create(
            Trade(
                trade_id=f"{strategy_id}-T{i}",
                strategy_id=strategy_id,
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("50000"),
                realized_pnl=Decimal(pnl),
                executed_at=_dt(2025, 3, i, 9, 0),
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


def _cfg(*, baseline: str, min_trade: int, max_dd: Decimal, max_risk: Decimal) -> EvaluatorConfig:
    return EvaluatorConfig(
        objective_definition={
            "primary": "pnl",
            "primary_weight": 1.0,
            "secondary": [],
            "secondary_weights": [],
        },
        constraint_definition={
            "max_drawdown_pct": float(max_dd),
            "min_trade_count": int(min_trade),
            "max_risk_exposure": float(max_risk),
            "custom": None,
        },
        baseline_version_id=baseline,
    )


@pytest.mark.asyncio
async def test_e2e_phase2_constraint_violation(d3_session_factory):
    period_start = _dt(2025, 3, 1, 0, 0)
    period_end = _dt(2025, 3, 31, 23, 59)

    baseline_strategy = "D3-BASE-STRAT"
    baseline_version = "D3-V-BASE"
    baseline_param = "D3-P-BASE"

    pass_strategy = "D3-PASS-STRAT"
    pass_version = "D3-V-PASS"
    pass_param = "D3-P-PASS"

    trade_fail_strategy = "D3-TRADE-FAIL-STRAT"
    trade_fail_version = "D3-V-TRADE-FAIL"
    trade_fail_param = "D3-P-TRADE-FAIL"

    dd_fail_strategy = "D3-DD-FAIL-STRAT"
    dd_fail_version = "D3-V-DD-FAIL"
    dd_fail_param = "D3-P-DD-FAIL"

    risk_fail_strategy = "D3-RISK-FAIL-STRAT"
    risk_fail_version = "D3-V-RISK-FAIL"
    risk_fail_param = "D3-P-RISK-FAIL"

    async with d3_session_factory() as session:
        # baseline 与 pass：3 笔，最大回撤低
        await _seed_trades(session, baseline_strategy, ["60", "30", "-10"])
        await _seed_trades(session, pass_strategy, ["100", "40", "-20"])
        # trade_count 不达标：1 笔
        await _seed_trades(session, trade_fail_strategy, ["50"])
        # max_drawdown 超阈值：累计曲线 50 -> -150 -> -80，max_dd=200
        await _seed_trades(session, dd_fail_strategy, ["50", "-200", "70"])
        # risk_exposure 超阈值：沿用 max_drawdown 代理口径，构造大回撤
        await _seed_trades(session, risk_fail_strategy, ["30", "-130", "20"])
        counts_before = await _phase12_counts(session)
    print("D3_PHASE12_COUNTS_BEFORE=" + json.dumps(counts_before, ensure_ascii=False, sort_keys=True))

    service = Phase2MainFlowService(d3_session_factory)
    phase12_write_sql: list[str] = []
    phase12_tables = ("trade", "decision_snapshot", "execution_events", "log")

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        sql = " ".join((statement or "").strip().split())
        lowered = sql.lower()
        is_write = lowered.startswith("insert") or lowered.startswith("update") or lowered.startswith("delete") or lowered.startswith("replace")
        if is_write and any(f" {tbl} " in f" {lowered} " or f" {tbl}(" in f" {lowered} " for tbl in phase12_tables):
            phase12_write_sql.append(sql)

    event.listen(d3_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        # baseline 报告（用于后续 comparison_summary）
        await service.run_main_flow(
            strategy_id=baseline_strategy,
            strategy_version_id=baseline_version,
            param_version_id=baseline_param,
            period_start=period_start,
            period_end=period_end,
            config=EvaluatorConfig(
                objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
                constraint_definition={"max_drawdown_pct": 1000, "min_trade_count": 1, "max_risk_exposure": 1000, "custom": None},
                baseline_version_id=None,
            ),
        )

        # 1) 满足全部约束 => pass
        result_pass = await service.run_main_flow(
            strategy_id=pass_strategy,
            strategy_version_id=pass_version,
            param_version_id=pass_param,
            period_start=period_start,
            period_end=period_end,
            config=_cfg(baseline=baseline_version, min_trade=2, max_dd=Decimal("500"), max_risk=Decimal("500")),
        )
        assert result_pass.conclusion == "pass"
        assert result_pass.baseline_version_id == baseline_version

        # 2) trade_count < min_trade_count => fail
        result_trade_fail = await service.run_main_flow(
            strategy_id=trade_fail_strategy,
            strategy_version_id=trade_fail_version,
            param_version_id=trade_fail_param,
            period_start=period_start,
            period_end=period_end,
            config=_cfg(baseline=baseline_version, min_trade=2, max_dd=Decimal("500"), max_risk=Decimal("500")),
        )
        assert result_trade_fail.conclusion == "fail"

        # 3) max_drawdown > max_drawdown_pct => fail
        result_dd_fail = await service.run_main_flow(
            strategy_id=dd_fail_strategy,
            strategy_version_id=dd_fail_version,
            param_version_id=dd_fail_param,
            period_start=period_start,
            period_end=period_end,
            config=_cfg(baseline=baseline_version, min_trade=1, max_dd=Decimal("50"), max_risk=Decimal("500")),
        )
        assert result_dd_fail.conclusion == "fail"

        # 4) risk_exposure > max_risk_exposure => fail
        result_risk_fail = await service.run_main_flow(
            strategy_id=risk_fail_strategy,
            strategy_version_id=risk_fail_version,
            param_version_id=risk_fail_param,
            period_start=period_start,
            period_end=period_end,
            config=_cfg(baseline=baseline_version, min_trade=1, max_dd=Decimal("500"), max_risk=Decimal("10")),
        )
        assert result_risk_fail.conclusion == "fail"
    finally:
        event.remove(d3_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)

    print(f"D3_PHASE12_WRITE_SQL_COUNT={len(phase12_write_sql)}")
    assert len(phase12_write_sql) == 0

    # 查询与字段完整性校验
    reports = await service.query_by_strategy_version(risk_fail_version)
    assert len(reports) >= 1
    report = reports[-1]
    assert report.constraint_definition is not None
    assert report.baseline_version_id == baseline_version
    assert report.comparison_summary is not None
    violations = (report.comparison_summary or {}).get("constraint_violations") or []
    assert "max_risk_exposure" in violations
    summary_str = json.dumps(report.comparison_summary, ensure_ascii=False)
    assert "建议参数" not in summary_str
    assert "写回" not in summary_str
    assert "优化" not in summary_str
    assert "建议参数" not in report.conclusion
    assert "写回" not in report.conclusion
    assert "优化" not in report.conclusion

    # 各场景违规指标解释校验
    r_trade = (await service.query_by_strategy_version(trade_fail_version))[-1]
    r_dd = (await service.query_by_strategy_version(dd_fail_version))[-1]
    r_risk = (await service.query_by_strategy_version(risk_fail_version))[-1]
    assert "min_trade_count" in ((r_trade.comparison_summary or {}).get("constraint_violations") or [])
    assert "max_drawdown_pct" in ((r_dd.comparison_summary or {}).get("constraint_violations") or [])
    assert "max_risk_exposure" in ((r_risk.comparison_summary or {}).get("constraint_violations") or [])

    sample = {
        "pass_conclusion": result_pass.conclusion,
        "trade_fail_conclusion": result_trade_fail.conclusion,
        "dd_fail_conclusion": result_dd_fail.conclusion,
        "risk_fail_conclusion": result_risk_fail.conclusion,
        "baseline_version_id": report.baseline_version_id,
        "constraint_definition": report.constraint_definition,
        "comparison_summary": report.comparison_summary,
    }
    print("D3_REPORT_SAMPLE_JSON=" + json.dumps(sample, ensure_ascii=False, sort_keys=True))

    async with d3_session_factory() as session:
        counts_after = await _phase12_counts(session)
    print("D3_PHASE12_COUNTS_AFTER=" + json.dumps(counts_after, ensure_ascii=False, sort_keys=True))
    assert counts_after == counts_before
