from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import src.models  # noqa: F401 - register ORM models
from src.database.connection import Base
from src.models.evaluation_report import EvaluationReport
from src.repositories.strategy_version_repository import (
    StrategyVersionRepository,
    StrategyVersionView,
)


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


@pytest.fixture
async def session_factory():
    """In-memory SQLite，仅包含 Phase 2.0 表 evaluation_report。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _insert_versioned_report(
    session: AsyncSession,
    strategy_id: str,
    strategy_version_id: str,
) -> None:
    """插入一条最小 evaluation_report 记录，用于驱动 StrategyVersionRepository。"""
    now = _dt(2025, 1, 1)
    report = EvaluationReport(
        strategy_id=strategy_id,
        strategy_version_id=strategy_version_id,
        param_version_id=None,
        evaluated_at=now,
        period_start=now - timedelta(days=1),
        period_end=now,
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
    session.add(report)
    await session.commit()


@pytest.mark.asyncio
async def test_get_by_id_returns_version_view(session_factory):
    async with session_factory() as session:
        await _insert_versioned_report(session, "s-strategy", "ver-123")
    async with session_factory() as session:
        repo = StrategyVersionRepository(session)
        view = await repo.get_by_id("ver-123")
    assert isinstance(view, StrategyVersionView)
    assert view.strategy_version_id == "ver-123"
    assert view.strategy_id == "s-strategy"


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_no_evaluation_report(session_factory):
    """
    语义验证（方案B）：如果不存在对应的 evaluation_report，即使 version_id 在外部逻辑中存在，
    在当前 C4 实现中 get_by_id 也应返回 None。
    这是由于版本来源被定义为 evaluation_report 推导。
    """
    async with session_factory() as session:
        repo = StrategyVersionRepository(session)
        view = await repo.get_by_id("non-existent-version")
    assert view is None


@pytest.mark.asyncio
async def test_list_by_strategy_returns_sorted_versions(session_factory):
    """验证：返回去重后的版本列表，且按 strategy_version_id 升序排列（稳定排序，测试锁死）。"""
    async with session_factory() as session:
        # 乱序插入多个不同 strategy_version_id 的 evaluation_report
        await _insert_versioned_report(session, "s-a", "ver-a2")
        await _insert_versioned_report(session, "s-a", "ver-a1")
        await _insert_versioned_report(session, "s-a", "ver-a3")
        await _insert_versioned_report(session, "s-b", "ver-b1")
    async with session_factory() as session:
        repo = StrategyVersionRepository(session)
        views = await repo.list_by_strategy("s-a")
    
    # 验证返回顺序严格等于排序后的列表（升序）
    ids = [v.strategy_version_id for v in views]
    assert ids == ["ver-a1", "ver-a2", "ver-a3"]
    assert all(v.strategy_id == "s-a" for v in views)

