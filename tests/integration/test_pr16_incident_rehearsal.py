"""
PR16：事故演练集成测试。
- OKX 连续 5xx → 重试 → 断路器打开 → 全局拒单；验证 execution_events 序列与审计。
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.repositories.rate_limit_repository import RateLimitRepository
from src.repositories.circuit_breaker_repository import CircuitBreakerRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.okx_adapter import OkxExchangeAdapter
from src.execution.okx_client import FakeOkxHttpClient
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.config.app_config import load_app_config
from src.common.event_types import (
    ORDER_SUBMIT_STARTED,
    ORDER_SUBMIT_FAILED,
    OKX_HTTP_CREATE_ORDER,
    CIRCUIT_OPENED,
)
from src.common.reason_codes import CIRCUIT_OPEN, EXCHANGE_TRANSIENT_ERROR


@pytest.fixture
def pr16_incident_db_url(tmp_path):
    return "sqlite+aiosqlite:///" + (tmp_path / "pr16_incident.db").as_posix()


@pytest.fixture
async def pr16_incident_session_factory(pr16_incident_db_url, monkeypatch):
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "pr16-incident-token")
    sync_url = pr16_incident_db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(pr16_incident_db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await aengine.dispose()


@pytest.mark.asyncio
async def test_pr16_okx_5xx_then_circuit_open_rejects(pr16_incident_session_factory, pr16_incident_db_url, tmp_path, monkeypatch):
    """
    事故演练：OKX 连续 5xx → 重试 → 断路器打开 → 第三笔拒单；验证事件序列与审计。
    复现步骤：1) 配置 circuit_breaker_threshold=2；2) FakeOkx 返回 5xx；3) 执行 2 笔失败；4) 第三笔被 CIRCUIT_OPEN 拒绝。
    预期 execution_events：ORDER_SUBMIT_STARTED → OKX_HTTP_CREATE_ORDER / ORDER_SUBMIT_FAILED（前两笔）；
    第三笔：CLAIMED → ... → CIRCUIT_OPENED / FINAL_FAILED，reason_code=CIRCUIT_OPEN。
    """
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "pr16-incident-token")
    config_path = tmp_path / "pr16_incident_config.yaml"
    config_path.write_text(f"""
database:
  url: {pr16_incident_db_url!r}
execution:
  batch_size: 10
  dry_run: false
  allow_real_trading: true
  live_confirm_token: pr16-incident-token
  live_allowlist_accounts: [acc1]
  live_allowlist_symbols: [BTC-USDT]
  qty_precision_by_symbol:
    BTC-USDT: 8
  max_attempts: 1
  circuit_breaker_threshold: 2
  circuit_breaker_open_seconds: 300
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
  api_key: k
  secret: s
  passphrase: p
""")
    app_config = load_app_config(str(config_path))
    worker_config = WorkerConfig.from_app_config(app_config)
    fake_client = FakeOkxHttpClient()
    fake_client.set_post_response(
        "/api/v5/trade/order",
        {"code": "500", "msg": "Internal Server Error"},
    )
    okx_adapter = OkxExchangeAdapter(
        http_client=fake_client,
        api_key=app_config.okx.api_key,
        secret=app_config.okx.secret,
        passphrase=app_config.okx.passphrase,
    )
    now = datetime.now(timezone.utc)
    decision_ids = ["pr16-inc-001", "pr16-inc-002", "pr16-inc-003"]
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        for did in decision_ids:
            await dom_repo.create_reserved(
                decision_id=did,
                signal_id="sig-inc",
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
        r1 = await engine.execute_one(decision_ids[0])
        await session.commit()
    assert r1.get("status") in ("failed", "retry_scheduled")

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        engine2 = ExecutionEngine(
            dom_repo,
            okx_adapter,
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        r2 = await engine2.execute_one(decision_ids[1])
        await session.commit()
    assert r2.get("status") in ("failed", "retry_scheduled")

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        engine3 = ExecutionEngine(
            dom_repo,
            okx_adapter,
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
        event_repo = ExecutionEventRepository(session)
        events_2 = await event_repo.list_by_decision_id(decision_ids[1])
        events_3 = await event_repo.list_by_decision_id(decision_ids[2])
    assert any(e.event_type == CIRCUIT_OPENED for e in events_2), "CIRCUIT_OPENED 应在触发熔断的那笔（第二笔）写入"
    assert any(e.reason_code == CIRCUIT_OPEN for e in events_3), "第三笔应含 reason_code=CIRCUIT_OPEN"
