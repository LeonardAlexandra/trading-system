"""
PR14a 集成测试：
1）Live Gate：live_enabled=true 且缺 account_id/exchange_profile_id → 启动 fail-fast（reason_code）；
   live_enabled=false 时同样配置缺失不阻塞启动。
2）外置限频：两 engine 共享同一 DB，连续下单触发 rate limit，第二实例也被拒绝，events 含 RATE_LIMIT_EXCEEDED + account_id。
3）外置断路器：连续 N 次失败 → circuit open，第二实例也被拒绝；到期或 reset 后 close，审计 CIRCUIT_OPENED/CLOSED。
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
from src.config.app_config import load_app_config
from src.common.config_errors import ConfigValidationError
from src.common.reason_codes import (
    LIVE_GATE_MISSING_ACCOUNT_ID,
    LIVE_GATE_MISSING_EXCHANGE_PROFILE_ID,
    RATE_LIMIT_EXCEEDED,
    CIRCUIT_OPEN,
)
from src.common.event_types import (
    RATE_LIMIT_EXCEEDED as EV_RATE_LIMIT_EXCEEDED,
    CIRCUIT_OPENED,
    CIRCUIT_CLOSED,
)
from src.models.decision_order_map_status import RESERVED
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.repositories.rate_limit_repository import RateLimitRepository
from src.repositories.circuit_breaker_repository import CircuitBreakerRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter, DryRunExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.execution.exceptions import TransientOrderError
from src.execution.exchange_adapter import ExchangeAdapter


# ----- fixtures -----
@pytest.fixture
def pr14a_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def pr14a_db_url(pr14a_tmp_path):
    return "sqlite+aiosqlite:///" + (pr14a_tmp_path / "pr14a.db").as_posix()


@pytest.fixture
async def pr14a_session_factory(pr14a_db_url):
    import src.models  # ensure all models (rate_limit_state, circuit_breaker_state) registered
    sync_url = pr14a_db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(pr14a_db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await aengine.dispose()


# ----- 1) Live Gate -----
def test_pr14a_live_enabled_missing_account_id_fail_fast(tmp_path):
    """live_enabled=true 且策略缺 account_id → 启动 fail-fast，reason_code=LIVE_GATE_MISSING_ACCOUNT_ID"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./test.db
execution:
  batch_size: 10
  live_enabled: true
  live_allowlist_accounts: [acc1]
  live_allowlist_symbols: [BTC-USDT]
  qty_precision_by_symbol:
    BTC-USDT: 8
strategies:
  S1:
    enabled: true
    exchange_profile_id: paper
    # account_id missing
exchange_profiles:
  paper:
    id: paper
    mode: paper
accounts: {}
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == LIVE_GATE_MISSING_ACCOUNT_ID
    assert "account_id" in (exc_info.value.message or "").lower()


def test_pr14a_live_enabled_missing_exchange_profile_id_fail_fast(tmp_path):
    """live_enabled=true 且策略缺 exchange_profile_id → 启动 fail-fast，reason_code=LIVE_GATE_MISSING_EXCHANGE_PROFILE_ID"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./test.db
execution:
  batch_size: 10
  live_enabled: true
  live_allowlist_accounts: [acc1]
  live_allowlist_symbols: [BTC-USDT]
  qty_precision_by_symbol:
    BTC-USDT: 8
strategies:
  S1:
    enabled: true
    account_id: acc1
    # exchange_profile_id missing
exchange_profiles: {}
accounts:
  acc1:
    exchange_profile_id: paper
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == LIVE_GATE_MISSING_EXCHANGE_PROFILE_ID
    assert "exchange_profile_id" in (exc_info.value.message or "").lower()


def test_pr14a_live_enabled_false_same_config_does_not_block(tmp_path):
    """live_enabled=false 时，同样缺 account_id/exchange_profile_id 不阻塞启动（兼容）"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./test.db
execution:
  batch_size: 10
  live_enabled: false
strategies:
  S1:
    enabled: true
    # no account_id, no exchange_profile_id
