"""
PR17b：Live 极小额风险限制集成测试。
- notional 超限 / 每小时超限 / 每日超限 → ORDER_REJECTED，无 HTTP，审计存在。
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.okx_adapter import OkxExchangeAdapter
from src.execution.okx_client import FakeOkxHttpClient
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.config.app_config import (
    AppConfig,
    DatabaseConfig,
    LoggingConfig,
    WebhookConfig,
    ExecutionConfig,
    RiskSectionConfig,
    ExchangeConfig,
    StrategyEntryConfig,
)
from src.common.reason_codes import (
    LIVE_RISK_NOTIONAL_EXCEEDED,
    LIVE_RISK_HOURLY_LIMIT,
    LIVE_RISK_DAILY_LIMIT,
)


class _LiveAdapter:
    def __init__(self, inner):
        self._inner = inner
    def is_live_endpoint(self):
        return True
    def __getattr__(self, n):
        return getattr(self._inner, n)


@pytest.fixture
def pr17b_db_url(tmp_path):
    return "sqlite+aiosqlite:///" + (tmp_path / "pr17b.db").as_posix()


@pytest.fixture
async def pr17b_session_factory(pr17b_db_url):
    sync_url = pr17b_db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(pr17b_db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await aengine.dispose()


async def _run_live( session_factory, app_config, adapter, decision_id, symbol="BTC-USDT", qty=Decimal("0.01")):
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-1",
            strategy_id="strat-1",
            symbol=symbol,
            side="BUY",
            created_at=now,
            quantity=qty,
        )
        await session.commit()
    async with session_factory() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            adapter,
            RiskManager(),
            config=WorkerConfig.from_app_config(app_config),
            app_config=app_config,
            market_data_adapter=None,
        )
        r = await engine.execute_one(decision_id)
        await session.commit()
        return r


@pytest.mark.asyncio
async def test_pr17b_notional_exceeded_rejects_no_http(pr17b_session_factory, pr17b_db_url, monkeypatch):
    """live_max_order_notional=5，qty*price=10 > 5 → LIVE_RISK_NOTIONAL_EXCEEDED，无 HTTP。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    cfg = AppConfig(
        database=DatabaseConfig(url=pr17b_db_url),
        logging=LoggingConfig(),
        webhook=WebhookConfig(),
        execution=ExecutionConfig(
            dry_run=False,
            live_enabled=True,
            allow_real_trading=True,
            live_allowlist_accounts=["default"],
            live_confirm_token="t",
            live_allowlist_symbols=["BTC-USDT"],
            qty_precision_by_symbol={"BTC-USDT": 8},
            live_max_order_notional=5.0,
            live_last_price_override=1000.0,
        ),
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper"),
        strategies={"strat-1": StrategyEntryConfig(enabled=True)},
    )
    fake = FakeOkxHttpClient()
    adapter = _LiveAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    r = await _run_live(pr17b_session_factory, cfg, adapter, "pr17b-1", qty=Decimal("0.01"))
    assert r.get("status") == "failed"
    assert r.get("reason_code") == LIVE_RISK_NOTIONAL_EXCEEDED
    assert len(fake.post_calls) == 0

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id("pr17b-1")
    assert any(e.reason_code == LIVE_RISK_NOTIONAL_EXCEEDED for e in events)


@pytest.mark.asyncio
async def test_pr17b_hourly_limit_exceeded_rejects_no_http(pr17b_session_factory, pr17b_db_url, monkeypatch):
    """live_max_orders_per_hour=1，先成功 1 笔，第二笔 → LIVE_RISK_HOURLY_LIMIT，无 HTTP。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    cfg = AppConfig(
        database=DatabaseConfig(url=pr17b_db_url),
        logging=LoggingConfig(),
        webhook=WebhookConfig(),
        execution=ExecutionConfig(
            dry_run=False,
            live_enabled=True,
            allow_real_trading=True,
            live_allowlist_accounts=["default"],
            live_confirm_token="t",
            live_allowlist_symbols=["BTC-USDT"],
            qty_precision_by_symbol={"BTC-USDT": 8},
            live_max_orders_per_hour=1,
            live_last_price_override=100.0,
        ),
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper"),
        strategies={"strat-1": StrategyEntryConfig(enabled=True)},
    )
    fake = FakeOkxHttpClient()
    fake.set_default_post({"code": "0", "data": [{"ordId": "o1", "state": "filled"}], "msg": ""})
    adapter = _LiveAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    r1 = await _run_live(pr17b_session_factory, cfg, adapter, "pr17b-2a")
    assert r1.get("status") == "filled"
    assert len(fake.post_calls) >= 1

    fake.reset_calls()
    r2 = await _run_live(pr17b_session_factory, cfg, adapter, "pr17b-2b")
    assert r2.get("status") == "failed"
    assert r2.get("reason_code") == LIVE_RISK_HOURLY_LIMIT
    assert len(fake.post_calls) == 0


@pytest.mark.asyncio
async def test_pr17b_daily_limit_exceeded_rejects_no_http(pr17b_session_factory, pr17b_db_url, monkeypatch):
    """live_max_orders_per_day=2，先成功 2 笔，第三笔 → LIVE_RISK_DAILY_LIMIT，无 HTTP。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    cfg = AppConfig(
        database=DatabaseConfig(url=pr17b_db_url),
        logging=LoggingConfig(),
        webhook=WebhookConfig(),
        execution=ExecutionConfig(
            dry_run=False,
            live_enabled=True,
            allow_real_trading=True,
            live_allowlist_accounts=["default"],
            live_confirm_token="t",
            live_allowlist_symbols=["BTC-USDT"],
            qty_precision_by_symbol={"BTC-USDT": 8},
            live_max_orders_per_day=2,
            live_last_price_override=100.0,
        ),
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper"),
        strategies={"strat-1": StrategyEntryConfig(enabled=True)},
    )
    fake = FakeOkxHttpClient()
    fake.set_default_post({"code": "0", "data": [{"ordId": "o1", "state": "filled"}], "msg": ""})
    adapter = _LiveAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    r1 = await _run_live(pr17b_session_factory, cfg, adapter, "pr17b-3a")
    r2 = await _run_live(pr17b_session_factory, cfg, adapter, "pr17b-3b")
    assert r1.get("status") == "filled"
    assert r2.get("status") == "filled"

    fake.reset_calls()
    r3 = await _run_live(pr17b_session_factory, cfg, adapter, "pr17b-3c")
    assert r3.get("status") == "failed"
    assert r3.get("reason_code") == LIVE_RISK_DAILY_LIMIT
    assert len(fake.post_calls) == 0
