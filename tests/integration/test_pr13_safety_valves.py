"""
PR13 安全阀与账户绑定集成测试：
- Dry-run：全链路走 execution/风控/审计，Adapter 不产生真实 side effect，events 标记 dry_run
- account/exchange 显式绑定：strategy → exchange_profile → account，缺失配置 → 启动 fail-fast
- 断路器：连续失败 → 熔断，熔断期间拒绝下单并审计
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
from src.config.app_config import load_app_config, AppConfig
from src.common.config_errors import ConfigValidationError
from src.common.reason_codes import INVALID_ACCOUNT_CONFIGURATION, CIRCUIT_OPEN
from src.common.event_types import (
    CLAIMED,
    ORDER_SUBMIT_OK,
    FILLED as EV_FILLED,
    CIRCUIT_OPENED,
    CIRCUIT_CLOSED,
)
from src.models.decision_order_map_status import RESERVED
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter, DryRunExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.execution.exceptions import TransientOrderError


@pytest.fixture
def pr13_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def pr13_db_url(pr13_tmp_path):
    return "sqlite+aiosqlite:///" + (pr13_tmp_path / "pr13.db").as_posix()


@pytest.fixture
async def pr13_session_factory(pr13_db_url):
    from sqlalchemy import create_engine
    sync_url = pr13_db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(pr13_db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await aengine.dispose()


def test_pr13_missing_exchange_profile_fail_fast(tmp_path):
    """strategy 配置了 exchange_profile_id 但 exchange_profiles 中不存在 → 启动 fail-fast"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./test.db
execution:
  batch_size: 10
  max_concurrency: 5
strategies:
  S1:
    enabled: true
    exchange_profile_id: nonexistent_profile
    account_id: acc1
exchange_profiles: {}
accounts:
  acc1:
    exchange_profile_id: nonexistent_profile
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == INVALID_ACCOUNT_CONFIGURATION
    assert "exchange_profile_id" in (exc_info.value.message or "") or "not found" in (exc_info.value.message or "").lower()


def test_pr13_missing_account_fail_fast(tmp_path):
    """strategy 配置了 account_id 但 accounts 中不存在 → 启动 fail-fast"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./test.db
execution:
  batch_size: 10
  max_concurrency: 5
strategies:
  S1:
    enabled: true
    exchange_profile_id: paper
    account_id: nonexistent_account
exchange_profiles:
  paper:
    id: paper
    mode: paper
accounts: {}
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == INVALID_ACCOUNT_CONFIGURATION
    assert "account_id" in (exc_info.value.message or "") or "not found" in (exc_info.value.message or "").lower()


@pytest.mark.asyncio
async def test_pr13_dry_run_full_flow_events_marked(pr13_session_factory, tmp_path):
    """Dry-run 模式下 ExecutionEngine 走完整流程，Adapter 不产生真实 side effect，execution_events 标记 dry_run"""
    config_path = tmp_path / "dry_run_config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./dry_run.db
execution:
  batch_size: 10
  max_concurrency: 5
  dry_run: true
strategies:
  strat-1:
    enabled: true
""")
    app_config = load_app_config(str(config_path))
    assert app_config.execution.dry_run is True

    decision_id = "pr13-dry-001"
    now = datetime.now(timezone.utc)
    inner = PaperExchangeAdapter(filled=True)
    adapter = DryRunExchangeAdapter(inner)

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-dry",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        await session.commit()

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, adapter, RiskManager(), app_config=app_config)
        result = await engine.execute_one(decision_id)
        await session.commit()

    assert result.get("status") == "filled"
    assert result.get("exchange_order_id", "").startswith("dry_run_")
    assert len(inner._orders) == 0

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    assert len(events) >= 1
    dry_run_events = [e for e in events if getattr(e, "dry_run", False)]
    assert len(dry_run_events) >= 1
    event_types = [e.event_type for e in events]
    assert CLAIMED in event_types
    assert ORDER_SUBMIT_OK in event_types
    assert EV_FILLED in event_types


@pytest.mark.asyncio
async def test_pr13_circuit_breaker_trip_and_reject(pr13_session_factory, tmp_path):
    """连续失败 → 熔断；熔断期间拒绝下单并审计"""
    from src.execution.exchange_adapter import ExchangeAdapter

    class FailingAdapter(ExchangeAdapter):
        async def create_order(self, symbol, side, qty, client_order_id, **kwargs):
            raise TransientOrderError()
        async def get_order(self, exchange_order_id, symbol):
            from src.execution.exchange_adapter import GetOrderResult
            return GetOrderResult(exchange_order_id=exchange_order_id, status="FILLED", filled_qty=None, avg_price=None, error=None, raw=None)
        async def cancel_order(self, exchange_order_id, **kwargs):
            from src.execution.exchange_adapter import CancelOrderResult
            return CancelOrderResult(success=True)
        async def get_account_info(self):
            from src.adapters.models import AccountInfo
            return AccountInfo(balances={}, equity=None)

    config_path = tmp_path / "circuit_config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./circuit.db
execution:
  batch_size: 10
  max_concurrency: 5
  max_attempts: 1
  circuit_breaker_threshold: 2
  circuit_breaker_open_seconds: 300
strategies:
  strat-1:
    enabled: true
""")
    app_config = load_app_config(str(config_path))

    now = datetime.now(timezone.utc)
    decision_ids = [f"pr13-circuit-{i}" for i in range(4)]

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        for did in decision_ids:
            await dom_repo.create_reserved(
                decision_id=did,
                signal_id="sig-c",
                strategy_id="strat-1",
                symbol="BTCUSDT",
                side="BUY",
                created_at=now,
                quantity=Decimal("0.01"),
            )
        await session.commit()

    worker_config = WorkerConfig.from_app_config(app_config)
    engine = None
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, FailingAdapter(), RiskManager(), config=worker_config, app_config=app_config)
        r1 = await engine.execute_one(decision_ids[0])
        await session.commit()
    assert r1.get("status") == "failed"

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, FailingAdapter(), RiskManager(), config=worker_config, app_config=app_config)
        engine._circuit_failures = 1
        r2 = await engine.execute_one(decision_ids[1])
        await session.commit()
    assert r2.get("status") == "failed"
    assert engine._circuit_opened_at is not None

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events_1 = await event_repo.list_by_decision_id(decision_ids[1])
    assert any(e.event_type == CIRCUIT_OPENED for e in events_1)

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine2 = ExecutionEngine(dom_repo, FailingAdapter(), RiskManager(), config=worker_config, app_config=app_config)
        engine2._circuit_opened_at = engine._circuit_opened_at
        engine2._circuit_failures = 2
        r3 = await engine2.execute_one(decision_ids[2])
        await session.commit()
    assert r3.get("status") == "failed"
    assert r3.get("reason_code") == CIRCUIT_OPEN
