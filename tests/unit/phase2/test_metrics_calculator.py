"""
Phase2.0 C2：MetricsCalculator 单元测试（B.2 口径、只读边界、无 conclusion/baseline）

- 给定策略+版本+时间范围返回 B.2 五指标
- 固定 trade 集抽检：trade_count=COUNT、realized_pnl=SUM、win_rate=盈利笔数/总笔数、max_drawdown 来自权益曲线、avg_holding_time_sec
- 仅风控拒绝无 trade 的周期 -> 0 或 NULL
- compute 不写 Phase 1.2 表；MetricsResult 无 conclusion、comparison_summary、baseline
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import src.models  # noqa: F401 - register Trade etc.
from src.database.connection import Base
from src.models.trade import Trade
from src.repositories.trade_repo import TradeRepository
from src.phase2.metrics_calculator import MetricsCalculator
from src.phase2.metrics_result import MetricsResult


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
async def session_factory():
    """In-memory SQLite，含 trade 表（仅读用于 C2）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    yield session_factory
    await engine.dispose()


async def _create_trade(
    session: AsyncSession,
    trade_id: str,
    strategy_id: str,
    executed_at: datetime,
    realized_pnl: Decimal,
) -> None:
    repo = TradeRepository(session)
    trade = Trade(
        trade_id=trade_id,
        strategy_id=strategy_id,
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("0.01"),
        price=Decimal("50000"),
        realized_pnl=realized_pnl,
        executed_at=executed_at,
    )
    await repo.create(trade)
    await session.commit()


@pytest.mark.asyncio
async def test_compute_returns_b2_five_metrics(session_factory):
    """给定策略+版本+时间范围可返回 B.2 五指标（当前 trade 层仅按 strategy_id+时间范围读取）。"""
    async with session_factory() as session:
        await _create_trade(session, "t1", "strat-1", _dt(2025, 1, 10), Decimal("100"))
        await _create_trade(session, "t2", "strat-1", _dt(2025, 1, 15), Decimal("-20"))
        await _create_trade(session, "t3", "strat-1", _dt(2025, 1, 20), Decimal("50"))
    async with session_factory() as session:
        repo = TradeRepository(session)
        # Spy：确认 MetricsCalculator.compute 仅以 strategy_id + 时间范围调用只读查询，
        # 不向 Repo 传递 strategy_version_id 之类的版本维度做过滤。
        calls = []

        original_list = repo.list_by_strategy_and_executed_time_range

        async def _spy_list_by_strategy_and_executed_time_range(
            strategy_id: str,
            period_start: datetime,
            period_end: datetime,
        ):
            calls.append((strategy_id, period_start, period_end))
            return await original_list(strategy_id, period_start, period_end)

        repo.list_by_strategy_and_executed_time_range = (  # type: ignore[assignment]
            _spy_list_by_strategy_and_executed_time_range
        )
        calc = MetricsCalculator(repo)
        result = await calc.compute(
            "strat-1", "ver-1", None,
            _dt(2025, 1, 1), _dt(2025, 1, 31),
        )
    assert isinstance(result, MetricsResult)
    assert result.trade_count == 3
    assert result.realized_pnl == Decimal("130")  # 100 - 20 + 50
    assert result.win_rate == Decimal("2") / Decimal("3")  # 2 笔盈利
    assert result.max_drawdown is not None
    assert result.avg_holding_time_sec is None  # Trade 无 open/close 时间字段
    # 版本口径 Option B：trade 表无 strategy_version_id，C2 仅按 strategy_id + 时间范围查询。
    assert calls == [
        ("strat-1", _dt(2025, 1, 1), _dt(2025, 1, 31)),
    ]


@pytest.mark.asyncio
async def test_compute_b2_fixed_trade_set(session_factory):
    """口径抽检：trade_count=COUNT、realized_pnl=SUM、win_rate=盈利笔数/总笔数、max_drawdown 来自权益曲线。"""
    async with session_factory() as session:
        await _create_trade(session, "a1", "s", _dt(2025, 2, 1), Decimal("10"))
        await _create_trade(session, "a2", "s", _dt(2025, 2, 2), Decimal("-5"))
        await _create_trade(session, "a3", "s", _dt(2025, 2, 3), Decimal("0"))
    async with session_factory() as session:
        repo = TradeRepository(session)
        calc = MetricsCalculator(repo)
        result = await calc.compute("s", "v", None, _dt(2025, 2, 1), _dt(2025, 2, 28))
    assert result.trade_count == 3
    assert result.realized_pnl == Decimal("5")  # 10 - 5 + 0
    assert result.win_rate == Decimal("1") / Decimal("3")  # 1 笔盈利
    # 权益曲线: 10 -> 5 -> 5；peak 10，max_drawdown = 10 - 5 = 5
    assert result.max_drawdown == Decimal("5")
    assert result.avg_holding_time_sec is None


