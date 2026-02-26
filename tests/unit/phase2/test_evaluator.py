"""
Phase2.0 C3：Evaluator 单元测试（0.2 报告、B.1 结构、只读边界、无建议/写回措辞）

- 产出报告必含 objective_definition、constraint_definition、baseline_version_id、conclusion、comparison_summary，且已持久化
- report.strategy_version_id 存在；baseline_version_id 为 null 或 strategy_version_id（非 param_version_id）
- B.1 结构：objective 含 primary、primary_weight、secondary、secondary_weights；constraint 含 max_drawdown_pct、min_trade_count、max_risk_exposure、custom
- evaluate 执行前后 Phase 1.2 表无写操作；结论与 comparison_summary 无「建议参数」「可写回」「供优化」
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import src.models  # noqa: F401 - register all ORM
from src.database.connection import Base
from src.models.trade import Trade
from src.models.evaluation_report import EvaluationReport
from src.models.metrics_snapshot import MetricsSnapshot
from src.repositories.trade_repo import TradeRepository
from src.repositories.metrics_snapshot_repository import MetricsRepository
from src.repositories.evaluation_report_repository import EvaluationReportRepository
from src.phase2.metrics_calculator import MetricsCalculator
from src.phase2.evaluator import Evaluator
from src.phase2.evaluation_config import EvaluatorConfig
from src.phase2.evaluation_report_result import EvaluationReportResult


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
async def session_factory():
    """In-memory SQLite，含 Phase 1.2 表（trade）与 Phase 2.0 表（metrics_snapshot、evaluation_report）。"""
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
async def test_evaluate_produces_report_with_02_five_and_persisted(session_factory):
    """产出报告必含 objective_definition、constraint_definition、baseline_version_id、conclusion、comparison_summary，且已持久化。"""
    async with session_factory() as session:
        await _create_trade(session, "t1", "strat-1", _dt(2025, 1, 10), Decimal("100"))
        await _create_trade(session, "t2", "strat-1", _dt(2025, 1, 15), Decimal("-20"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        calc = MetricsCalculator(trade_repo)
        evaluator = Evaluator(calc, metrics_repo, report_repo)
        result = await evaluator.evaluate(
            "strat-1", "ver-1", None,
            _dt(2025, 1, 1), _dt(2025, 1, 31),
            config=None,
        )
        await session.commit()
    assert isinstance(result, EvaluationReportResult)
    assert result.objective_definition is not None
    assert result.constraint_definition is not None
    assert result.baseline_version_id is None  # config=None -> default null
    assert result.conclusion in ("pass", "fail")
    assert result.comparison_summary is None  # no baseline
    assert result.strategy_version_id == "ver-1"
    assert result.metrics_snapshot_id is not None

    async with session_factory() as session:
        stmt = select(func.count()).select_from(EvaluationReport)
        count = (await session.execute(stmt)).scalar()
    assert count == 1
    async with session_factory() as session:
        stmt = select(EvaluationReport).limit(1)
        row = (await session.execute(stmt)).scalar_one()
    assert row.strategy_version_id == "ver-1"
    assert row.objective_definition is not None
    assert row.constraint_definition is not None
    assert row.baseline_version_id is None
    assert row.conclusion in ("pass", "fail")
    assert "建议参数" not in (row.conclusion or "")
    assert "可写回" not in (row.conclusion or "")
    assert "供优化" not in (row.conclusion or "")


@pytest.mark.asyncio
async def test_evaluate_b1_structure(session_factory):
    """B.1 结构：objective 含 primary、primary_weight、secondary、secondary_weights；constraint 含 max_drawdown_pct、min_trade_count、max_risk_exposure、custom。"""
    async with session_factory() as session:
        await _create_trade(session, "a1", "s", _dt(2025, 2, 1), Decimal("10"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        result = await evaluator.evaluate(
            "s", "v", None, _dt(2025, 2, 1), _dt(2025, 2, 28), config=None
        )
        await session.commit()
    obj = result.objective_definition
    assert "primary" in obj
    assert "primary_weight" in obj
    assert "secondary" in obj
    assert "secondary_weights" in obj
    con = result.constraint_definition
    assert "max_drawdown_pct" in con
    assert "min_trade_count" in con
    assert "max_risk_exposure" in con
    assert "custom" in con


@pytest.mark.asyncio
async def test_evaluate_baseline_version_id_is_strategy_version_only(session_factory):
    """baseline_version_id 为 null 或某 strategy_version_id（非 param_version_id）；report.strategy_version_id 存在。"""
    async with session_factory() as session:
        await _create_trade(session, "b1", "strat-b", _dt(2025, 3, 1), Decimal("50"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        result = await evaluator.evaluate(
            "strat-b", "ver-current", "param-xyz",
            _dt(2025, 3, 1), _dt(2025, 3, 31),
            config=EvaluatorConfig(baseline_version_id="ver-baseline"),
        )
        await session.commit()
    assert result.strategy_version_id == "ver-current"
    assert result.baseline_version_id == "ver-baseline"  # 仅存 strategy_version_id 语义，测试传入合法值


@pytest.mark.asyncio
async def test_baseline_rejects_param_version_id(session_factory):
    """baseline_version_id 不得等于 param_version_id（禁止使用 param_version_id 作为 baseline）。"""
    async with session_factory() as session:
        await _create_trade(session, "bp1", "strat-bp", _dt(2025, 3, 1), Decimal("10"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        with pytest.raises(ValueError) as exc:
            await evaluator.evaluate(
                "strat-bp", "ver-bp", "param-baseline",
                _dt(2025, 3, 1), _dt(2025, 3, 31),
                config=EvaluatorConfig(baseline_version_id="param-baseline"),
            )
    msg = str(exc.value)
    assert "baseline_version_id" in msg
    assert "strategy_version_id" in msg


@pytest.mark.asyncio
async def test_evaluate_read_only_phase12_unchanged(session_factory):
    """只读边界：evaluate 执行前后 Phase 1.2 表（trade）无任何写操作。"""
    async with session_factory() as session:
        await _create_trade(session, "r1", "strat-r", _dt(2025, 4, 1), Decimal("1"))
        await _create_trade(session, "r2", "strat-r", _dt(2025, 4, 2), Decimal("2"))
    async with session_factory() as session:
        stmt = select(func.count()).select_from(Trade)
        count_before = (await session.execute(stmt)).scalar()
    assert count_before == 2

    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        await evaluator.evaluate(
            "strat-r", "ver-r", None,
            _dt(2025, 4, 1), _dt(2025, 4, 30),
            config=None,
        )
        await session.commit()

    async with session_factory() as session:
        stmt = select(func.count()).select_from(Trade)
        count_after = (await session.execute(stmt)).scalar()
    assert count_after == 2
    assert count_after == count_before


@pytest.mark.asyncio
async def test_conclusion_and_comparison_no_suggest_wording(session_factory):
    """结论与 comparison_summary 中无「建议参数」「可写回」「供优化」等措辞。"""
    async with session_factory() as session:
        await _create_trade(session, "c1", "strat-c", _dt(2025, 5, 1), Decimal("10"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        result = await evaluator.evaluate(
            "strat-c", "ver-c", None,
            _dt(2025, 5, 1), _dt(2025, 5, 31),
            config=None,
        )
        await session.commit()
    forbidden = ("建议参数", "可写回", "供优化")
    for word in forbidden:
        assert word not in (result.conclusion or "")
    if result.comparison_summary:
        summary_str = str(result.comparison_summary)
        for word in forbidden:
            assert word not in summary_str


@pytest.mark.asyncio
async def test_constraint_min_trade_count_fail(session_factory):
    """约束 min_trade_count 未满足时 conclusion 为 fail。"""
    async with session_factory() as session:
        await _create_trade(session, "m1", "strat-m", _dt(2025, 6, 1), Decimal("1"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        result = await evaluator.evaluate(
            "strat-m", "ver-m", None,
            _dt(2025, 6, 1), _dt(2025, 6, 30),
            config=EvaluatorConfig(
                constraint_definition={"min_trade_count": 10, "max_drawdown_pct": None, "max_risk_exposure": None, "custom": None},
            ),
        )
        await session.commit()
    assert result.trade_count == 1
    assert result.conclusion == "fail"


@pytest.mark.asyncio
async def test_constraint_min_trade_count_pass(session_factory):
    """约束 min_trade_count 满足时 conclusion 为 pass。"""
    async with session_factory() as session:
        for i in range(5):
            await _create_trade(session, f"p{i}", "strat-p", _dt(2025, 7, i + 1), Decimal("1"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        result = await evaluator.evaluate(
            "strat-p", "ver-p", None,
            _dt(2025, 7, 1), _dt(2025, 7, 31),
            config=EvaluatorConfig(
                constraint_definition={"min_trade_count": 3, "max_drawdown_pct": None, "max_risk_exposure": None, "custom": None},
            ),
        )
        await session.commit()
    assert result.trade_count == 5
    assert result.conclusion == "pass"


@pytest.mark.asyncio
async def test_evaluate_same_period_not_duplicate_snapshot(session_factory):
    """同一 strategy/version/param + 周期重复 evaluate，不应产生重复 metrics_snapshot，且 snapshot id 复用。"""
    async with session_factory() as session:
        # 构造 2 笔 trade，用于生成非零指标
        await _create_trade(session, "d1", "strat-d", _dt(2025, 8, 1), Decimal("10"))
        await _create_trade(session, "d2", "strat-d", _dt(2025, 8, 2), Decimal("-5"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)

        result1 = await evaluator.evaluate(
            "strat-d", "ver-d", "param-d",
            _dt(2025, 8, 1), _dt(2025, 8, 31),
            config=None,
        )
        result2 = await evaluator.evaluate(
            "strat-d", "ver-d", "param-d",
            _dt(2025, 8, 1), _dt(2025, 8, 31),
            config=None,
        )
        await session.commit()

        # 两次返回的 metrics_snapshot_id 必须相同（复用同一快照）
        assert result1.metrics_snapshot_id is not None
        assert result1.metrics_snapshot_id == result2.metrics_snapshot_id

        # metrics_snapshot 表中该周期只存在 1 条记录
        stmt = select(func.count()).select_from(MetricsSnapshot).where(
            MetricsSnapshot.strategy_id == "strat-d",
            MetricsSnapshot.strategy_version_id == "ver-d",
            MetricsSnapshot.param_version_id == "param-d",
            MetricsSnapshot.period_start == _dt(2025, 8, 1),
            MetricsSnapshot.period_end == _dt(2025, 8, 31),
        )
        count = (await session.execute(stmt)).scalar()
        assert count == 1


@pytest.mark.asyncio
async def test_constraint_max_drawdown_pct_fail(session_factory):
    """max_drawdown_pct 约束：当实际 max_drawdown 大于阈值时 conclusion 为 fail。"""
    async with session_factory() as session:
        # 构造 max_drawdown = 5 的场景：10 -> -5 -> 0
        await _create_trade(session, "md1", "strat-md", _dt(2025, 9, 1), Decimal("10"))
        await _create_trade(session, "md2", "strat-md", _dt(2025, 9, 2), Decimal("-15"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        result = await evaluator.evaluate(
            "strat-md", "ver-md", None,
            _dt(2025, 9, 1), _dt(2025, 9, 30),
            config=EvaluatorConfig(
                constraint_definition={
                    "min_trade_count": None,
                    "max_drawdown_pct": 1,  # 阈值远小于实际 max_drawdown
                    "max_risk_exposure": None,
                    "custom": None,
                },
            ),
        )
        await session.commit()
    assert result.conclusion == "fail"


@pytest.mark.asyncio
async def test_constraint_max_drawdown_pct_pass(session_factory):
    """max_drawdown_pct 约束：当实际 max_drawdown 小于等于阈值时 conclusion 为 pass。"""
    async with session_factory() as session:
        await _create_trade(session, "mp1", "strat-mp", _dt(2025, 10, 1), Decimal("10"))
        await _create_trade(session, "mp2", "strat-mp", _dt(2025, 10, 2), Decimal("-5"))
    async with session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        result = await evaluator.evaluate(
            "strat-mp", "ver-mp", None,
            _dt(2025, 10, 1), _dt(2025, 10, 31),
            config=EvaluatorConfig(
                constraint_definition={
                    "min_trade_count": None,
                    "max_drawdown_pct": 100,  # 阈值远大于实际 max_drawdown
                    "max_risk_exposure": None,
                    "custom": None,
                },
            ),
        )
        await session.commit()
    assert result.conclusion == "pass"
