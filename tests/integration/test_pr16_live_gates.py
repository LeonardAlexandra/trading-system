"""
PR16：多重 Live 门禁集成测试。
- 门禁仅当 is_live_endpoint=True 时触发；Demo（OKX Demo HTTP）不触发，demo rehearsal 可正常下单。
- 当 is_live_endpoint=True（模拟）且 allow_real_trading=False → 拒绝，写 ORDER_REJECTED。
- 当 is_live_endpoint=True 且 PR16 仍不允许实盘 → LIVE_GATE_REAL_LIVE_FORBIDDEN。
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
from src.execution.execution_engine import ExecutionEngine
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
from src.common.reason_codes import LIVE_GATE_ALLOW_REAL_TRADING_OFF


def _app_config(allow_real_trading=False, live_allowlist_accounts=None, live_confirm_token="", db_url=None, live_allowlist_symbols=None):
    return AppConfig(
        database=DatabaseConfig(url=db_url or "sqlite+aiosqlite:///./pr16_gate.db"),
        logging=LoggingConfig(),
        webhook=WebhookConfig(),
        execution=ExecutionConfig(
            dry_run=False,
            live_enabled=True,
            allow_real_trading=allow_real_trading,
            live_allowlist_accounts=live_allowlist_accounts or [],
            live_confirm_token=live_confirm_token,
            live_allowlist_symbols=live_allowlist_symbols or ["BTCUSDT"],
            qty_precision_by_symbol={"BTCUSDT": 8},
        ),
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper"),
        strategies={"strat-1": StrategyEntryConfig(enabled=True)},
    )


@pytest.fixture
def pr16_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def pr16_db_url(pr16_tmp_path):
    return "sqlite+aiosqlite:///" + (pr16_tmp_path / "pr16_gate.db").as_posix()


@pytest.fixture
def pr16_sync_url(pr16_tmp_path):
    return "sqlite:///" + (pr16_tmp_path / "pr16_gate.db").as_posix()


@pytest.fixture
def pr16_schema(pr16_sync_url):
    engine = create_engine(pr16_sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def pr16_session_factory(pr16_db_url, pr16_schema):
    engine = create_async_engine(pr16_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


class _LiveEndpointAdapter:
    """测试用：包装任意适配器并声明 is_live_endpoint=True，用于验证仅 live endpoint 触发门禁。"""
    def __init__(self, inner):
        self._inner = inner

    def is_live_endpoint(self):
        return True

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.mark.asyncio
async def test_live_endpoint_allow_real_trading_off_rejects(pr16_session_factory, pr16_db_url, monkeypatch):
    """
    当 is_live_endpoint=True（模拟）且 allow_real_trading=False 时，门禁拒绝，写 ORDER_REJECTED，不发起 HTTP。
    Demo（is_live_endpoint=False）不触发此门禁，OKX Demo 可正常下单。
    """
    from src.execution.okx_adapter import OkxExchangeAdapter
    from src.execution.okx_client import FakeOkxHttpClient

    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "token123")
    app_config = _app_config(allow_real_trading=False, live_confirm_token="token123", db_url=pr16_db_url)
    now = datetime.now(timezone.utc)
    decision_id = "pr16-gate-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-1",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    fake_client = FakeOkxHttpClient()
    okx_adapter = OkxExchangeAdapter(fake_client, "key", "secret", "pass")
    adapter = _LiveEndpointAdapter(okx_adapter)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            adapter,
            RiskManager(),
            config=WorkerConfig.from_app_config(app_config),
            app_config=app_config,
        )
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "failed"
    assert result.get("reason_code") == LIVE_GATE_ALLOW_REAL_TRADING_OFF
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    order_rejected_events = [e for e in events if e.event_type == EV_ORDER_REJECTED]
    assert len(order_rejected_events) >= 1
    assert order_rejected_events[0].reason_code == LIVE_GATE_ALLOW_REAL_TRADING_OFF
    okx_events = [e for e in events if "OKX_HTTP" in (e.event_type or "")]
    assert len(okx_events) == 0
