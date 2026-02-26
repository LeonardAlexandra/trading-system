"""
Phase1.1 D2：EXTERNAL_SYNC 定价优先级测试

验证 C3 定价优先级（交易所价 > 本地参考价 > 兜底价）被正确执行，
且落库 trade 的 price 与预期档位一致。覆盖三档及多档同时存在取最高优先。
封版：幂等 DB 兜底（IntegrityError 视为成功）、并发 reconcile、price_tier 落盘。
"""
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db_session, set_session_factory
from src.database.connection import Base
from src.execution.position_manager import (
    PositionManager,
    ReconcileItem,
    resolve_price_and_tier,
    PRICE_TIER_EXCHANGE,
    PRICE_TIER_LOCAL_REF,
    PRICE_TIER_FALLBACK,
)
from src.models.trade import Trade, SOURCE_TYPE_EXTERNAL_SYNC
from src.repositories.trade_repo import TradeRepository
from src.models.position_reconcile_log import PositionReconcileLog, SYNC_TRADE
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig


@pytest.fixture
async def d2_session_factory(db_session_factory):
    set_session_factory(db_session_factory)
    yield db_session_factory


def _ensure_runtime_state(session: AsyncSession, strategy_id: str):
    """C1 前置：ReconcileLock 需要 strategy_runtime_state 行存在。"""
    from sqlalchemy import text
    return session.execute(
        text(
            "INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, lock_ttl_seconds) VALUES (:sid, 30)"
        ),
        {"sid": strategy_id},
    )


@pytest.mark.asyncio
async def test_resolve_price_tier_exchange_first():
    """有交易所价时，使用交易所价（第一档）。"""
    item = ReconcileItem(
        external_trade_id="ext-1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("1"),
        exchange_price=Decimal("50000"),
        local_ref_price=Decimal("49900"),
        fallback_price=Decimal("48000"),
    )
    price, tier = resolve_price_and_tier(item)
    assert price == Decimal("50000")
    assert tier == PRICE_TIER_EXCHANGE


@pytest.mark.asyncio
async def test_resolve_price_tier_local_ref_when_no_exchange():
    """无交易所价、有本地参考价时，使用本地参考价（第二档）。"""
    item = ReconcileItem(
        external_trade_id="ext-2",
        symbol="BTCUSDT",
        side="SELL",
        quantity=Decimal("0.5"),
        exchange_price=None,
        local_ref_price=Decimal("50100"),
        fallback_price=Decimal("48000"),
    )
    price, tier = resolve_price_and_tier(item)
    assert price == Decimal("50100")
    assert tier == PRICE_TIER_LOCAL_REF


@pytest.mark.asyncio
async def test_resolve_price_tier_fallback_only():
    """仅兜底价时，使用兜底价（第三档）。"""
    item = ReconcileItem(
        external_trade_id="ext-3",
        symbol="ETHUSDT",
        side="BUY",
        quantity=Decimal("2"),
        exchange_price=None,
        local_ref_price=None,
        fallback_price=Decimal("3000"),
    )
    price, tier = resolve_price_and_tier(item)
    assert price == Decimal("3000")
    assert tier == PRICE_TIER_FALLBACK


@pytest.mark.asyncio
async def test_resolve_price_tier_missing_all_raises():
    """三档皆无时报错。"""
    item = ReconcileItem(
        external_trade_id="ext-x",
        symbol="X",
        side="BUY",
        quantity=Decimal("1"),
        exchange_price=None,
        local_ref_price=None,
        fallback_price=None,
    )
    with pytest.raises(ValueError) as exc_info:
        resolve_price_and_tier(item)
    assert "at least one" in str(exc_info.value).lower() or "exchange_price" in str(exc_info.value)


# ---------- D2 落库校验：reconcile 后 EXTERNAL_SYNC trade 的 price 与档位一致 ----------

