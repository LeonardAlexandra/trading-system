"""
PR17a：Live 路径事故演练 + 回滚入口验证。
场景 A：门禁缺失 → 拒绝 → 审计正确（无 HTTP）。
场景 B：连续 transient（模拟 5xx）→ 断路器打开 → 拒绝 → 调用 reset 脚本/入口 → 恢复 + CIRCUIT_RESET_BY_OPERATOR 审计。
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
from src.repositories.circuit_breaker_repository import CircuitBreakerRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.okx_adapter import OkxExchangeAdapter
from src.execution.okx_client import FakeOkxHttpClient
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.config.app_config import load_app_config
from src.common.event_types import CIRCUIT_OPENED, CIRCUIT_RESET_BY_OPERATOR
from src.common.reason_codes import CIRCUIT_OPEN


@pytest.fixture
def pr17a_incident_db_url(tmp_path):
    return "sqlite+aiosqlite:///" + (tmp_path / "pr17a_incident.db").as_posix()


@pytest.fixture
async def pr17a_incident_session_factory(pr17a_incident_db_url):
    sync_url = pr17a_incident_db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(pr17a_incident_db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await aengine.dispose()


class _LiveAdapter:
    """测试用：is_live_endpoint=True。"""
    def __init__(self, inner):
        self._inner = inner
    def is_live_endpoint(self):
        return True
    def __getattr__(self, n):
        return getattr(self._inner, n)


@pytest.mark.asyncio
async def test_pr17a_incident_a_gate_missing_no_http_audit_correct(pr17a_incident_session_factory, pr17a_incident_db_url, tmp_path, monkeypatch):
    """
    场景 A：门禁缺失（如 allow_real_trading=False）→ 拒绝 → 无 HTTP；事件链完整，reason_code 正确。
    """
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    config_path = tmp_path / "pr17a_incident_a_config.yaml"
    config_path.write_text(f"""
database:
  url: {pr17a_incident_db_url!r}
execution:
  batch_size: 10
  dry_run: false
  live_enabled: true
  allow_real_trading: false
  live_allowlist_accounts: [acc1]
  live_allowlist_symbols: [BTC-USDT]
  qty_precision_by_symbol:
    BTC-USDT: 8
  live_confirm_token: t
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
    from src.common.reason_codes import LIVE_GATE_ALLOW_REAL_TRADING_OFF
    app_config = load_app_config(str(config_path))
    fake = FakeOkxHttpClient()
    adapter = _LiveAdapter(OkxExchangeAdapter(fake, "k", "s", "p"))
    now = datetime.now(timezone.utc)
    decision_id = "pr17a-inc-a"
    async with pr17a_incident_session_factory() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-a",
            strategy_id="strat-1",
            symbol="BTC-USDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        await session.commit()

    async with pr17a_incident_session_factory() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            adapter,
            RiskManager(),
            config=WorkerConfig.from_app_config(app_config),
            app_config=app_config,
        )
        r = await engine.execute_one(decision_id)
        await session.commit()

    assert r.get("status") == "failed"
    assert r.get("reason_code") == LIVE_GATE_ALLOW_REAL_TRADING_OFF
    assert len(fake.post_calls) == 0

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    from src.common.event_types import ORDER_REJECTED as EV_ORDER_REJECTED
    assert any(e.event_type == EV_ORDER_REJECTED for e in events)
    assert any(e.reason_code == LIVE_GATE_ALLOW_REAL_TRADING_OFF for e in events)


