from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import src.models  # noqa: F401 - register ORM models
from src.database.connection import Base
from src.models.evaluation_report import EvaluationReport
from src.repositories.evaluation_report_repository import EvaluationReportRepository


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
async def session_factory():
    """In-memory SQLite，含 evaluation_report 表（Phase 2.0 自有表）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _insert_report(
    session: AsyncSession,
    strategy_id: str,
    strategy_version_id: str,
    param_version_id: str | None,
    evaluated_at: datetime,
) -> None:
    repo = EvaluationReportRepository(session)
    report = EvaluationReport(
        strategy_id=strategy_id,
        strategy_version_id=strategy_version_id,
        param_version_id=param_version_id,
        evaluated_at=evaluated_at,
        period_start=evaluated_at - timedelta(days=1),
        period_end=evaluated_at,
        objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
        constraint_definition={
            "max_drawdown_pct": None,
            "min_trade_count": None,
            "max_risk_exposure": None,
            "custom": None,
        },
        baseline_version_id=None,
        conclusion="pass",
        comparison_summary=None,
        metrics_snapshot_id=None,
    )
    await repo.write(report)
    await session.commit()


@pytest.mark.asyncio
async def test_get_by_strategy_version(session_factory):
    async with session_factory() as session:
        await _insert_report(session, "s1", "ver-1", None, _dt(2025, 1, 10))
        await _insert_report(session, "s1", "ver-1", "param-a", _dt(2025, 1, 11))
        await _insert_report(session, "s1", "ver-2", None, _dt(2025, 1, 12))

    async with session_factory() as session:
        repo = EvaluationReportRepository(session)
        rows = await repo.get_by_strategy_version("ver-1")
    assert len(rows) == 2
    assert all(r.strategy_version_id == "ver-1" for r in rows)


@pytest.mark.asyncio
async def test_get_by_evaluated_at_range(session_factory):
    async with session_factory() as session:
        await _insert_report(session, "s2", "ver-a", None, _dt(2025, 2, 1))
        await _insert_report(session, "s2", "ver-b", None, _dt(2025, 2, 5))
        await _insert_report(session, "s3", "ver-c", None, _dt(2025, 2, 3))

    async with session_factory() as session:
        repo = EvaluationReportRepository(session)
        rows = await repo.get_by_evaluated_at(
            "s2", _dt(2025, 2, 2), _dt(2025, 2, 10)
        )
    assert len(rows) == 1
    assert rows[0].strategy_id == "s2"
    assert rows[0].evaluated_at.date() == _dt(2025, 2, 5).date()


@pytest.mark.asyncio
async def test_get_by_param_version(session_factory):
    async with session_factory() as session:
        await _insert_report(session, "s3", "ver-x", "param-1", _dt(2025, 3, 1))
        await _insert_report(session, "s3", "ver-x", "param-2", _dt(2025, 3, 2))

    async with session_factory() as session:
        repo = EvaluationReportRepository(session)
        rows = await repo.get_by_param_version("param-1")
    assert len(rows) == 1
    assert rows[0].param_version_id == "param-1"


@pytest.mark.asyncio
async def test_baseline_version_id_remains_strategy_version_only(session_factory):
    """验证：C4 查询不改变 baseline_version_id 语义，仍仅引用 strategy_version。"""
    async with session_factory() as session:
        await _insert_report(session, "s4", "ver-main", "param-x", _dt(2025, 4, 1))
        # baseline_version_id 仅存 strategy_version_id 语义
        stmt = select(EvaluationReport).limit(1)
        row = (await session.execute(stmt)).scalar_one()
        assert row.baseline_version_id is None

    async with session_factory() as session:
        repo = EvaluationReportRepository(session)
        by_version = await repo.get_by_strategy_version("ver-main")
        by_param = await repo.get_by_param_version("param-x")

    assert len(by_version) == 1
    assert len(by_param) == 1
    assert by_version[0].baseline_version_id is None
    assert by_param[0].baseline_version_id is None