async def _run_reconcile_and_get_trade(
    session_factory,
    strategy_id: str,
    items: list,
) -> Trade:
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
            await pm.reconcile(session, strategy_id, items, lock_holder_id="d2-test", risk_manager=risk_manager)
    async with get_db_session() as session:
        result = await session.execute(
            select(Trade).where(
                Trade.strategy_id == strategy_id,
                Trade.source_type == SOURCE_TYPE_EXTERNAL_SYNC,
                Trade.external_trade_id == items[0].external_trade_id,
            )
        )
        return result.scalar_one()


@pytest.mark.asyncio
async def test_d2_external_sync_trade_uses_exchange_price(d2_session_factory):
    """D2：有交易所价时，EXTERNAL_SYNC trade 使用交易所价。"""
    set_session_factory(d2_session_factory)
    strategy_id = "D2_STRAT_EX"
    items = [
        ReconcileItem(
            external_trade_id="d2-ex-001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("1"),
            exchange_price=Decimal("60000"),
            local_ref_price=Decimal("59000"),
            fallback_price=Decimal("50000"),
        ),
    ]
    trade = await _run_reconcile_and_get_trade(d2_session_factory, strategy_id, items)
    assert trade is not None
    assert trade.source_type == SOURCE_TYPE_EXTERNAL_SYNC
    assert trade.external_trade_id == "d2-ex-001"
    assert trade.price == Decimal("60000")


@pytest.mark.asyncio
async def test_d2_external_sync_trade_uses_local_ref_when_no_exchange(d2_session_factory):
    """D2：无交易所价、有本地参考价时，使用本地参考价。"""
    set_session_factory(d2_session_factory)
    strategy_id = "D2_STRAT_LR"
    items = [
        ReconcileItem(
            external_trade_id="d2-lr-001",
            symbol="ETHUSDT",
            side="SELL",
            quantity=Decimal("2"),
            exchange_price=None,
            local_ref_price=Decimal("3500"),
            fallback_price=Decimal("3000"),
        ),
    ]
    trade = await _run_reconcile_and_get_trade(d2_session_factory, strategy_id, items)
    assert trade is not None
    assert trade.source_type == SOURCE_TYPE_EXTERNAL_SYNC
    assert trade.price == Decimal("3500")


@pytest.mark.asyncio
async def test_d2_external_sync_trade_uses_fallback_only(d2_session_factory):
    """D2：仅兜底价时，使用兜底价。"""
    set_session_factory(d2_session_factory)
    strategy_id = "D2_STRAT_FB"
    items = [
        ReconcileItem(
            external_trade_id="d2-fb-001",
            symbol="SOLUSDT",
            side="BUY",
            quantity=Decimal("10"),
            exchange_price=None,
            local_ref_price=None,
            fallback_price=Decimal("100"),
        ),
    ]
    trade = await _run_reconcile_and_get_trade(d2_session_factory, strategy_id, items)
    assert trade is not None
    assert trade.source_type == SOURCE_TYPE_EXTERNAL_SYNC
    assert trade.price == Decimal("100")


@pytest.mark.asyncio
async def test_d2_reconcile_updates_position_and_writes_log(d2_session_factory):
    """reconcile 后 position 与 position_reconcile_log 均有记录（同一事务）。"""
    set_session_factory(d2_session_factory)

    strategy_id = "D2_STRAT_PL"
    external_trade_id = "d2-pl-001"
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
                session,
                strategy_id,
                [
                    ReconcileItem(
                        external_trade_id=external_trade_id,
                        symbol="BTCUSDT",
                        side="BUY",
                        quantity=Decimal("0.1"),
                        fallback_price=Decimal("50000"),
                    ),
                ],
                lock_holder_id="d2-test",
                risk_manager=risk_manager,
            )
    async with get_db_session() as session:
        position_repo = PositionRepository(session)
        pos = await position_repo.get(strategy_id, "BTCUSDT")
        stmt_log = select(PositionReconcileLog).where(
            PositionReconcileLog.strategy_id == strategy_id,
            PositionReconcileLog.event_type == SYNC_TRADE,
            PositionReconcileLog.external_trade_id == external_trade_id,
        )
        r2 = await session.execute(stmt_log)
        log_row = r2.scalar_one_or_none()
    assert pos is not None
    assert pos.quantity == Decimal("0.1")
    assert log_row is not None
    assert log_row.external_trade_id == external_trade_id
    assert log_row.event_type == SYNC_TRADE
    assert log_row.price_tier == PRICE_TIER_FALLBACK


