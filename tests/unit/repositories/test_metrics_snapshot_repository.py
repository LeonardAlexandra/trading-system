"""
Phase2.0 C1：MetricsRepository 单元测试（D.1 接口：write / get_by_strategy_period / get_by_strategy_time_range）

锁死语义：
- get_by_strategy_period：精确匹配 period_start 与 period_end。
- get_by_strategy_time_range：快照区间与 [start_ts, end_ts] 存在重叠（period_start <= end_ts AND period_end >= start_ts）。
覆盖：插入 commit 后新 session 查询一致；时间边界（贴边、不重叠、包含、start=end）。

时间语义（UTC 显式化）：所有 datetime 统一为 tz-aware UTC，禁止 naive。
- 构造：通过 _dt(year, month, day) 或 datetime(..., tzinfo=timezone.utc)。
- 断言：通过 _utc(d) 归一化后再比较（兼容 SQLite 读出的 naive）。
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from decimal import Decimal

from src.database.connection import Base
from src.models.metrics_snapshot import MetricsSnapshot
from src.repositories.metrics_snapshot_repository import MetricsRepository


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _utc(d: datetime) -> datetime:
    """归一化到 UTC 以便与 DB 读出的 naive datetime 比较（SQLite 可能无 tz）。"""
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


@pytest.fixture
async def c1_session_factory():
    """In-memory SQLite，仅创建 Base 上已注册表（含 metrics_snapshot）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    yield session_factory
    await engine.dispose()


# ---------- write 与持久化一致性 ----------


@pytest.mark.asyncio
async def test_write_then_get_by_strategy_period_new_session(c1_session_factory):
    """插入 commit 后，新 session 通过 get_by_strategy_period 查询结果与写入一致。"""
    p_start = _dt(2025, 1, 1)
    p_end = _dt(2025, 1, 31)
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        snapshot = MetricsSnapshot(
            strategy_id="strat-1",
            strategy_version_id="ver-001",
            param_version_id="param-1",
            period_start=p_start,
            period_end=p_end,
            trade_count=10,
            win_rate=Decimal("0.6"),
            realized_pnl=Decimal("100.5"),
            max_drawdown=Decimal("-20.0"),
            avg_holding_time_sec=Decimal("3600.0"),
        )
        await repo.write(snapshot)
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        rows = await repo.get_by_strategy_period("strat-1", p_start, p_end)
    assert len(rows) == 1
    assert rows[0].strategy_id == "strat-1"
    assert rows[0].strategy_version_id == "ver-001"
    assert rows[0].trade_count == 10
    assert rows[0].realized_pnl == Decimal("100.5")


# ---------- get_by_strategy_version：按策略版本查询，新 session 持久化 + 过滤锁死 ----------


@pytest.mark.asyncio
async def test_write_then_get_by_strategy_version_new_session(c1_session_factory):
    """写入 snapshot -> commit -> 新 session -> get_by_strategy_version 查询 -> 断言条数与字段一致。"""
    p_start = _dt(2025, 1, 1)
    p_end = _dt(2025, 1, 31)
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        snapshot = MetricsSnapshot(
            strategy_id="strat-1",
            strategy_version_id="ver-001",
            param_version_id="param-1",
            period_start=p_start,
            period_end=p_end,
            trade_count=10,
            win_rate=Decimal("0.6"),
            realized_pnl=Decimal("100.5"),
            max_drawdown=Decimal("-20.0"),
            avg_holding_time_sec=Decimal("3600.0"),
        )
        await repo.write(snapshot)
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        rows = await repo.get_by_strategy_version("ver-001")
    assert len(rows) == 1
    assert rows[0].strategy_id == "strat-1"
    assert rows[0].strategy_version_id == "ver-001"
    assert rows[0].param_version_id == "param-1"
    assert rows[0].trade_count == 10
    assert rows[0].realized_pnl == Decimal("100.5")
    assert _utc(rows[0].period_start) == _utc(p_start)
    assert _utc(rows[0].period_end) == _utc(p_end)


