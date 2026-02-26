"""
PR15b 集成测试：OKX Demo 最小下单闭环。
- create_order 成功路径：OKX_HTTP_CREATE_ORDER + ORDER_SUBMIT_OK，无 secret
- PermanentOrderError 路径：OKX_HTTP_CREATE_ORDER + FINAL_FAILED，attempts=1 不重试
- TransientOrderError 重试路径：第一次 5xx → OKX_HTTP_CREATE_ORDER + retry_scheduled；第二次成功 → ORDER_SUBMIT_OK
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest

from src.config.app_config import load_app_config
from src.app.dependencies import get_db_session, set_session_factory
from src.database.connection import Base
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.repositories.rate_limit_repository import RateLimitRepository
from src.repositories.circuit_breaker_repository import CircuitBreakerRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.okx_adapter import OkxExchangeAdapter
from src.execution.okx_client import FakeOkxHttpClient
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.common.event_types import (
    OKX_HTTP_CREATE_ORDER,
    ORDER_SUBMIT_OK,
    ORDER_SUBMIT_FAILED,
    FINAL_FAILED,
    RETRY_SCHEDULED as EV_RETRY_SCHEDULED,
)


@pytest.fixture
def pr15b_db_url(tmp_path):
    return "sqlite+aiosqlite:///" + (tmp_path / "pr15b.db").as_posix()


@pytest.fixture
async def pr15b_session_factory(pr15b_db_url):
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    sync_url = pr15b_db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(pr15b_db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await aengine.dispose()


@pytest.mark.asyncio
async def test_pr15b_create_order_success_okx_http_and_order_submit_ok(pr15b_session_factory, pr15b_db_url, tmp_path):
    """
    PR15b：create_order 成功 → OKX_HTTP_CREATE_ORDER 通信审计 + ORDER_SUBMIT_OK 业务审计；无 secret。
    PR16：Demo（is_live_endpoint=False）不触发 allow_real_trading 等门禁，OKX Demo 可正常下单。
    """
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"""
database:
  url: {pr15b_db_url!r}
execution:
  batch_size: 10
  dry_run: false
strategies:
  strat-1:
    enabled: true
    exchange_profile_id: okx_demo
    account_id: acc1
exchange_profiles:
  okx_demo:
    id: okx_demo
    mode: okx_demo
accounts:
  acc1:
    exchange_profile_id: okx_demo
okx:
  env: demo
  api_key: fake-key
  secret: fake-secret
  passphrase: fake-pass
""")
    app_config = load_app_config(str(config_path))
    worker_config = WorkerConfig.from_app_config(app_config)
    fake_client = FakeOkxHttpClient()
    fake_client.set_post_response(
        "/api/v5/trade/order",
        {"code": "0", "data": [{"ordId": "okx-456", "state": "filled", "accFillSz": "0.01", "avgPx": "50000"}], "msg": ""},
    )
    okx_adapter = OkxExchangeAdapter(
        http_client=fake_client,
        api_key=app_config.okx.api_key,
        secret=app_config.okx.secret,
        passphrase=app_config.okx.passphrase,
    )

    decision_id = "pr15b-success-001"
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-1",
            strategy_id="strat-1",
            symbol="BTC-USDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        await session.commit()

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            okx_adapter,
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        result = await engine.execute_one(decision_id)
        await session.commit()

    assert result.get("status") == "filled"
    assert result.get("exchange_order_id") == "okx-456"
    assert len(fake_client.post_calls) == 1

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    event_types = [e.event_type for e in events]
    assert OKX_HTTP_CREATE_ORDER in event_types
    assert ORDER_SUBMIT_OK in event_types
    okx_ev = next(e for e in events if e.event_type == OKX_HTTP_CREATE_ORDER)
    assert "action=CREATE_ORDER" in (okx_ev.message or "")
    assert "http_status=" in (okx_ev.message or "")
    assert "secret" not in (okx_ev.message or "").lower()
    assert "passphrase" not in (okx_ev.message or "").lower()
    assert "api_key" not in (okx_ev.message or "").lower()


@pytest.mark.asyncio
async def test_pr15b_create_order_permanent_no_retry(pr15b_session_factory, pr15b_db_url, tmp_path):
    """
    PR15b：鉴权失败 PermanentOrderError → OKX_HTTP_CREATE_ORDER + FINAL_FAILED，attempt_count=1 不重试。
    """
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"""
database:
  url: {pr15b_db_url!r}
execution:
  batch_size: 10
  dry_run: false