@pytest.mark.asyncio
async def test_compute_no_trades_only_rejections(session_factory):
    """仅风控拒绝无 trade 的周期：核心指标为 0 或 NULL。"""
    async with session_factory() as session:
        repo = TradeRepository(session)
        calc = MetricsCalculator(repo)
        result = await calc.compute(
            "strat-empty", "ver-1", None,
            _dt(2025, 3, 1), _dt(2025, 3, 31),
        )
    assert result.trade_count == 0
    assert result.win_rate is None
    assert result.realized_pnl == Decimal("0")
    assert result.max_drawdown == Decimal("0")
    assert result.avg_holding_time_sec is None


@pytest.mark.asyncio
async def test_compute_single_trade_max_drawdown_zero(session_factory):
    """仅一笔 trade 时 max_drawdown 为 0（文档约定）。"""
    async with session_factory() as session:
        await _create_trade(session, "single", "s", _dt(2025, 4, 1), Decimal("100"))
    async with session_factory() as session:
        repo = TradeRepository(session)
        calc = MetricsCalculator(repo)
        result = await calc.compute("s", "v", None, _dt(2025, 4, 1), _dt(2025, 4, 30))
    assert result.trade_count == 1
    assert result.max_drawdown == Decimal("0")
    assert result.win_rate == Decimal("1")


@pytest.mark.asyncio
async def test_metrics_result_no_conclusion_baseline():
    """MetricsCalculator 未输出 conclusion、comparison_summary、baseline 或「建议」。"""
    assert not hasattr(MetricsResult, "conclusion")
    assert not hasattr(MetricsResult, "comparison_summary")
    assert not hasattr(MetricsResult, "baseline")
    # 仅有 B.2 五字段
    fields = {f.name for f in MetricsResult.__dataclass_fields__.values()}
    assert fields == {"trade_count", "win_rate", "realized_pnl", "max_drawdown", "avg_holding_time_sec"}
    # max_drawdown 类型约定：始终为 Decimal，且无 Optional 语义。
    max_dd_field = MetricsResult.__dataclass_fields__["max_drawdown"]
    assert max_dd_field.type is Decimal


@pytest.mark.asyncio
async def test_compute_read_only_no_write(session_factory):
    """只读边界：compute 仅通过 list_by_strategy_and_executed_time_range 读 trade，不写表。"""
    async with session_factory() as session:
        await _create_trade(session, "r1", "strat-r", _dt(2025, 5, 1), Decimal("1"))
    async with session_factory() as session:
        # 显式 Spy 写路径：若 compute 存在写操作，应触发 add/commit/flush。
        write_calls = {"add": 0, "commit": 0, "flush": 0}

        original_add = session.add

        def _spy_add(instance, *args, **kwargs):
            write_calls["add"] += 1
            return original_add(instance, *args, **kwargs)

        original_commit = session.commit

        async def _spy_commit(*args, **kwargs):
            write_calls["commit"] += 1
            return await original_commit(*args, **kwargs)

        original_flush = session.flush

        async def _spy_flush(*args, **kwargs):
            write_calls["flush"] += 1
            return await original_flush(*args, **kwargs)

        session.add = _spy_add  # type: ignore[assignment]
        session.commit = _spy_commit  # type: ignore[assignment]
        session.flush = _spy_flush  # type: ignore[assignment]

        repo = TradeRepository(session)
        calc = MetricsCalculator(repo)
        await calc.compute("strat-r", "v", None, _dt(2025, 5, 1), _dt(2025, 5, 31))

        # 只读保证：compute 过程中未触发任何写路径。
        assert write_calls == {"add": 0, "commit": 0, "flush": 0}
    async with session_factory() as session:
        repo = TradeRepository(session)
        trades = await repo.list_by_strategy_and_executed_time_range(
            "strat-r", _dt(2025, 5, 1), _dt(2025, 5, 31)
        )
    assert len(trades) == 1
    assert trades[0].trade_id == "r1"