@pytest.mark.asyncio
async def test_get_by_strategy_version_filters_only_target(c1_session_factory):
    """插入两条不同 strategy_version_id -> 查询其中一个 -> 只返回对应记录；排序按 period_start 升序。"""
    p1 = (_dt(2025, 1, 1), _dt(2025, 1, 31))
    p2 = (_dt(2025, 2, 1), _dt(2025, 2, 28))
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        await repo.write(
            MetricsSnapshot(
                strategy_id="s",
                strategy_version_id="ver-A",
                param_version_id=None,
                period_start=p1[0],
                period_end=p1[1],
                trade_count=1,
                realized_pnl=Decimal("0"),
            )
        )
        await repo.write(
            MetricsSnapshot(
                strategy_id="s",
                strategy_version_id="ver-B",
                param_version_id=None,
                period_start=p2[0],
                period_end=p2[1],
                trade_count=2,
                realized_pnl=Decimal("0"),
            )
        )
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        rows_a = await repo.get_by_strategy_version("ver-A")
        rows_b = await repo.get_by_strategy_version("ver-B")
    assert len(rows_a) == 1 and rows_a[0].strategy_version_id == "ver-A" and rows_a[0].trade_count == 1
    assert len(rows_b) == 1 and rows_b[0].strategy_version_id == "ver-B" and rows_b[0].trade_count == 2
    # 锁死排序：按 period_start 升序
    assert _utc(rows_a[0].period_start) <= _utc(rows_a[0].period_end)
    assert _utc(rows_b[0].period_start) <= _utc(rows_b[0].period_end)


# ---------- get_by_strategy_period：精确匹配，锁死语义 ----------


@pytest.mark.asyncio
async def test_get_by_strategy_period_exact_match_only(c1_session_factory):
    """get_by_strategy_period 仅返回 period_start 与 period_end 均精确匹配的记录。"""
    p1_start = _dt(2025, 1, 1)
    p1_end = _dt(2025, 1, 31)
    p2_start = _dt(2025, 2, 1)
    p2_end = _dt(2025, 2, 28)
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        await repo.write(
            MetricsSnapshot(
                strategy_id="s",
                strategy_version_id="v1",
                param_version_id=None,
                period_start=p1_start,
                period_end=p1_end,
                trade_count=1,
                realized_pnl=Decimal("0"),
            )
        )
        await repo.write(
            MetricsSnapshot(
                strategy_id="s",
                strategy_version_id="v2",
                param_version_id=None,
                period_start=p2_start,
                period_end=p2_end,
                trade_count=2,
                realized_pnl=Decimal("0"),
            )
        )
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        exact_p1 = await repo.get_by_strategy_period("s", p1_start, p1_end)
        exact_p2 = await repo.get_by_strategy_period("s", p2_start, p2_end)
        wrong_period = await repo.get_by_strategy_period("s", _dt(2025, 1, 15), _dt(2025, 1, 20))
    assert len(exact_p1) == 1 and _utc(exact_p1[0].period_start) == _utc(p1_start) and _utc(exact_p1[0].period_end) == _utc(p1_end)
    assert len(exact_p2) == 1 and _utc(exact_p2[0].period_start) == _utc(p2_start) and _utc(exact_p2[0].period_end) == _utc(p2_end)
    assert len(wrong_period) == 0


# ---------- get_by_strategy_time_range：重叠语义，边界条件 ----------


@pytest.mark.asyncio
async def test_get_by_strategy_time_range_overlap_edge(c1_session_factory):
    """贴边重叠：快照 [1/1, 1/15]，查询 [1/15, 1/31] 应命中（1/15 重合）。"""
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        await repo.write(
            MetricsSnapshot(
                strategy_id="s",
                strategy_version_id="v",
                param_version_id=None,
                period_start=_dt(2025, 1, 1),
                period_end=_dt(2025, 1, 15),
                trade_count=1,
                realized_pnl=Decimal("0"),
            )
        )
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        rows = await repo.get_by_strategy_time_range("s", _dt(2025, 1, 15), _dt(2025, 1, 31))
    assert len(rows) == 1
    assert _utc(rows[0].period_start) == _utc(_dt(2025, 1, 1)) and _utc(rows[0].period_end) == _utc(_dt(2025, 1, 15))