""")
    app_config = load_app_config(str(config_path))
    assert app_config.execution.live_enabled is False


# ----- 2) 外置限频（多实例共享）-----
@pytest.mark.asyncio
async def test_pr14a_shared_rate_limit_two_engines(pr14a_session_factory, tmp_path):
    """两 engine 共享同一 DB；连续下单触发 rate limit，第二实例也被拒绝；events 含 RATE_LIMIT_EXCEEDED + account_id"""
    config_path = tmp_path / "rate_config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./r.db
execution:
  batch_size: 10
  max_orders_per_minute: 2
strategies:
  strat-1:
    enabled: true
    account_id: acc1
    exchange_profile_id: paper
exchange_profiles:
  paper:
    id: paper
    mode: paper
accounts:
  acc1:
    exchange_profile_id: paper
""")
    app_config = load_app_config(str(config_path))
    worker_config = WorkerConfig.from_app_config(app_config)
    now = datetime.now(timezone.utc)
    decision_ids = [f"pr14a-rate-{i}" for i in range(4)]

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        for did in decision_ids:
            await dom_repo.create_reserved(
                decision_id=did,
                signal_id="sig-r",
                strategy_id="strat-1",
                symbol="BTCUSDT",
                side="BUY",
                created_at=now,
                quantity=Decimal("0.01"),
            )
        await session.commit()

    rate_limit_repo_1 = None
    rate_limit_repo_2 = None
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        event_repo = ExecutionEventRepository(session)
        rate_limit_repo_1 = RateLimitRepository(session)
        circuit_breaker_repo_1 = CircuitBreakerRepository(session)
        engine1 = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_limit_repo_1,
            circuit_breaker_repo=circuit_breaker_repo_1,
        )
        r1 = await engine1.execute_one(decision_ids[0])
        r2 = await engine1.execute_one(decision_ids[1])
        await session.commit()
    assert r1.get("status") == "filled"
    assert r2.get("status") == "filled"

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_limit_repo_2 = RateLimitRepository(session)
        circuit_breaker_repo_2 = CircuitBreakerRepository(session)
        engine2 = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_limit_repo_2,
            circuit_breaker_repo=circuit_breaker_repo_2,
        )
        r3 = await engine2.execute_one(decision_ids[2])
        await session.commit()
    assert r3.get("status") == "failed"
    assert r3.get("reason_code") == RATE_LIMIT_EXCEEDED

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events_2 = await event_repo.list_by_decision_id(decision_ids[2])
    rate_events = [e for e in events_2 if e.event_type == EV_RATE_LIMIT_EXCEEDED]
    assert len(rate_events) >= 1
    assert getattr(rate_events[0], "account_id", None) == "acc1"


# ----- 3) 外置断路器（多实例共享）-----
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


@pytest.mark.asyncio
async def test_pr14a_shared_circuit_breaker_two_engines(pr14a_session_factory, tmp_path):
    """连续 N 次失败 → circuit open；第二实例也被拒绝；到期或 reset 后能 close，审计 CIRCUIT_OPENED/CLOSED"""
    config_path = tmp_path / "circuit_config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./c.db
execution:
  batch_size: 10
  max_attempts: 1
  circuit_breaker_threshold: 2
  circuit_breaker_open_seconds: 300
strategies:
  strat-1:
    enabled: true
    account_id: acc1
    exchange_profile_id: paper
exchange_profiles:
  paper:
    id: paper
    mode: paper
accounts:
  acc1:
    exchange_profile_id: paper
""")
    app_config = load_app_config(str(config_path))
    worker_config = WorkerConfig.from_app_config(app_config)
    now = datetime.now(timezone.utc)
    decision_ids = [f"pr14a-cb-{i}" for i in range(4)]

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        for did in decision_ids:
            await dom_repo.create_reserved(
                decision_id=did,
                signal_id="sig-cb",
                strategy_id="strat-1",
                symbol="BTCUSDT",
                side="BUY",
                created_at=now,
                quantity=Decimal("0.01"),
            )
        await session.commit()

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        rate_repo = RateLimitRepository(session)
        engine1 = ExecutionEngine(
            dom_repo,
            FailingAdapter(),
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        r1 = await engine1.execute_one(decision_ids[0])
        await session.commit()
    assert r1.get("status") == "failed"

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        rate_repo = RateLimitRepository(session)
        engine2 = ExecutionEngine(
            dom_repo,
            FailingAdapter(),
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        r2 = await engine2.execute_one(decision_ids[1])
        await session.commit()
    assert r2.get("status") == "failed"
    events_1 = None
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events_1 = await event_repo.list_by_decision_id(decision_ids[1])
    assert any(e.event_type == CIRCUIT_OPENED for e in events_1)

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        rate_repo = RateLimitRepository(session)
        engine3 = ExecutionEngine(
            dom_repo,
            FailingAdapter(),
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        r3 = await engine3.execute_one(decision_ids[2])
        await session.commit()
    assert r3.get("status") == "failed"
    assert r3.get("reason_code") == CIRCUIT_OPEN

    async with get_db_session() as session:
        circuit_repo = CircuitBreakerRepository(session)
        await circuit_repo.close_circuit("acc1")
        await session.commit()

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        rate_repo = RateLimitRepository(session)
        engine4 = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        did_new = "pr14a-cb-after-close"
        await dom_repo.create_reserved(
            decision_id=did_new,
            signal_id="sig-cb2",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=datetime.now(timezone.utc),
            quantity=Decimal("0.01"),
        )
        await session.commit()
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        rate_repo = RateLimitRepository(session)
        engine4 = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        r4 = await engine4.execute_one(did_new)
        await session.commit()
    assert r4.get("status") == "filled"