@pytest.mark.asyncio
async def test_d2_price_tier_persisted_in_reconcile_log(d2_session_factory):
    """封版：price_tier 必须落盘，SYNC_TRADE 时写入 position_reconcile_log.price_tier。"""
    set_session_factory(d2_session_factory)
    from src.models.position_reconcile_log import PositionReconcileLog, SYNC_TRADE

    strategy_id = "D2_STRAT_TIER"
    for tier_name, item in [
        (PRICE_TIER_EXCHANGE, ReconcileItem("d2-tier-ex", "BTCUSDT", "BUY", Decimal("1"), exchange_price=Decimal("60000"), fallback_price=Decimal("50000"))),
        (PRICE_TIER_LOCAL_REF, ReconcileItem("d2-tier-lr", "ETHUSDT", "BUY", Decimal("1"), local_ref_price=Decimal("3500"), fallback_price=Decimal("3000"))),
        (PRICE_TIER_FALLBACK, ReconcileItem("d2-tier-fb", "SOLUSDT", "BUY", Decimal("1"), fallback_price=Decimal("100"))),
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
                await pm.reconcile(session, strategy_id, [item], lock_holder_id="d2-test", risk_manager=risk_manager)
        async with get_db_session() as session:
            r = await session.execute(
                select(PositionReconcileLog).where(
                    PositionReconcileLog.strategy_id == strategy_id,
                    PositionReconcileLog.external_trade_id == item.external_trade_id,
                    PositionReconcileLog.event_type == SYNC_TRADE,
                )
            )
            log_row = r.scalar_one_or_none()
        assert log_row is not None, f"missing log for {item.external_trade_id}"
        assert log_row.price_tier == tier_name, f"expected price_tier={tier_name} got {log_row.price_tier}"


@pytest.mark.asyncio
async def test_c3_concurrent_reconcile_same_external_trade_id(d2_session_factory):
    """封版：两并发会话对同一 (strategy_id, external_trade_id) reconcile，最终仅 1 条 trade，position/log 不重复不一致。"""
    import asyncio
    from src.execution.position_manager import ReconcileLockNotAcquiredError

    set_session_factory(d2_session_factory)
    strategy_id = "C3_CONCURRENT"
    external_trade_id = "c3-con-001"
    item = ReconcileItem(
        external_trade_id=external_trade_id,
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("0.5"),
        fallback_price=Decimal("50000"),
    )
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.commit()

    results = []
    async def run_reconcile(session_factory, sid: str):
        async with get_db_session() as session:
            async with session.begin():
                trade_repo = TradeRepository(session)
                position_repo = PositionRepository(session)
                log_repo = PositionReconcileLogRepository(session)
                risk_manager = RiskManager(position_repo=position_repo, risk_config=RiskConfig())
                pm = PositionManager(trade_repo, position_repo, log_repo)
                try:
                    out = await pm.reconcile(session, sid, [item], lock_holder_id="c3-con-test", risk_manager=risk_manager)
                    results.append(("ok", out))
                except ReconcileLockNotAcquiredError:
                    results.append(("lock_fail", None))

    await asyncio.gather(
        run_reconcile(d2_session_factory, strategy_id),
        run_reconcile(d2_session_factory, strategy_id),
    )
    ok_count = sum(1 for t, _ in results if t == "ok")
    fail_count = sum(1 for t, _ in results if t == "lock_fail")
    assert ok_count >= 1 and fail_count + ok_count == 2

    async with get_db_session() as session:
        r = await session.execute(
            select(Trade).where(
                Trade.strategy_id == strategy_id,
                Trade.external_trade_id == external_trade_id,
            )
        )
        trades = list(r.scalars().all())
        r2 = await session.execute(
            select(PositionReconcileLog).where(
                PositionReconcileLog.strategy_id == strategy_id,
                PositionReconcileLog.event_type == SYNC_TRADE,
                PositionReconcileLog.external_trade_id == external_trade_id,
            )
        )
        logs = list(r2.scalars().all())
        pos_repo = PositionRepository(session)
        pos = await pos_repo.get(strategy_id, "BTCUSDT")
    assert len(trades) == 1, "must have exactly one trade"
    assert len(logs) == 1, "must have exactly one SYNC_TRADE log"
    assert pos is not None and pos.quantity == Decimal("0.5")


@pytest.mark.asyncio
async def test_c3_idempotent_integrity_error_treated_as_success(d2_session_factory):
    """封版：UNIQUE 冲突时捕获 IntegrityError 视为幂等成功，reconcile 不整体失败。"""
    set_session_factory(d2_session_factory)
    strategy_id = "C3_IDEM_IE"
    external_trade_id = "c3-ie-001"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.commit()
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            t = Trade(
                trade_id=f"EXTSYNC:{strategy_id}:{external_trade_id}",
                strategy_id=strategy_id,
                source_type=SOURCE_TYPE_EXTERNAL_SYNC,
                external_trade_id=external_trade_id,
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("50000"),
                slippage=Decimal("0"),
                realized_pnl=Decimal("0"),
                executed_at=datetime.now(timezone.utc),
                is_simulated=False,
            )
            await trade_repo.create(t)
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            trade_repo.get_by_strategy_external_trade_id = AsyncMock(return_value=None)
            risk_manager = RiskManager(position_repo=position_repo, risk_config=RiskConfig())
            pm = PositionManager(trade_repo, position_repo, log_repo)
            out = await pm.reconcile(
                session,
                strategy_id,
                [
                    ReconcileItem(
                        external_trade_id=external_trade_id,
                        symbol="BTCUSDT",
                        side="BUY",
                        quantity=Decimal("1"),
                        fallback_price=Decimal("50000"),
                    ),
                ],
                lock_holder_id="c3-ie-test",
                risk_manager=risk_manager,
            )
    assert out["skipped_idempotent"] == 1
    assert out["synced"] == 0
    async with get_db_session() as session:
        r = await session.execute(
            select(Trade).where(
                Trade.strategy_id == strategy_id,
                Trade.external_trade_id == external_trade_id,
            )
        )
        trades = list(r.scalars().all())
    assert len(trades) == 1


@pytest.mark.asyncio
async def test_d2_idempotent_skip_duplicate_external_trade_id(d2_session_factory):
    """同一 (strategy_id, external_trade_id) 重复 reconcile 不产生重复 trade，可审计。"""
    set_session_factory(d2_session_factory)
    strategy_id = "D2_STRAT_IDEM"
    external_trade_id = "d2-idem-001"
    items = [
        ReconcileItem(
            external_trade_id=external_trade_id,
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("1"),
            fallback_price=Decimal("50000"),
        ),
    ]
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.commit()
    # 第一次
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_manager = RiskManager(position_repo=position_repo, risk_config=RiskConfig())
            pm = PositionManager(trade_repo, position_repo, log_repo)
            out1 = await pm.reconcile(session, strategy_id, items, lock_holder_id="d2-test", risk_manager=risk_manager)
    # 第二次（幂等：应跳过）
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_manager = RiskManager(position_repo=position_repo, risk_config=RiskConfig())
            pm = PositionManager(trade_repo, position_repo, log_repo)
            out2 = await pm.reconcile(session, strategy_id, items, lock_holder_id="d2-test", risk_manager=risk_manager)
    assert out1["synced"] == 1
    assert out2["skipped_idempotent"] == 1
    async with get_db_session() as session:
        result = await session.execute(
            select(Trade).where(
                Trade.strategy_id == strategy_id,
                Trade.external_trade_id == external_trade_id,
            )
        )
        trades = list(result.scalars().all())
    assert len(trades) == 1
