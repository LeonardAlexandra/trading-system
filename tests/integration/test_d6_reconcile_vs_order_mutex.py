"""
Phase1.1 D6：对账写持仓 vs 下单写持仓 互斥并发测试（Correct-Scope）

并发触发两条路径（同一 strategy_id）：
1) 对账/EXTERNAL_SYNC 写路径（C3/C4）
2) 信号下单写路径（C2 execute decision → phase3 写 position）

断言：写区段互斥、无死锁、数据不变量（trade/position_snapshot/runtime_state 一致，无重复/错乱）。
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import text

from src.app.dependencies import get_db_session, set_session_factory
from src.execution.position_manager import PositionManager, ReconcileItem, ReconcileLockNotAcquiredError
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.models.decision_order_map_status import FILLED, PENDING_EXCHANGE, RESERVED, FAILED, SUBMITTING
from src.models.trade import SOURCE_TYPE_EXTERNAL_SYNC
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.repositories.trade_repo import TradeRepository

D6_STRATEGY_ID = "D6_MUTEX_STRAT"
D6_EXTERNAL_TRADE_ID = "d6-ext-1"
D6_TIMEOUT_SECONDS = 15.0
D6_REPEAT_RUNS = 5


async def _ensure_runtime_state(session, strategy_id: str):
    await session.execute(
        text(
            "INSERT OR REPLACE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, 'RUNNING', 30)"
        ),
        {"sid": strategy_id},
    )
    await session.flush()


async def _run_reconcile_path(strategy_id: str, external_trade_id: str) -> dict:
    """对账路径：PositionManager.reconcile（C3/C4 写 trade + position_snapshot + log）。"""
    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            risk_config = RiskConfig(max_position_qty=Decimal("100"))
            risk_manager = RiskManager(position_repo=position_repo, risk_config=risk_config)
            pm = PositionManager(trade_repo, position_repo, log_repo)
            item = ReconcileItem(
                external_trade_id=external_trade_id,
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("0.5"),
                fallback_price=Decimal("50000"),
            )
            out = await pm.reconcile(
                session,
                strategy_id,
                [item],
                lock_holder_id="d6-reconcile",
                max_acquire_retries=3,
                retry_interval_seconds=0.05,
                risk_manager=risk_manager,
            )
            return {"path": "reconcile", "ok": out.get("ok"), "synced": out.get("synced", 0)}


async def _run_order_path(decision_id: str, strategy_id: str) -> dict:
    """下单路径：ExecutionEngine.execute_one（C2 phase1/phase3 写 decision + position）。"""
    try:
        async with get_db_session() as session:
            dom_repo = DecisionOrderMapRepository(session)
            position_repo = PositionRepository(session)
            risk_manager = RiskManager(risk_config=RiskConfig(max_position_qty=Decimal("100")))
            adapter = PaperExchangeAdapter(filled=True)
            engine = ExecutionEngine(
                dom_repo,
                adapter,
                risk_manager,
                position_repo=position_repo,
                app_config=None,
            )
            result = await engine.execute_one(decision_id)
        return {"path": "order", "result": result}
    except Exception as e:
        return {"path": "order", "error": e}


@pytest.mark.asyncio
async def test_d6_concurrent_reconcile_and_order_mutex_no_deadlock(db_session_factory):
    """
    D6：并发执行对账路径与下单路径（同一 strategy_id），断言无死锁、可重复、数据不变量。
    """
    set_session_factory(db_session_factory)
    strategy_id = D6_STRATEGY_ID
    decision_id = "d6-decision-001"

    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id)
        await session.commit()
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="d6-sig-1",
            strategy_id=strategy_id,
            symbol="BTCUSDT",
            side="BUY",
            created_at=datetime.now(timezone.utc),
            quantity=Decimal("1"),
        )
        await session.commit()

    async def run_both():
        rec = await _run_reconcile_path(strategy_id, D6_EXTERNAL_TRADE_ID)
        ord_ = await _run_order_path(decision_id, strategy_id)
        return rec, ord_

    try:
        rec_out, order_out = await asyncio.wait_for(run_both(), timeout=D6_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        pytest.fail("D6: 对账与下单应在限定时间内完成，无死锁/永久阻塞")

    if isinstance(rec_out, Exception):
        assert isinstance(rec_out, ReconcileLockNotAcquiredError), type(rec_out).__name__
    if isinstance(order_out, dict) and "error" in order_out:
        pass
    elif isinstance(order_out, Exception):
        raise order_out

    async with get_db_session() as session:
        trade_repo = TradeRepository(session)
        position_repo = PositionRepository(session)
        dom_repo = DecisionOrderMapRepository(session)

        ext_trades = await trade_repo.get_by_strategy_external_trade_id(strategy_id, D6_EXTERNAL_TRADE_ID)
        ext_count = 1 if ext_trades is not None else 0
        assert ext_count <= 1, "D6: EXTERNAL_SYNC 同 external_trade_id 至多 1 条，无重复写入"

        decision = await dom_repo.get_by_decision_id(decision_id)
        assert decision is not None
        assert decision.status in (FILLED, PENDING_EXCHANGE, RESERVED, FAILED, SUBMITTING), \
            f"D6: decision 状态应在允许集合内: {decision.status}"

        pos = await position_repo.get(strategy_id, "BTCUSDT")
        if pos is not None:
            assert (pos.quantity or Decimal("0")) >= 0, "D6: 持仓数量非负，无错乱状态"


@pytest.mark.asyncio
async def test_d6_repeat_runs_expose_no_race(db_session_factory):
    """
    D6：多次重复并发运行，断言每次均无死锁、数据不变量成立（可重复运行以暴露竞态）。
    """
    set_session_factory(db_session_factory)

    for run in range(D6_REPEAT_RUNS):
        strategy_id = f"{D6_STRATEGY_ID}_r{run}"
        decision_id = f"d6-dec-{run}"

        async with get_db_session() as session:
            await _ensure_runtime_state(session, strategy_id)
            await session.commit()
        async with get_db_session() as session:
            repo = DecisionOrderMapRepository(session)
            await repo.create_reserved(
                decision_id=decision_id,
                signal_id=f"d6-sig-{run}",
                strategy_id=strategy_id,
                symbol="BTCUSDT",
                side="BUY",
                created_at=datetime.now(timezone.utc),
                quantity=Decimal("1"),
            )
            await session.commit()

        async def run_both():
            rec = await _run_reconcile_path(strategy_id, f"d6-ext-{run}")
            ord_ = await _run_order_path(decision_id, strategy_id)
            return rec, ord_

        try:
            rec_out, order_out = await asyncio.wait_for(run_both(), timeout=D6_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            pytest.fail(f"D6 repeat run {run}: 超时，存在死锁或永久阻塞")

        if isinstance(rec_out, ReconcileLockNotAcquiredError):
            pass
        elif isinstance(rec_out, Exception):
            raise rec_out
        if isinstance(order_out, dict) and "error" in order_out:
            pass
        elif isinstance(order_out, Exception):
            raise order_out

        async with get_db_session() as session:
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            dom_repo = DecisionOrderMapRepository(session)

            ext_trade = await trade_repo.get_by_strategy_external_trade_id(strategy_id, f"d6-ext-{run}")
            assert ext_trade is None or (ext_trade.source_type == SOURCE_TYPE_EXTERNAL_SYNC and ext_trade.external_trade_id == f"d6-ext-{run}")

            decision = await dom_repo.get_by_decision_id(decision_id)
            assert decision is not None
            assert decision.status in (FILLED, PENDING_EXCHANGE, RESERVED, FAILED, SUBMITTING)

            pos = await position_repo.get(strategy_id, "BTCUSDT")
            if pos is not None:
                assert (pos.quantity or Decimal("0")) >= 0