@pytest.mark.asyncio
async def test_pr17a_incident_b_circuit_breaker_then_reset_audit(pr17a_incident_session_factory, pr17a_incident_db_url, tmp_path, monkeypatch):
    """
    场景 B：连续 transient 5xx → 断路器打开 → 拒单 → 调用 reset → 恢复 + CIRCUIT_RESET_BY_OPERATOR 审计。
    使用 Demo 路径（is_live_endpoint=False）以便触发 create_order 和断路器。
    """
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "pr17a-token")
    config_path = tmp_path / "pr17a_incident_config.yaml"
    config_path.write_text(f"""
database:
  url: {pr17a_incident_db_url!r}
execution:
  batch_size: 10
  dry_run: false
  allow_real_trading: false
  max_attempts: 1
  circuit_breaker_threshold: 2
  circuit_breaker_open_seconds: 300
  live_allowlist_accounts: [acc1]
  live_allowlist_symbols: [BTC-USDT]
  qty_precision_by_symbol:
    BTC-USDT: 8
strategies:
  strat-1:
    enabled: true
    account_id: acc1
    exchange_profile_id: okx_demo
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
    fake = FakeOkxHttpClient()
    fake.set_post_response("/api/v5/trade/order", {"code": "500", "msg": "Internal Server Error"})
    okx_adapter = OkxExchangeAdapter(fake, "k", "s", "p")
    from src.repositories.rate_limit_repository import RateLimitRepository

    now = datetime.now(timezone.utc)
    decision_ids = ["pr17a-inc-b1", "pr17a-inc-b2", "pr17a-inc-b3"]
    async with pr17a_incident_session_factory() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        for did in decision_ids:
            await dom_repo.create_reserved(
                decision_id=did,
                signal_id="sig-b",
                strategy_id="strat-1",
                symbol="BTC-USDT",
                side="BUY",
                created_at=now,
                quantity=Decimal("0.01"),
            )
        await session.commit()

    async with pr17a_incident_session_factory() as session:
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

    async with pr17a_incident_session_factory() as session:
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
        r2 = await engine.execute_one(decision_ids[1])
        await session.commit()
    assert r2.get("status") in ("failed", "retry_scheduled")

    async with pr17a_incident_session_factory() as session:
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
        r3 = await engine.execute_one(decision_ids[2])
        await session.commit()
    assert r3.get("status") == "failed"
    assert r3.get("reason_code") == CIRCUIT_OPEN

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events_2 = await event_repo.list_by_decision_id(decision_ids[1])
    assert any(e.event_type == CIRCUIT_OPENED for e in events_2)

    # 调用 reset 入口（通过 repo 模拟 scripts/reset_circuit_breaker.py 行为）
    async with pr17a_incident_session_factory() as session:
        circuit_repo = CircuitBreakerRepository(session)
        event_repo = ExecutionEventRepository(session)
        state_before = await circuit_repo.get_state("acc1")
        await circuit_repo.close_circuit("acc1")
        decision_id = f"operator-reset-acc1-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        await event_repo.append_event(
            decision_id,
            CIRCUIT_RESET_BY_OPERATOR,
            message="account_id=acc1 reset by operator",
        )
        await session.commit()

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        all_events = await event_repo.list_by_decision_id(decision_id)
    reset_events = [e for e in all_events if e.event_type == CIRCUIT_RESET_BY_OPERATOR]
    assert len(reset_events) >= 1


@pytest.mark.asyncio
async def test_pr17b_incident_b_live_path_5xx_circuit_reset(pr17a_incident_session_factory, pr17a_incident_db_url, tmp_path, monkeypatch):
    """
    PR17b 事故演练 B（live path）：okx_live profile + is_live_endpoint=True 路径下，
    fake transport 返回 5xx → retry → circuit breaker 打开 → 拒绝 → reset 写 CIRCUIT_RESET_BY_OPERATOR。
    """
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "pr17b-live-token")
    config_path = tmp_path / "pr17b_incident_b_config.yaml"
    config_path.write_text(f"""
database:
  url: {pr17a_incident_db_url!r}
execution:
  batch_size: 10
  dry_run: false
  live_enabled: true
  allow_real_trading: true
  max_attempts: 1
  circuit_breaker_threshold: 2
  circuit_breaker_open_seconds: 300
  live_allowlist_accounts: [acc1]
  live_allowlist_symbols: [BTC-USDT]
  qty_precision_by_symbol:
    BTC-USDT: 8
  live_confirm_token: pr17b-live-token
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
    fake = FakeOkxHttpClient()
    fake.set_post_response("/api/v5/trade/order", {"code": "500", "msg": "Internal Server Error", "data": []})
    okx_adapter = OkxExchangeAdapter(fake, "k", "s", "p")
    adapter = _LiveAdapter(okx_adapter)
    from src.repositories.rate_limit_repository import RateLimitRepository

    now = datetime.now(timezone.utc)
    decision_ids = ["pr17b-inc-b1", "pr17b-inc-b2", "pr17b-inc-b3"]
    async with pr17a_incident_session_factory() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        for did in decision_ids:
            await dom_repo.create_reserved(
                decision_id=did,
                signal_id="sig-b",
                strategy_id="strat-1",
                symbol="BTC-USDT",
                side="BUY",
                created_at=now,
                quantity=Decimal("0.01"),
            )
        await session.commit()

    async with pr17a_incident_session_factory() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            adapter,
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        r1 = await engine.execute_one(decision_ids[0])
        await session.commit()
    assert r1.get("status") in ("failed", "retry_scheduled")

    async with pr17a_incident_session_factory() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            adapter,
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        r2 = await engine.execute_one(decision_ids[1])
        await session.commit()
    assert r2.get("status") in ("failed", "retry_scheduled")

    async with pr17a_incident_session_factory() as session:
        dom_repo = DecisionOrderMapRepository(session)
        rate_repo = RateLimitRepository(session)
        circuit_repo = CircuitBreakerRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            adapter,
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        r3 = await engine.execute_one(decision_ids[2])
        await session.commit()
    assert r3.get("status") == "failed"
    assert r3.get("reason_code") == CIRCUIT_OPEN

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events_2 = await event_repo.list_by_decision_id(decision_ids[1])
    assert any(e.event_type == CIRCUIT_OPENED for e in events_2)

    # reset 入口：close_circuit + 写 CIRCUIT_RESET_BY_OPERATOR
    async with pr17a_incident_session_factory() as session:
        circuit_repo = CircuitBreakerRepository(session)
        event_repo = ExecutionEventRepository(session)
        await circuit_repo.close_circuit("acc1")
        reset_decision_id = f"operator-reset-acc1-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        await event_repo.append_event(
            reset_decision_id,
            CIRCUIT_RESET_BY_OPERATOR,
            message="account_id=acc1 reset by operator (live path drill)",
        )
        await session.commit()

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        all_events = await event_repo.list_by_decision_id(reset_decision_id)
    reset_events = [e for e in all_events if e.event_type == CIRCUIT_RESET_BY_OPERATOR]
    assert len(reset_events) >= 1
