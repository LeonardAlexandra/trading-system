"""
PR14b 集成测试：
1）okx demo 模式缺 key/secret/passphrase → 启动 fail-fast（reason_code）
2）CONFIG_SNAPSHOT 不包含 okx secret/passphrase
3）强制 dry-run：strategy 指向 okx_demo 时走完整链路，但使用 Fake client，events 标记 dry_run，无真实网络
"""
from datetime import datetime, timezone
from decimal import Decimal
import json
import pytest

from src.config.app_config import load_app_config
from src.common.config_errors import ConfigValidationError
from src.common.reason_codes import OKX_SECRET_MISSING, OKX_LIVE_FORBIDDEN
from src.app.dependencies import set_session_factory, get_db_session
from src.database.connection import Base
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.okx_adapter import OkxExchangeAdapter
from src.execution.okx_client import FakeOkxHttpClient
from src.execution.exchange_adapter import DryRunExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.repositories.rate_limit_repository import RateLimitRepository
from src.repositories.circuit_breaker_repository import CircuitBreakerRepository


# ----- 配置 fail-fast -----
def test_pr14b_okx_demo_missing_secret_fail_fast(tmp_path):
    """okx_demo profile 存在但 okx 缺 api_key → 启动 fail-fast，reason_code=OKX_SECRET_MISSING"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./test.db
execution:
  batch_size: 10
strategies:
  S1:
    enabled: true
    exchange_profile_id: okx_demo
    account_id: acc1
exchange_profiles:
  okx_demo:
    id: okx_demo
    name: okx
    mode: okx_demo
accounts:
  acc1:
    exchange_profile_id: okx_demo
okx:
  env: demo
  api_key: ""
  secret: fake-secret
  passphrase: fake-pass
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == OKX_SECRET_MISSING
    assert "api_key" in (exc_info.value.message or "").lower()


def test_pr14b_okx_demo_missing_passphrase_fail_fast(tmp_path):
    """okx 缺 passphrase → fail-fast"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./test.db
execution:
  batch_size: 10
exchange_profiles:
  okx_demo:
    id: okx_demo
    mode: okx_demo
okx:
  env: demo
  api_key: fake-key
  secret: fake-secret
  passphrase: ""
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == OKX_SECRET_MISSING
    assert "passphrase" in (exc_info.value.message or "").lower()


def test_pr15a_okx_env_invalid_fail_fast(tmp_path):
    """PR15a/PR17b：okx.env 必须为 demo 或 live；无效值（如 prod）时启动 fail-fast。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./test.db
execution:
  batch_size: 10
exchange_profiles:
  okx_demo:
    id: okx_demo
    mode: okx_demo
okx:
  env: prod
  api_key: fake-key
  secret: fake-secret
  passphrase: fake-pass
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == OKX_LIVE_FORBIDDEN


def test_pr14b_config_snapshot_no_okx_secret(tmp_path):
    """CONFIG_SNAPSHOT message 不包含 okx api_key/secret/passphrase"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./test.db
execution:
  batch_size: 10
strategies:
  S1:
    enabled: true
    exchange_profile_id: okx_demo
exchange_profiles:
  okx_demo:
    id: okx_demo
    mode: okx_demo
okx:
  env: demo
  api_key: secret-key-xxx
  secret: secret-value-xxx
  passphrase: secret-pass-xxx
""")
    app_config = load_app_config(str(config_path))
    from src.config.snapshot import make_config_snapshot_message_for_strategy
    from src.config.strategy_resolver import resolve as resolve_strategy
    resolved = resolve_strategy(app_config, "S1")
    msg = make_config_snapshot_message_for_strategy(resolved)
    snapshot = json.loads(msg)
    raw_str = msg
    assert "secret-key-xxx" not in raw_str
    assert "secret-value-xxx" not in raw_str
    assert "secret-pass-xxx" not in raw_str
    assert "okx" not in snapshot or "api_key" not in str(snapshot.get("okx", {}))


# ----- 强制 dry-run 安全测试 -----
@pytest.fixture
def pr14b_db_url(tmp_path):
    return "sqlite+aiosqlite:///" + (tmp_path / "pr14b.db").as_posix()


@pytest.fixture
async def pr14b_session_factory(pr14b_db_url):
    import src.models
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    sync_url = pr14b_db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(pr14b_db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await aengine.dispose()


@pytest.mark.asyncio
async def test_pr14b_dry_run_okx_demo_fake_client_no_live_call(pr14b_session_factory, tmp_path):
    """
    strategy 指向 okx_demo，ExecutionEngine 使用 DryRunExchangeAdapter(OkxExchangeAdapter(FakeOkxHttpClient))：
    - 走完整链路
    - Fake client 未被调用（dry-run 在 wrapper 层就返回，不调用 inner adapter）
    - execution_events 标记 dry_run
    """
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
database:
  url: sqlite+aiosqlite:///./pr14b.db
execution:
  batch_size: 10
  dry_run: true
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
    okx_adapter = OkxExchangeAdapter(
        http_client=fake_client,
        api_key=app_config.okx.api_key,
        secret=app_config.okx.secret,
        passphrase=app_config.okx.passphrase,
    )
    dry_run_adapter = DryRunExchangeAdapter(okx_adapter)

    decision_id = "pr14b-dry-001"
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
            dry_run_adapter,
            RiskManager(),
            config=worker_config,
            app_config=app_config,
            rate_limit_repo=rate_repo,
            circuit_breaker_repo=circuit_repo,
        )
        result = await engine.execute_one(decision_id)
        await session.commit()

    assert result.get("status") == "filled"
    # Dry-run 包装器直接返回，不调用 inner OkxExchangeAdapter.create_order
    assert len(fake_client.post_calls) == 0
    assert result.get("exchange_order_id", "").startswith("dry_run_")

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    dry_run_events = [e for e in events if getattr(e, "dry_run", False)]
    assert len(dry_run_events) >= 1
    for e in events:
        assert "live endpoint" not in (e.message or "").lower()
