"""
Phase 2.0: D1: E2E-2.0 主流程可验证点

验证闭环：
1. 指定策略+版本+时间范围
2. 调用 MetricsCalculator.compute 计算指标
3. 调用 Evaluator.evaluate 生成评估报告
4. 报告自动持久化到 evaluation_report 表
5. 通过 EvaluationReportRepository 按 strategy_version_id / evaluated_at / param_version_id 能够准确查询到该报告

验收标准：
- 报告中包含 0.2 五项核心内容（objective_definition, constraint_definition, baseline_version_id, conclusion, comparison_summary）
- 报告能够通过不同维度查询
- 全过程对 Phase 1.2 数据（Trade表）为只读，无任何修改
"""
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, func

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


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
async def e2e_session_factory():
    """使用内存 SQLite 进行 E2E 验证，包含所有必要的表结构。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    yield session_factory
    await engine.dispose()


async def _setup_mock_trades(session: AsyncSession, strategy_id: str):
    """准备 Phase 1.2 Mock 数据：3 笔交易。"""
    trade_repo = TradeRepository(session)
    trades = [
        Trade(
            trade_id="T1", strategy_id=strategy_id, symbol="BTCUSDT", side="BUY",
            quantity=Decimal("1"), price=Decimal("50000"), realized_pnl=Decimal("100"),
            executed_at=_dt(2025, 1, 10, 10, 0)
        ),
        Trade(
            trade_id="T2", strategy_id=strategy_id, symbol="BTCUSDT", side="SELL",
            quantity=Decimal("1"), price=Decimal("51000"), realized_pnl=Decimal("200"),
            executed_at=_dt(2025, 1, 15, 10, 0)
        ),
        Trade(
            trade_id="T3", strategy_id=strategy_id, symbol="BTCUSDT", side="BUY",
            quantity=Decimal("1"), price=Decimal("49000"), realized_pnl=Decimal("-50"),
            executed_at=_dt(2025, 1, 20, 10, 0)
        ),
    ]
    for t in trades:
        await trade_repo.create(t)
    await session.commit()


@pytest.mark.asyncio
async def test_phase20_d1_e2e_flow(e2e_session_factory):
    strategy_id = "STRAT-E2E-01"
    strategy_version_id = "V1.0"
    param_version_id = "P1.0-ALPHA"
    period_start = _dt(2025, 1, 1)
    period_end = _dt(2025, 1, 31)

    # 1. 数据准备
    async with e2e_session_factory() as session:
        await _setup_mock_trades(session, strategy_id)
        # 记录初始状态用于只读验证
        trade_count_before = (await session.execute(select(func.count()).select_from(Trade))).scalar()
        assert trade_count_before == 3

    # 2. 执行评估流程
    async with e2e_session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        
        calc = MetricsCalculator(trade_repo)
        evaluator = Evaluator(calc, metrics_repo, report_repo)
        
        # 配置评估参数
        config = EvaluatorConfig(
            objective_definition={
                "primary": "realized_pnl",
                "primary_weight": 1.0,
                "secondary": [],
                "secondary_weights": []
            },
            constraint_definition={
                "min_trade_count": 2,
                "max_drawdown_pct": 1000  # 宽松约束
            }
        )
        
        # 执行评估
        result = await evaluator.evaluate(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            period_start=period_start,
            period_end=period_end,
            config=config
        )
        await session.commit()
        
        assert result.strategy_id == strategy_id
        assert result.conclusion == "pass"  # 3 > 2 笔，应通过

    # 3. 验证持久化与只读性
    async with e2e_session_factory() as session:
        # 验证 Phase 1.2 数据未变（只读验证）
        trade_count_after = (await session.execute(select(func.count()).select_from(Trade))).scalar()
        assert trade_count_after == trade_count_before
        
        # 验证 Phase 2.0 数据已写入
        report_count = (await session.execute(select(func.count()).select_from(EvaluationReport))).scalar()
        assert report_count == 1
        
        snapshot_count = (await session.execute(select(func.count()).select_from(MetricsSnapshot))).scalar()
        assert snapshot_count == 1

    # 4. 验证多维度查询能力
    async with e2e_session_factory() as session:
        report_repo = EvaluationReportRepository(session)
        
        # A. 按 strategy_version_id 查询
        reports_v = await report_repo.get_by_strategy_version(strategy_version_id)
        assert len(reports_v) == 1
        assert reports_v[0].strategy_version_id == strategy_version_id
        
        # B. 按 evaluated_at 时间范围查询
        now = datetime.now(timezone.utc)
        reports_t = await report_repo.get_by_evaluated_at(
            strategy_id, 
            now - timedelta(minutes=5), 
            now + timedelta(minutes=5)
        )
        assert len(reports_t) == 1
        
        # C. 按 param_version_id 查询
        reports_p = await report_repo.get_by_param_version(param_version_id)
        assert len(reports_p) == 1
        assert reports_p[0].param_version_id == param_version_id

        # 验证 0.2 五项核心内容
        report = reports_v[0]
        assert "primary" in report.objective_definition
        assert "min_trade_count" in report.constraint_definition
        assert report.baseline_version_id is None
        assert report.conclusion in ("pass", "fail")
        # 由于是第一次评估且无基线，comparison_summary 应为 None 或符合预期
        assert report.comparison_summary is None or isinstance(report.comparison_summary, dict)

    # 5. 验证可重复性 (Repeatability)
    async with e2e_session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        
        # 再次执行相同的评估
        result2 = await evaluator.evaluate(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            period_start=period_start,
            period_end=period_end,
            config=config
        )
        await session.commit()
        
        # 验证两次结果一致（核心字段）
        assert result2.conclusion == result.conclusion
        assert result2.objective_definition == result.objective_definition
        assert result2.constraint_definition == result.constraint_definition

    # 6. 验证基线对比 (Baseline)
    async with e2e_session_factory() as session:
        trade_repo = TradeRepository(session)
        metrics_repo = MetricsRepository(session)
        report_repo = EvaluationReportRepository(session)
        evaluator = Evaluator(MetricsCalculator(trade_repo), metrics_repo, report_repo)
        
        # 传入 baseline_version_id = strategy_version_id (自身对比)
        config_with_baseline = EvaluatorConfig(
            baseline_version_id=strategy_version_id
        )
        
        result_baseline = await evaluator.evaluate(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            period_start=period_start,
            period_end=period_end,
            config=config_with_baseline
        )
        await session.commit()
        
        assert result_baseline.baseline_version_id == strategy_version_id
        assert result_baseline.comparison_summary is not None
        assert "delta" in result_baseline.comparison_summary
        # 自身对比，delta 应为 0
        assert result_baseline.comparison_summary["delta"]["trade_count"] == 0
