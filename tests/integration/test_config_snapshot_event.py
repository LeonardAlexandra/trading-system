"""
PR10 配置快照审计集成测试：execute_one 写入 CONFIG_SNAPSHOT，白名单字段存在、不含 secret
"""
import json
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
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.common.event_types import CLAIMED, CONFIG_SNAPSHOT, RISK_CHECK_STARTED
from src.config.snapshot import MAX_SNAPSHOT_BYTES
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


def _minimal_app_config(webhook_secret=None):
    """PR11：含 strategies 以便 resolve(strat-1) 成功，CONFIG_SNAPSHOT 含 strategy_id + fingerprint"""
    return AppConfig(
        database=DatabaseConfig(url="sqlite+aiosqlite:///./snapshot_test.db"),
        logging=LoggingConfig(),
        webhook=WebhookConfig(tradingview_secret=webhook_secret),
        execution=ExecutionConfig(
            poll_interval_seconds=1.0,
            batch_size=10,
            max_concurrency=5,
            max_attempts=3,
            backoff_seconds=[1, 5, 30],
        ),
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper", paper_filled=True),
        strategies={"strat-1": StrategyEntryConfig(enabled=True)},
    )


@pytest.fixture
def exec_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def exec_db_url(exec_tmp_path):
    return "sqlite+aiosqlite:///" + (exec_tmp_path / "config_snapshot.db").as_posix()


@pytest.fixture
def exec_sync_db_url(exec_tmp_path):
    return "sqlite:///" + (exec_tmp_path / "config_snapshot.db").as_posix()


@pytest.fixture
def exec_schema(exec_sync_db_url):
    engine = create_engine(exec_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def exec_session_factory(exec_db_url, exec_schema):
    engine = create_async_engine(exec_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_config_snapshot_written_and_contains_expected_fields(exec_session_factory):
    """执行一次成功 flow，查询 execution_events 找到 CONFIG_SNAPSHOT，断言 message 含 execution/risk/exchange 关键字段"""
    app_config = _minimal_app_config()
    now = datetime.now(timezone.utc)
    decision_id = "snapshot-fields-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-snap-1",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=WorkerConfig.from_app_config(app_config),
            app_config=app_config,
        )
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "filled"

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    event_types = [e.event_type for e in events]
    assert CONFIG_SNAPSHOT in event_types
    assert CLAIMED in event_types
    assert RISK_CHECK_STARTED in event_types

    config_ev = next(e for e in events if e.event_type == CONFIG_SNAPSHOT)
    assert config_ev.message is not None
    snapshot = json.loads(config_ev.message)
    assert "execution" in snapshot
    assert "risk" in snapshot
    assert "exchange" in snapshot
    # PR11：CONFIG_SNAPSHOT 含 strategy_id、strategy_config_fingerprint
    assert snapshot.get("strategy_id") == "strat-1"
    assert "strategy_config_fingerprint" in snapshot
    assert snapshot["execution"].get("batch_size") == 10
    assert snapshot["execution"].get("max_concurrency") == 5
    assert snapshot["execution"].get("backoff_seconds") == [1, 5, 30]
    assert snapshot["risk"].get("cooldown_mode") == "after_fill"
    assert snapshot["exchange"].get("mode") == "paper"
    assert snapshot["exchange"].get("paper_filled") is True
    assert config_ev.reason_code is None


@pytest.mark.asyncio
async def test_config_snapshot_does_not_contain_secret(exec_session_factory):
    """配置中设置 webhook.tradingview_secret=supersecret，执行一次，断言 CONFIG_SNAPSHOT.message 不包含 supersecret 及 tradingview_secret"""
    app_config = _minimal_app_config(webhook_secret="supersecret")
    now = datetime.now(timezone.utc)
    decision_id = "snapshot-no-secret-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-snap-2",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=WorkerConfig.from_app_config(app_config),
            app_config=app_config,
        )
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "filled"

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    config_ev = next((e for e in events if e.event_type == CONFIG_SNAPSHOT), None)
    assert config_ev is not None
    assert config_ev.message is not None
    assert "supersecret" not in config_ev.message
    assert "tradingview_secret" not in config_ev.message
    snapshot = json.loads(config_ev.message)
    assert "webhook" not in snapshot


@pytest.mark.asyncio
async def test_config_snapshot_truncates_when_too_large(exec_session_factory):
    """P3：backoff_seconds 很大时 snapshot 超限，message 含 snapshot_truncated=true，长度受控，不含 secret"""
    # 构造超大 backoff_seconds 使完整 snapshot 超过 MAX_SNAPSHOT_BYTES；PR11 含 strategies 以便 resolve 成功
    huge_backoff = [1] * 5000
    app_config = AppConfig(
        database=DatabaseConfig(url="sqlite+aiosqlite:///./snapshot_test.db"),
        logging=LoggingConfig(),
        webhook=WebhookConfig(tradingview_secret="must_not_appear"),
        execution=ExecutionConfig(
            poll_interval_seconds=1.0,
            batch_size=10,
            max_concurrency=5,
            max_attempts=3,
            backoff_seconds=huge_backoff,
        ),
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper", paper_filled=True),
        strategies={"strat-1": StrategyEntryConfig(enabled=True)},
    )
    now = datetime.now(timezone.utc)
    decision_id = "snapshot-truncate-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-snap-3",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=WorkerConfig.from_app_config(app_config),
            app_config=app_config,
        )
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "filled"

    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    config_ev = next((e for e in events if e.event_type == CONFIG_SNAPSHOT), None)
    assert config_ev is not None
    assert config_ev.message is not None
    snapshot = json.loads(config_ev.message)
    assert snapshot.get("snapshot_truncated") is True
    assert "size" in snapshot
    assert snapshot["size"] > MAX_SNAPSHOT_BYTES
    assert len(config_ev.message.encode("utf-8")) <= int(MAX_SNAPSHOT_BYTES * 1.2)
    assert "tradingview_secret" not in config_ev.message
    assert "must_not_appear" not in config_ev.message
    assert "execution" in snapshot and "risk" in snapshot and "exchange" in snapshot