strategies:
  strat-1:
    enabled: true
    exchange_profile_id: okx_demo
    account_id: acc1
exchange_profiles:
  okx_demo:
    id: okx_demo
    mode: okx_demo
accounts:
  acc1:
    exchange_profile_id: okx_demo
okx:
  env: demo
  api_key: fake-key
  secret: fake-secret
  passphrase: fake-pass
""")
    app_config = load_app_config(str(config_path))
    worker_config = WorkerConfig.from_app_config(app_config)
    fake_client = FakeOkxHttpClient()
    fake_client.set_post_response("/api/v5/trade/order", {"code": "50111", "msg": "Invalid API key", "data": []})
    okx_adapter = OkxExchangeAdapter(
        http_client=fake_client,
        api_key=app_config.okx.api_key,
        secret=app_config.okx.secret,
        passphrase=app_config.okx.passphrase,
    )

    decision_id = "pr15b-perm-001"
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-2",
            strategy_id="strat-1",
            symbol="BTC-USDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        await session.commit()

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            okx_adapter,
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        result = await engine.execute_one(decision_id)
        await session.commit()

    assert result.get("status") == "failed"
    assert result.get("reason_code") == "ORDER_REJECTED"
    assert result.get("attempt_count") == 1
    assert len(fake_client.post_calls) == 1

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    event_types = [e.event_type for e in events]
    assert OKX_HTTP_CREATE_ORDER in event_types
    assert FINAL_FAILED in event_types
    failed_ev = next(e for e in events if e.event_type == FINAL_FAILED)
    assert failed_ev.attempt_count == 1


@pytest.mark.asyncio
async def test_pr15b_create_order_transient_then_success(pr15b_session_factory, pr15b_db_url, tmp_path):
    """
    PR15b：第一次 5xx Transient → OKX_HTTP_CREATE_ORDER + retry_scheduled；第二次成功 → ORDER_SUBMIT_OK。
    backoff=0 使第二次 execute_one 可立即 claim。
    """
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"""
database:
  url: {pr15b_db_url!r}
execution:
  batch_size: 10
  dry_run: false
  max_attempts: 3
  backoff_seconds: [0, 0, 0]
strategies:
  strat-1:
    enabled: true
    exchange_profile_id: okx_demo
    account_id: acc1
exchange_profiles:
  okx_demo:
    id: okx_demo
    mode: okx_demo
accounts:
  acc1:
    exchange_profile_id: okx_demo
okx:
  env: demo
  api_key: fake-key
  secret: fake-secret
  passphrase: fake-pass
""")
    app_config = load_app_config(str(config_path))
    worker_config = WorkerConfig.from_app_config(app_config)
    fake_client = FakeOkxHttpClient()
    fake_client.set_post_response("/api/v5/trade/order", {"code": "50000", "msg": "Internal error", "data": []})
    okx_adapter = OkxExchangeAdapter(
        http_client=fake_client,
        api_key=app_config.okx.api_key,
        secret=app_config.okx.secret,
        passphrase=app_config.okx.passphrase,
    )

    decision_id = "pr15b-retry-001"
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-3",
            strategy_id="strat-1",
            symbol="BTC-USDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        await session.commit()

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            okx_adapter,
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        result1 = await engine.execute_one(decision_id)
        await session.commit()

    assert result1.get("status") == "retry_scheduled"
    assert result1.get("reason_code") == "RETRY_SCHEDULED"
    assert len(fake_client.post_calls) == 1

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events1 = await event_repo.list_by_decision_id(decision_id)
    assert OKX_HTTP_CREATE_ORDER in [e.event_type for e in events1]
    assert EV_RETRY_SCHEDULED in [e.event_type for e in events1]

    fake_client.set_post_response(
        "/api/v5/trade/order",
        {"code": "0", "data": [{"ordId": "okx-789", "state": "filled", "accFillSz": "0.01", "avgPx": "50000"}], "msg": ""},
    )

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            okx_adapter,
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        result2 = await engine.execute_one(decision_id)
        await session.commit()

    assert result2.get("status") == "filled"
    assert result2.get("exchange_order_id") == "okx-789"
    assert len(fake_client.post_calls) == 2

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events2 = await event_repo.list_by_decision_id(decision_id)
    okx_events = [e for e in events2 if e.event_type == OKX_HTTP_CREATE_ORDER]
    assert len(okx_events) >= 2
    assert ORDER_SUBMIT_OK in [e.event_type for e in events2]
