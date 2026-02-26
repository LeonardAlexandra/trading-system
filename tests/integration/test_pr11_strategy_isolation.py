"""
PR11 集成测试：多 strategy_id 支持、策略级配置解析、风控/执行按 strategy_id 隔离、审计快照含 strategy_id/fingerprint
"""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.app.main import create_app
from src.database.connection import Base
import src.models
from src.app.dependencies import set_session_factory, get_db_session
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.risk_state_repository import RiskStateRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
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


TEST_WEBHOOK_SECRET = "test_pr11_secret"


def _make_signature(secret: str, payload_bytes: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    ).decode("utf-8")


@pytest.fixture
def pr11_app(monkeypatch, tmp_path):
    """多策略配置：strat-A（启用）、strat-B（启用，不同风控）"""
    monkeypatch.setenv("TV_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    tmp_db = (tmp_path / "pr11.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + tmp_db)
    engine = create_engine("sqlite:///" + tmp_db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return create_app()


@pytest.fixture
def pr11_client(pr11_app):
    with TestClient(pr11_app) as c:
        yield c


def test_webhook_strategy_not_found_returns_422(pr11_client):
    """payload 中 strategy_id 在配置中不存在 -> 422 STRATEGY_NOT_FOUND"""
    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-01-27T12:00:00Z",
        "indicator_name": "X",
        "strategy_id": "NONEXISTENT_STRATEGY",
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = _make_signature(TEST_WEBHOOK_SECRET, payload_bytes)
    r = pr11_client.post(
        "/webhook/tradingview",
        content=payload_bytes,
        headers={"Content-Type": "application/json", "X-TradingView-Signature": sig},
    )
    assert r.status_code == 422
    data = r.json()
    assert data.get("reason_code") == "STRATEGY_NOT_FOUND"
    assert data.get("strategy_id") == "NONEXISTENT_STRATEGY"


def test_webhook_strategy_disabled_returns_422(monkeypatch, tmp_path):
    """某 strategy_id 在 app_config.strategies 中存在但 enabled=False -> 422 STRATEGY_DISABLED；不进入 execution、不产生 decision、不写 execution_events"""
    import sqlite3
    monkeypatch.setenv("TV_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    tmp_db = (tmp_path / "disabled_strat.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + tmp_db)
    config_file = tmp_path / "config_disabled_strat.yaml"
    config_file.write_text(
        "database:\n  url: ''\n"
        "execution:\n  batch_size: 10\n  max_attempts: 3\n  backoff_seconds: [1, 5, 30]\n"
        "risk:\n  cooldown_mode: after_fill\n"
        "strategies:\n  DISABLED_STRAT:\n    enabled: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    from sqlalchemy import create_engine
    engine = create_engine("sqlite:///" + tmp_db)
    Base.metadata.create_all(engine)
    engine.dispose()
    app = create_app()
    with TestClient(app) as client:
        payload = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "timestamp": "2026-01-27T12:00:00Z",
            "indicator_name": "X",
            "strategy_id": "DISABLED_STRAT",
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = _make_signature(TEST_WEBHOOK_SECRET, payload_bytes)
        r = client.post(
            "/webhook/tradingview",
            content=payload_bytes,
            headers={"Content-Type": "application/json", "X-TradingView-Signature": sig},
        )
    assert r.status_code == 422
    data = r.json()
    assert data.get("reason_code") == "STRATEGY_DISABLED"
    assert data.get("strategy_id") == "DISABLED_STRAT"
    if not (tmp_path / "disabled_strat.db").exists():
        return
    conn = sqlite3.connect(tmp_db)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM decision_order_map")
        (n_dom,) = cur.fetchone()
        cur = conn.execute("SELECT COUNT(*) FROM execution_events")
        (n_ev,) = cur.fetchone()
    finally:
        conn.close()
    assert n_dom == 0, "must not create decision when strategy disabled"
    assert n_ev == 0, "must not write execution_events when strategy disabled"


@pytest.mark.asyncio
async def test_risk_position_isolated_by_strategy_id(tmp_path):
    """不同 strategy_id 的仓位互不影响：strat-A 仓位满仍允许 strat-B 下单（按 strategy_id 隔离）"""
    db_url = "sqlite+aiosqlite:///" + (tmp_path / "risk_iso.db").as_posix()
    sync_url = "sqlite:///" + (tmp_path / "risk_iso.db").as_posix()
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine, class_=AsyncSession, expire_on_commit=False
    )
    set_session_factory(session_factory)

    # 策略 A：max_position_qty=1，已占满；策略 B：max_position_qty=2，可下单
    app_config = AppConfig(
        database=DatabaseConfig(url=db_url),
        logging=LoggingConfig(),
        webhook=WebhookConfig(tradingview_secret=TEST_WEBHOOK_SECRET),
        execution=ExecutionConfig(batch_size=10, max_attempts=3, backoff_seconds=[1, 5, 30]),
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper", paper_filled=True),
        strategies={
            "strat-A": StrategyEntryConfig(
                enabled=True,
                risk_override=RiskSectionConfig(max_position_qty=Decimal("1")),
            ),
            "strat-B": StrategyEntryConfig(
                enabled=True,
                risk_override=RiskSectionConfig(max_position_qty=Decimal("2")),
            ),
        },
    )

    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        pos_repo = PositionRepository(session)
        await pos_repo.upsert("strat-A", "BTCUSDT", Decimal("1"), side="LONG")
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id="dec-a-full",
            signal_id="sig-a",
            strategy_id="strat-A",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.5"),
        )
        await dom_repo.create_reserved(
            decision_id="dec-b-ok",
            signal_id="sig-b",
            strategy_id="strat-B",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.5"),
        )

    risk_state_repo = RiskStateRepository(session_factory())
    from src.config.strategy_resolver import resolve as resolve_strategy_config
    resolved_a = resolve_strategy_config(app_config, "strat-A")
    resolved_b = resolve_strategy_config(app_config, "strat-B")
    risk_a = RiskConfig.from_risk_section(resolved_a.risk)
    risk_b = RiskConfig.from_risk_section(resolved_b.risk)

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        pos_repo = PositionRepository(session)
        risk_mgr = RiskManager(
            position_repo=pos_repo,
            dom_repo=dom_repo,
            risk_state_repo=risk_state_repo,
            risk_config=RiskConfig(),
        )

        class MockDecision:
            decision_id = "dec-a-full"
            strategy_id = "strat-A"
            symbol = "BTCUSDT"
            side = "BUY"
            quantity = Decimal("0.5")

        class MockDecisionB:
            decision_id = "dec-b-ok"
            strategy_id = "strat-B"
            symbol = "BTCUSDT"
            side = "BUY"
            quantity = Decimal("0.5")

        res_a = await risk_mgr.check(MockDecision(), risk_config_override=risk_a)
        res_b = await risk_mgr.check(MockDecisionB(), risk_config_override=risk_b)

    assert res_a.get("allowed") is False
    assert res_a.get("reason_code") == "POSITION_LIMIT_EXCEEDED"
    assert res_b.get("allowed") is True

    await aengine.dispose()


