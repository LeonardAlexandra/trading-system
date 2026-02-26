"""
Phase1.2 C6：对账状态监控验收测试

1) get_status 基本返回：至少 2 条 position_snapshot，每条含 strategy_id, symbol, reconcile_status, last_reconcile_at
2) strategy_id 过滤：get_status(strategy_id="X") 只返回该策略
3) 对账失败触发写 log：RECONCILE_FAILED 时写入 event_type=reconcile_status_alert 的日志（不依赖 AlertSystem.evaluate_rules）
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401
from src.models.position_reconcile_log import RECONCILE_END, RECONCILE_FAILED, RECONCILE_START
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.repositories.log_repository import LogRepository
from src.monitoring.position_consistency_monitor import (
    PositionConsistencyMonitor,
    ConsistencyStatus,
    RECONCILE_STATUS_OK,
    RECONCILE_STATUS_WARNING,
    RECONCILE_STATUS_CRITICAL,
)
from src.monitoring.alert_system import AlertSystem
from src.monitoring.system_monitor import SystemMonitor
from src.monitoring.health_checker import HealthChecker
from src.execution.exchange_adapter import PaperExchangeAdapter


@pytest.fixture
def c6_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def c6_db_url(c6_tmp_path):
    return "sqlite+aiosqlite:///" + (c6_tmp_path / "c6_consistency.db").as_posix()


@pytest.fixture
def c6_sync_db_url(c6_tmp_path):
    return "sqlite:///" + (c6_tmp_path / "c6_consistency.db").as_posix()


@pytest.fixture
def c6_schema(c6_sync_db_url):
    engine = create_engine(c6_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def c6_session_factory(c6_db_url, c6_schema):
    engine = create_async_engine(c6_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


# ---------- 1) get_status 基本返回 ----------
@pytest.mark.asyncio
async def test_get_status_returns_required_fields(c6_session_factory):
    """插入至少 2 条 position（不同 strategy/symbol），get_status() 返回 list，每条含 strategy_id, symbol, reconcile_status, last_reconcile_at。"""
    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        await pos_repo.upsert("strat_c6_a", "BTCUSDT", Decimal("0.01"))
        await pos_repo.upsert("strat_c6_b", "ETHUSDT", Decimal("0.1"))

    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        rec_repo = PositionReconcileLogRepository(session)
        log_repo = LogRepository(session)
        alert_system = AlertSystem([])
        monitor = SystemMonitor()
        checker = HealthChecker()
        exchange = PaperExchangeAdapter(filled=True)
        monitor_c6 = PositionConsistencyMonitor(
            pos_repo, rec_repo, alert_system, monitor, checker, log_repo, exchange
        )
        statuses = await monitor_c6.get_status(session)

    assert isinstance(statuses, list)
    assert len(statuses) >= 2
    for s in statuses:
        assert isinstance(s, ConsistencyStatus)
        assert hasattr(s, "strategy_id") and s.strategy_id
        assert hasattr(s, "symbol") and s.symbol
        assert hasattr(s, "reconcile_status") and s.reconcile_status in (RECONCILE_STATUS_OK, RECONCILE_STATUS_WARNING, RECONCILE_STATUS_CRITICAL)
        assert hasattr(s, "last_reconcile_at")


# ---------- 2) strategy_id 过滤 ----------
@pytest.mark.asyncio
async def test_get_status_filter_by_strategy_id(c6_session_factory):
    """get_status(strategy_id="X") 只返回该策略相关记录。"""
    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        await pos_repo.upsert("only_this_strategy", "BTCUSDT", Decimal("0"))
        await pos_repo.upsert("other_strategy", "ETHUSDT", Decimal("0"))

    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        rec_repo = PositionReconcileLogRepository(session)
        log_repo = LogRepository(session)
        alert_system = AlertSystem([])
        monitor = SystemMonitor()
        checker = HealthChecker()
        exchange = PaperExchangeAdapter(filled=True)
        monitor_c6 = PositionConsistencyMonitor(
            pos_repo, rec_repo, alert_system, monitor, checker, log_repo, exchange
        )
        statuses = await monitor_c6.get_status(session, strategy_id="only_this_strategy")

    assert len(statuses) == 1
    assert statuses[0].strategy_id == "only_this_strategy"
    assert statuses[0].symbol == "BTCUSDT"


# ---------- 3) 对账失败触发写 log（reconcile_status_alert） ----------
@pytest.mark.asyncio
async def test_reconcile_failed_writes_reconcile_status_alert_log(c6_session_factory):
    """构造 position_reconcile_log 最新为 RECONCILE_FAILED -> reconcile_status=CRITICAL；调用 get_status 后断言写入了 event_type=reconcile_status_alert 的日志（不调用 AlertSystem.evaluate_rules）。"""
    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        await pos_repo.upsert("strat_alert", "BTCUSDT", Decimal("0"))

    async with get_db_session() as session:
        rec_repo = PositionReconcileLogRepository(session)
        async with session.begin():
            await rec_repo.log_event_in_txn("strat_alert", RECONCILE_FAILED)

    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        rec_repo = PositionReconcileLogRepository(session)
        log_repo = LogRepository(session)
        alert_system = AlertSystem([])
        monitor = SystemMonitor()
        checker = HealthChecker()
        exchange = PaperExchangeAdapter(filled=True)
        monitor_c6 = PositionConsistencyMonitor(
            pos_repo, rec_repo, alert_system, monitor, checker, log_repo, exchange
        )
        statuses = await monitor_c6.get_status(session)

    assert any(s.reconcile_status == RECONCILE_STATUS_CRITICAL for s in statuses)

    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows = await log_repo.query(limit=20)
    assert any(
        r.event_type == "reconcile_status_alert" for r in rows
    ), "log 中应有 event_type=reconcile_status_alert"
    alert_row = next(r for r in rows if r.event_type == "reconcile_status_alert")
    assert alert_row.level == "ERROR"


@pytest.mark.asyncio
async def test_reconcile_start_yields_warning_status(c6_session_factory):
    """最新 event_type=RECONCILE_START 时 reconcile_status=WARNING。"""
    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        await pos_repo.upsert("strat_warn", "ETHUSDT", Decimal("0"))

    async with get_db_session() as session:
        rec_repo = PositionReconcileLogRepository(session)
        async with session.begin():
            await rec_repo.log_event_in_txn("strat_warn", RECONCILE_START)

    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        rec_repo = PositionReconcileLogRepository(session)
        log_repo = LogRepository(session)
        alert_system = AlertSystem([])
        monitor = SystemMonitor()
        checker = HealthChecker()
        exchange = PaperExchangeAdapter(filled=True)
        monitor_c6 = PositionConsistencyMonitor(
            pos_repo, rec_repo, alert_system, monitor, checker, log_repo, exchange
        )
        statuses = await monitor_c6.get_status(session, strategy_id="strat_warn")

    assert len(statuses) == 1
    assert statuses[0].reconcile_status == RECONCILE_STATUS_WARNING


@pytest.mark.asyncio
async def test_reconcile_end_yields_ok_status(c6_session_factory):
    """最新 event_type=RECONCILE_END 时 reconcile_status=OK。"""
    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        await pos_repo.upsert("strat_ok", "BTCUSDT", Decimal("0"))

    async with get_db_session() as session:
        rec_repo = PositionReconcileLogRepository(session)
        async with session.begin():
            await rec_repo.log_event_in_txn("strat_ok", RECONCILE_END)

    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        rec_repo = PositionReconcileLogRepository(session)
        log_repo = LogRepository(session)
        alert_system = AlertSystem([])
        monitor = SystemMonitor()
        checker = HealthChecker()
        exchange = PaperExchangeAdapter(filled=True)
        monitor_c6 = PositionConsistencyMonitor(
            pos_repo, rec_repo, alert_system, monitor, checker, log_repo, exchange
        )
        statuses = await monitor_c6.get_status(session, strategy_id="strat_ok")

    assert len(statuses) == 1
    assert statuses[0].reconcile_status == RECONCILE_STATUS_OK