@pytest.mark.asyncio
async def test_get_by_strategy_time_range_no_overlap(c1_session_factory):
    """完全不重叠：快照 [1/1, 1/10]，查询 [1/11, 1/20] 不命中。"""
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        await repo.write(
            MetricsSnapshot(
                strategy_id="s",
                strategy_version_id="v",
                param_version_id=None,
                period_start=_dt(2025, 1, 1),
                period_end=_dt(2025, 1, 10),
                trade_count=1,
                realized_pnl=Decimal("0"),
            )
        )
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        rows = await repo.get_by_strategy_time_range("s", _dt(2025, 1, 11), _dt(2025, 1, 20))
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_get_by_strategy_time_range_query_contains_snapshot(c1_session_factory):
    """查询范围完全包含快照：快照 [1/10, 1/20]，查询 [1/1, 1/31] 应命中。"""
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        await repo.write(
            MetricsSnapshot(
                strategy_id="s",
                strategy_version_id="v",
                param_version_id=None,
                period_start=_dt(2025, 1, 10),
                period_end=_dt(2025, 1, 20),
                trade_count=1,
                realized_pnl=Decimal("0"),
            )
        )
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        rows = await repo.get_by_strategy_time_range("s", _dt(2025, 1, 1), _dt(2025, 1, 31))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_by_strategy_time_range_snapshot_contains_query(c1_session_factory):
    """快照完全包含查询范围：快照 [1/1, 1/31]，查询 [1/10, 1/20] 应命中。"""
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        await repo.write(
            MetricsSnapshot(
                strategy_id="s",
                strategy_version_id="v",
                param_version_id=None,
                period_start=_dt(2025, 1, 1),
                period_end=_dt(2025, 1, 31),
                trade_count=1,
                realized_pnl=Decimal("0"),
            )
        )
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        rows = await repo.get_by_strategy_time_range("s", _dt(2025, 1, 10), _dt(2025, 1, 20))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_by_strategy_time_range_start_equals_end(c1_session_factory):
    """start_ts == end_ts：查询 [1/15, 1/15]，快照 [1/10, 1/20] 应命中（单点仍重叠）。"""
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        await repo.write(
            MetricsSnapshot(
                strategy_id="s",
                strategy_version_id="v",
                param_version_id=None,
                period_start=_dt(2025, 1, 10),
                period_end=_dt(2025, 1, 20),
                trade_count=1,
                realized_pnl=Decimal("0"),
            )
        )
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        rows = await repo.get_by_strategy_time_range("s", _dt(2025, 1, 15), _dt(2025, 1, 15))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_by_strategy_time_range_strategy_id_filter(c1_session_factory):
    """仅返回 strategy_id 匹配；不同 strategy_id 不混入。"""
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        await repo.write(
            MetricsSnapshot(
                strategy_id="s1",
                strategy_version_id="v",
                param_version_id=None,
                period_start=_dt(2025, 1, 1),
                period_end=_dt(2025, 1, 31),
                trade_count=1,
                realized_pnl=Decimal("0"),
            )
        )
        await repo.write(
            MetricsSnapshot(
                strategy_id="s2",
                strategy_version_id="v",
                param_version_id=None,
                period_start=_dt(2025, 1, 1),
                period_end=_dt(2025, 1, 31),
                trade_count=2,
                realized_pnl=Decimal("0"),
            )
        )
        await session.commit()
    async with c1_session_factory() as session:
        repo = MetricsRepository(session)
        rows_s1 = await repo.get_by_strategy_time_range("s1", _dt(2025, 1, 1), _dt(2025, 1, 31))
        rows_s2 = await repo.get_by_strategy_time_range("s2", _dt(2025, 1, 1), _dt(2025, 1, 31))
    assert len(rows_s1) == 1 and rows_s1[0].strategy_id == "s1"
    assert len(rows_s2) == 1 and rows_s2[0].strategy_id == "s2"


@pytest.mark.asyncio
async def test_repository_no_business_logic():
    """C1 约束：Repository 无指标计算/业务判断（无 calc、evaluator、baseline 等）。"""
    assert not hasattr(MetricsRepository, "calculate")
    assert not hasattr(MetricsRepository, "evaluate")
    assert not hasattr(MetricsRepository, "baseline")
    assert hasattr(MetricsRepository, "write")
    assert hasattr(MetricsRepository, "get_by_strategy_period")
    assert hasattr(MetricsRepository, "get_by_strategy_time_range")
    assert hasattr(MetricsRepository, "get_by_strategy_version")