@pytest.mark.asyncio
async def test_execution_engine_resolve_failure_marks_failed_no_order_no_position(tmp_path):
    """封版：strategy resolve 失败 → execution FAILED，不成交、不更新仓位，execution_events 记录 reason_code"""
    from src.models.decision_order_map_status import FAILED
    from src.repositories.execution_event_repository import ExecutionEventRepository
    from src.common.event_types import CLAIMED, FINAL_FAILED, CONFIG_SNAPSHOT
    from src.common.reason_codes import STRATEGY_NOT_FOUND
    from src.execution.worker_config import WorkerConfig

    db_url = "sqlite+aiosqlite:///" + (tmp_path / "resolve_fail.db").as_posix()
    sync_url = "sqlite:///" + (tmp_path / "resolve_fail.db").as_posix()
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine, class_=AsyncSession, expire_on_commit=False
    )
    set_session_factory(session_factory)

    # app_config 仅含 strat-1，decision 使用 strategy_id=missing-strat（resolve 会失败）
    app_config = AppConfig(
        database=DatabaseConfig(url=db_url),
        logging=LoggingConfig(),
        webhook=WebhookConfig(tradingview_secret=TEST_WEBHOOK_SECRET),
        execution=ExecutionConfig(batch_size=10, max_attempts=3, backoff_seconds=[1, 5, 30]),
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper", paper_filled=True),
        strategies={"strat-1": StrategyEntryConfig(enabled=True)},
    )
    now = datetime.now(timezone.utc)
    decision_id = "dec-resolve-fail-001"
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-rf",
            strategy_id="missing-strat",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine_inst = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=WorkerConfig.from_app_config(app_config),
            app_config=app_config,
        )
        result = await engine_inst.execute_one(decision_id)

    assert result.get("status") == "failed"
    assert result.get("reason_code") == STRATEGY_NOT_FOUND
    assert "exchange_order_id" not in result or result.get("exchange_order_id") is None

    async with get_db_session() as session:
        row = await DecisionOrderMapRepository(session).get_by_decision_id(decision_id)
        assert row is not None
        assert row.status == FAILED
        assert row.last_error == STRATEGY_NOT_FOUND
        events = await ExecutionEventRepository(session).list_by_decision_id(decision_id)
    event_types = [e.event_type for e in events]
    assert CLAIMED in event_types
    assert FINAL_FAILED in event_types
    assert CONFIG_SNAPSHOT not in event_types
    failed_ev = next(e for e in events if e.event_type == FINAL_FAILED)
    assert failed_ev.reason_code == STRATEGY_NOT_FOUND

    await aengine.dispose()


def test_multi_strategy_allow_position_schema_downgrade_fails_startup(monkeypatch):
    """封版：多策略 + ALLOW_POSITION_SCHEMA_DOWNGRADE=true → validate 失败（fail-fast）"""
    from src.common.config_errors import ConfigValidationError
    from src.common.reason_codes import MULTI_STRATEGY_POSITION_DOWNGRADE_FORBIDDEN

    monkeypatch.setenv("ALLOW_POSITION_SCHEMA_DOWNGRADE", "true")
    app_config = AppConfig(
        database=DatabaseConfig(url="sqlite:///./x.db"),
        logging=LoggingConfig(),
        webhook=WebhookConfig(),
        execution=ExecutionConfig(),
        risk=RiskSectionConfig(),
        exchange=ExchangeConfig(),
        strategies={
            "strat-A": StrategyEntryConfig(enabled=True),
            "strat-B": StrategyEntryConfig(enabled=True),
        },
    )
    with pytest.raises(ConfigValidationError) as exc_info:
        app_config.validate()
    assert exc_info.value.reason_code == MULTI_STRATEGY_POSITION_DOWNGRADE_FORBIDDEN
