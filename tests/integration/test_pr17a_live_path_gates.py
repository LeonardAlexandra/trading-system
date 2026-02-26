"""
PR17a：Live 路径门禁矩阵集成测试。
- 每个门禁缺失都能触发拒绝，并有 distinct reason_code。
- 全部满足时：仍拒绝 live create_order（PR17a stage 禁用），且 post_calls_to_live_endpoint=0。
- 默认离线，使用 FakeOkxHttpClient。
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
from src.common.event_types import ORDER_REJECTED as EV_ORDER_REJECTED
from src.common.reason_codes import (
    LIVE_GATE_ALLOW_REAL_TRADING_OFF,
    LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED,
    LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED,
    LIVE_GATE_ACCOUNT_NOT_ALLOWED,
    LIVE_GATE_SYMBOL_NOT_ALLOWED,
    LIVE_GATE_CONFIRM_TOKEN_MISMATCH,
)


class _LiveEndpointAdapter:
    """测试用：包装适配器并声明 is_live_endpoint=True。"""
    def __init__(self, inner):
        self._inner = inner

    def is_live_endpoint(self):
        return True

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _base_config(db_url, **overrides):
    # strategy 无 account_id 时 resolve 返回 default，故 allowlist 需含 default 才能通过 account 门禁
    # PR17b：live_enabled=True 门禁全过才允许 create_order
    ex = ExecutionConfig(
        dry_run=False,
        live_enabled=overrides.get("live_enabled", True),
        allow_real_trading=overrides.get("allow_real_trading", True),
        live_allowlist_accounts=overrides.get("live_allowlist_accounts", ["default"]),
        live_confirm_token=overrides.get("live_confirm_token", "t"),
        live_allowlist_symbols=overrides.get("live_allowlist_symbols", ["BTC-USDT"]),
        qty_precision_by_symbol=overrides.get("qty_precision_by_symbol", {"BTC-USDT": 8}),
    )
    return AppConfig(
        database=DatabaseConfig(url=db_url),
        logging=LoggingConfig(),
        webhook=WebhookConfig(),
        execution=ex,
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper"),
        strategies={"strat-1": StrategyEntryConfig(enabled=True)},
    )


@pytest.fixture
def pr17a_db_url(tmp_path):
    return "sqlite+aiosqlite:///" + (tmp_path / "pr17a.db").as_posix()


@pytest.fixture
async def pr17a_session_factory(pr17a_db_url):
    sync_url = pr17a_db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(pr17a_db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await aengine.dispose()


async def _run_live_path_decision(session_factory, app_config, adapter, decision_id, symbol="BTC-USDT", account_id="acc1"):
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
            quantity=Decimal("0.01"),
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
        )
        result = await engine.execute_one(decision_id)
        await session.commit()
        return result


@pytest.mark.asyncio
async def test_pr17a_allow_real_trading_off_rejects(pr17a_session_factory, pr17a_db_url, monkeypatch):
    """allow_real_trading=False → LIVE_GATE_ALLOW_REAL_TRADING_OFF，无 HTTP。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    cfg = _base_config(pr17a_db_url, live_enabled=True, allow_real_trading=False)
    fake = FakeOkxHttpClient()
    adapter = _LiveEndpointAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    r = await _run_live_path_decision(pr17a_session_factory, cfg, adapter, "pr17a-001")
    assert r.get("status") == "failed"
    assert r.get("reason_code") == LIVE_GATE_ALLOW_REAL_TRADING_OFF
    assert len(fake.post_calls) == 0


@pytest.mark.asyncio
async def test_pr17a_allowlist_symbols_empty_rejects(pr17a_session_factory, pr17a_db_url, monkeypatch):
    """live_allowlist_symbols 为空 → LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED，无 HTTP。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    cfg = _base_config(pr17a_db_url, live_allowlist_symbols=[])
    fake = FakeOkxHttpClient()
    adapter = _LiveEndpointAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    r = await _run_live_path_decision(pr17a_session_factory, cfg, adapter, "pr17a-002")
    assert r.get("status") == "failed"
    assert r.get("reason_code") == LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED
    assert len(fake.post_calls) == 0


@pytest.mark.asyncio
async def test_pr17a_symbol_not_in_allowlist_rejects(pr17a_session_factory, pr17a_db_url, monkeypatch):
    """symbol 不在 live_allowlist_symbols → LIVE_GATE_SYMBOL_NOT_ALLOWED，无 HTTP。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    cfg = _base_config(pr17a_db_url, live_allowlist_symbols=["ETH-USDT"], qty_precision_by_symbol={"ETH-USDT": 8})
    fake = FakeOkxHttpClient()
    adapter = _LiveEndpointAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    r = await _run_live_path_decision(pr17a_session_factory, cfg, adapter, "pr17a-003", symbol="BTC-USDT")
    assert r.get("status") == "failed"
    assert r.get("reason_code") == LIVE_GATE_SYMBOL_NOT_ALLOWED
    assert len(fake.post_calls) == 0


@pytest.mark.asyncio
async def test_pr17a_account_not_in_allowlist_rejects(pr17a_session_factory, pr17a_db_url, monkeypatch):
    """account_id 不在 live_allowlist_accounts → LIVE_GATE_ACCOUNT_NOT_ALLOWED。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    # allowlist 只有 acc-other；strategy 无 account_id 时 resolve 返回 default，default 不在列表
    cfg = _base_config(pr17a_db_url, live_allowlist_accounts=["acc-other"])
    fake = FakeOkxHttpClient()
    adapter = _LiveEndpointAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    r = await _run_live_path_decision(pr17a_session_factory, cfg, adapter, "pr17a-004")
    assert r.get("status") == "failed"
    assert r.get("reason_code") == LIVE_GATE_ACCOUNT_NOT_ALLOWED
    assert len(fake.post_calls) == 0


@pytest.mark.asyncio
async def test_pr17a_confirm_token_mismatch_rejects(pr17a_session_factory, pr17a_db_url, monkeypatch):
    """live_confirm_token 与 env 均有值但不一致 → LIVE_GATE_CONFIRM_TOKEN_MISMATCH，无 HTTP。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "env-token")
    cfg = _base_config(pr17a_db_url, live_confirm_token="wrong-token")
    fake = FakeOkxHttpClient()
    adapter = _LiveEndpointAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    r = await _run_live_path_decision(pr17a_session_factory, cfg, adapter, "pr17a-005")
    assert r.get("status") == "failed"
    assert r.get("reason_code") == LIVE_GATE_CONFIRM_TOKEN_MISMATCH
    assert len(fake.post_calls) == 0


@pytest.mark.asyncio
async def test_pr17b_all_gates_pass_allows_create_order(pr17a_session_factory, pr17a_db_url, monkeypatch):
    """PR17b：门禁全过（含 live_enabled）则允许 live create_order，post_calls>=1。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    cfg = _base_config(pr17a_db_url)
    fake = FakeOkxHttpClient()
    fake.set_default_post({"code": "0", "data": [{"ordId": "ord-1", "state": "filled"}], "msg": ""})
    adapter = _LiveEndpointAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    r = await _run_live_path_decision(pr17a_session_factory, cfg, adapter, "pr17b-006")
    assert r.get("status") in ("filled", "success", "ok")
    assert len(fake.post_calls) >= 1

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id("pr17b-006")
    okx_events = [e for e in events if "OKX_HTTP" in (e.event_type or "")]
    assert len(okx_events) >= 1
