"""
Phase1.1 D2：EXTERNAL_SYNC 定价优先级测试（独立测试文件）

验证 C3 定价优先级（交易所价 > 本地参考价 > 兜底价）被正确执行，
落库 trade 的 price 与预期档位一致；覆盖三档及多档同时存在时取最高优先。
使用 mock/fixture 数据，不依赖真实交易所。
"""
from decimal import Decimal
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db_session, set_session_factory
from src.execution.position_manager import (
    PositionManager,
    ReconcileItem,
    PRICE_TIER_EXCHANGE,
    PRICE_TIER_LOCAL_REF,
    PRICE_TIER_FALLBACK,
)
from src.models.trade import Trade, SOURCE_TYPE_EXTERNAL_SYNC
from src.models.position_reconcile_log import PositionReconcileLog, SYNC_TRADE
from src.repositories.trade_repo import TradeRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig


@pytest.fixture
async def d2_pricing_session_factory(db_session_factory):
    set_session_factory(db_session_factory)
    yield db_session_factory


async def _ensure_runtime_state(session: AsyncSession, strategy_id: str):
    """C1 前置：ReconcileLock 需要 strategy_runtime_state 行存在。"""
    await session.execute(
        text(
            "INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, lock_ttl_seconds) VALUES (:sid, 30)"
        ),
        {"sid": strategy_id},
    )
    await session.flush()


async def _run_reconcile_and_get_trade(session_factory, strategy_id: str, items: list) -> Trade:
    """执行 reconcile 后查询 EXTERNAL_SYNC trade（mock 数据，不依赖真实交易所）。"""
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.commit()
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_manager = RiskManager(position_repo=position_repo, risk_config=RiskConfig())
            pm = PositionManager(trade_repo, position_repo, log_repo)
            await pm.reconcile(
                session, strategy_id, items,
                lock_holder_id="d2-pricing-test",
                risk_manager=risk_manager,
            )
    async with get_db_session() as session:
        r = await session.execute(
            select(Trade).where(
                Trade.strategy_id == strategy_id,
                Trade.source_type == SOURCE_TYPE_EXTERNAL_SYNC,
                Trade.external_trade_id == items[0].external_trade_id,
            )
        )
        return r.scalar_one()


@pytest.mark.asyncio
async def test_d2_exchange_price_used_when_present(d2_pricing_session_factory):
    """D2：有交易所价时，EXTERNAL_SYNC trade 使用交易所价。"""
    set_session_factory(d2_pricing_session_factory)
    strategy_id = "D2_PRIO_EX"
    items = [
        ReconcileItem(
            external_trade_id="d2-prio-ex-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("1"),
            exchange_price=Decimal("60000"),
            local_ref_price=Decimal("59000"),
            fallback_price=Decimal("50000"),
        ),
    ]
    trade = await _run_reconcile_and_get_trade(d2_pricing_session_factory, strategy_id, items)
    assert trade is not None
    assert trade.source_type == SOURCE_TYPE_EXTERNAL_SYNC
    assert trade.price == Decimal("60000")


@pytest.mark.asyncio
async def test_d2_local_ref_used_when_no_exchange(d2_pricing_session_factory):
    """D2：无交易所价、有本地参考价时，使用本地参考价。"""
    set_session_factory(d2_pricing_session_factory)
    strategy_id = "D2_PRIO_LR"
    items = [
        ReconcileItem(
            external_trade_id="d2-prio-lr-001",
            symbol="ETHUSDT",
            side="SELL",
            quantity=Decimal("2"),
            exchange_price=None,
            local_ref_price=Decimal("3500"),
            fallback_price=Decimal("3000"),
        ),
    ]
    trade = await _run_reconcile_and_get_trade(d2_pricing_session_factory, strategy_id, items)
    assert trade is not None
    assert trade.source_type == SOURCE_TYPE_EXTERNAL_SYNC
    assert trade.price == Decimal("3500")


@pytest.mark.asyncio
async def test_d2_fallback_used_when_only_fallback(d2_pricing_session_factory):
    """D2：仅兜底价时，使用兜底价。"""
    set_session_factory(d2_pricing_session_factory)
    strategy_id = "D2_PRIO_FB"
    items = [
        ReconcileItem(
            external_trade_id="d2-prio-fb-001",
            symbol="SOLUSDT",
            side="BUY",
            quantity=Decimal("10"),
            exchange_price=None,
            local_ref_price=None,
            fallback_price=Decimal("100"),
        ),
    ]
    trade = await _run_reconcile_and_get_trade(d2_pricing_session_factory, strategy_id, items)
    assert trade is not None
    assert trade.source_type == SOURCE_TYPE_EXTERNAL_SYNC
    assert trade.price == Decimal("100")


@pytest.mark.asyncio
async def test_d2_multi_tier_takes_highest_priority(d2_pricing_session_factory):
    """D2：多档同时存在时取最高优先（交易所价 > 本地 > 兜底）。"""
    set_session_factory(d2_pricing_session_factory)
    strategy_id = "D2_PRIO_MULTI"
    items = [
        ReconcileItem(
            external_trade_id="d2-prio-multi-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.5"),
            exchange_price=Decimal("62000"),
            local_ref_price=Decimal("61000"),
            fallback_price=Decimal("50000"),
        ),
    ]
    trade = await _run_reconcile_and_get_trade(d2_pricing_session_factory, strategy_id, items)
    assert trade is not None
    assert trade.price == Decimal("62000")


@pytest.mark.asyncio
async def test_d2_price_tier_persisted_in_log(d2_pricing_session_factory):
    """D2 可选：position_reconcile_log 中记录使用的优先级档位（price_tier）。"""
    set_session_factory(d2_pricing_session_factory)
    strategy_id = "D2_PRIO_LOG"
    for expected_tier, item in [
        (PRICE_TIER_EXCHANGE, ReconcileItem("d2-log-ex", "BTCUSDT", "BUY", Decimal("1"), exchange_price=Decimal("60000"), fallback_price=Decimal("50000"))),
        (PRICE_TIER_LOCAL_REF, ReconcileItem("d2-log-lr", "ETHUSDT", "BUY", Decimal("1"), local_ref_price=Decimal("3500"), fallback_price=Decimal("3000"))),
        (PRICE_TIER_FALLBACK, ReconcileItem("d2-log-fb", "SOLUSDT", "BUY", Decimal("1"), fallback_price=Decimal("100"))),
    ]:
        async with get_db_session() as session:
            await _ensure_runtime_state(session, strategy_id)
            await session.commit()
        async with get_db_session() as session:
            async with session.begin():
                trade_repo = TradeRepository(session)
                position_repo = PositionRepository(session)
                log_repo = PositionReconcileLogRepository(session)
                risk_manager = RiskManager(position_repo=position_repo, risk_config=RiskConfig())
                pm = PositionManager(trade_repo, position_repo, log_repo)
                await pm.reconcile(
                    session, strategy_id, [item],
                    lock_holder_id="d2-pricing-test",
                    risk_manager=risk_manager,
                )
        async with get_db_session() as session:
            r = await session.execute(
                select(PositionReconcileLog).where(
                    PositionReconcileLog.strategy_id == strategy_id,
                    PositionReconcileLog.external_trade_id == item.external_trade_id,
                    PositionReconcileLog.event_type == SYNC_TRADE,
                )
            )
            log_row = r.scalar_one_or_none()
        assert log_row is not None
        assert log_row.price_tier == expected_tier
