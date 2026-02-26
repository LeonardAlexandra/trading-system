"""
Phase1.2 C4：监控与告警验收测试（SystemMonitor / HealthChecker / AlertSystem）

1) get_metrics：返回 dict 含 4 个必需字段；数据非硬编码（插入后计数变化）
2) check_all：db_ok 真实查询；exchange_ok 可 mock 验证；strategy_status 有结构
3) evaluate_rules：至少 2 条规则；触发后 list[Alert] 非空且 log 存在；SMTP 失败降级；冷却 60s
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401
from src.models.dedup_signal import DedupSignal
from src.models.trade import Trade
from src.repositories.log_repository import LogRepository
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository
from src.monitoring.system_monitor import SystemMonitor
from src.monitoring.health_checker import HealthChecker
from src.monitoring.alert_system import AlertSystem
from src.monitoring.models import HealthResult


@pytest.fixture
def c4_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def c4_db_url(c4_tmp_path):
    return "sqlite+aiosqlite:///" + (c4_tmp_path / "c4_monitoring.db").as_posix()


@pytest.fixture
def c4_sync_db_url(c4_tmp_path):
    return "sqlite:///" + (c4_tmp_path / "c4_monitoring.db").as_posix()


@pytest.fixture
def c4_schema(c4_sync_db_url):
    engine = create_engine(c4_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def c4_session_factory(c4_db_url, c4_schema):
    engine = create_async_engine(c4_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


# ---------- 1) get_metrics ----------
@pytest.mark.asyncio
async def test_get_metrics_returns_required_fields(c4_session_factory):
    """get_metrics() 返回 dict 且包含 4 个必需字段及 window_seconds。"""
    async with get_db_session() as session:
        monitor = SystemMonitor(default_window_seconds=3600)
        metrics = await monitor.get_metrics(session)
    assert isinstance(metrics, dict)
    assert "signals_received_count" in metrics
    assert "orders_executed_count" in metrics
    assert "error_count" in metrics
    assert "error_rate" in metrics
    assert "window_seconds" in metrics
    assert metrics["window_seconds"] == 3600


@pytest.mark.asyncio
async def test_get_metrics_data_from_real_queries(c4_session_factory):
    """插入 signal / trade / error log 后，get_metrics 计数增加，证明非硬编码。"""
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        monitor = SystemMonitor(default_window_seconds=7200)
        m0 = await monitor.get_metrics(session)
    async with get_db_session() as session:
        session.add(DedupSignal(signal_id="sig-m1", first_seen_at=now, received_at=now))
        await session.flush()
    async with get_db_session() as session:
        session.add(Trade(
            trade_id="tr-m1",
            strategy_id="s1",
            decision_id="d1",
            signal_id="sig-m1",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            price=Decimal("50000"),
            executed_at=now,
        ))
        await session.flush()
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        await log_repo.write("ERROR", "test", "error for metrics test")
    async with get_db_session() as session:
        monitor = SystemMonitor(default_window_seconds=7200)
        m1 = await monitor.get_metrics(session)
    assert m1["signals_received_count"] >= m0["signals_received_count"] + 1
    assert m1["orders_executed_count"] >= m0["orders_executed_count"] + 1
    assert m1["error_count"] >= m0["error_count"] + 1


# ---------- 2) check_all ----------
@pytest.mark.asyncio
async def test_check_all_db_ok(c4_session_factory):
    """db_ok 通过真实 DB 查询为 True。"""
    from src.execution.exchange_adapter import PaperExchangeAdapter
    async with get_db_session() as session:
        checker = HealthChecker()
        health = await checker.check_all(session, PaperExchangeAdapter(filled=True))
    assert health.db_ok is True
    assert health.exchange_ok is True
    assert "strategies" in health.strategy_status


@pytest.mark.asyncio
async def test_check_all_exchange_down_when_adapter_raises(c4_session_factory):
    """exchange 不可用时 exchange_ok 为 False。"""
    from src.execution.exchange_adapter import PaperExchangeAdapter

    class FailingAdapter(PaperExchangeAdapter):
        async def get_account_info(self):
            raise RuntimeError("mock exchange unreachable")

    async with get_db_session() as session:
        checker = HealthChecker()
        health = await checker.check_all(session, FailingAdapter(filled=True))
    assert health.db_ok is True
    assert health.exchange_ok is False
    assert "strategies" in health.strategy_status


@pytest.mark.asyncio
async def test_check_all_strategy_status_structure(c4_session_factory):
    """strategy_status 有明确结构（含 strategies 或 summary）。"""
    async with get_db_session() as session:
        repo = StrategyRuntimeStateRepository(session)
        from src.models.strategy_runtime_state import StrategyRuntimeState
        session.add(StrategyRuntimeState(strategy_id="strat-c4", status="RUNNING"))
        await session.flush()
    async with get_db_session() as session:
        from src.execution.exchange_adapter import PaperExchangeAdapter
        checker = HealthChecker()
        health = await checker.check_all(session, PaperExchangeAdapter(filled=True))
    assert "strategies" in health.strategy_status
    assert health.strategy_status.get("strategies") is not None


# ---------- 3) evaluate_rules ----------
@pytest.mark.asyncio
async def test_evaluate_rules_fires_on_db_down(c4_session_factory):
    """规则 db_ok==false 触发 CRITICAL；返回非空 Alert 且 log 表有记录。"""
    rules = [
        {
            "rule_id": "db_down",
            "condition": "db_ok == false",
            "level": "CRITICAL",
            "component": "health",
            "title": "DB down",
            "message_template": "db_ok=false",
        },
    ]
    alert_system = AlertSystem(rules)
    # 模拟 health 为 db_ok=False（不真关 DB，用构造的 HealthResult）
    health_bad = HealthResult(db_ok=False, exchange_ok=True, strategy_status={"strategies": {}})
    metrics = {"signals_received_count": 0, "orders_executed_count": 0, "error_count": 0, "error_rate": 0.0}

    async with get_db_session() as session:
        log_repo = LogRepository(session)
        alerts = await alert_system.evaluate_rules(session, metrics, health_bad, log_repo)
    assert len(alerts) >= 1
    assert alerts[0].level == "CRITICAL"
    assert "db" in alerts[0].title.lower() or "db_down" in alerts[0].component

    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows = await log_repo.query(level="ERROR", limit=5)
    assert any("alert" in (r.event_type or "") or "CRITICAL" in (r.message or "") for r in rows)


@pytest.mark.asyncio
async def test_evaluate_rules_error_rate_threshold(c4_session_factory):
    """规则 error_rate > 阈值触发；返回 Alert 且 log 存在。"""
    rules = [
        {
            "rule_id": "error_rate_high",
            "condition": "error_rate > 0.1",
            "level": "WARNING",
            "component": "metrics",
            "title": "Error rate high",
            "message_template": "error_rate={error_rate}",
        },
    ]
    alert_system = AlertSystem(rules)
    health_ok = HealthResult(db_ok=True, exchange_ok=True, strategy_status={"strategies": {}})
    metrics = {"signals_received_count": 10, "orders_executed_count": 5, "error_count": 2, "error_rate": 1.5}

    async with get_db_session() as session:
        log_repo = LogRepository(session)
        alerts = await alert_system.evaluate_rules(session, metrics, health_ok, log_repo)
    assert len(alerts) >= 1
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows = await log_repo.query(level="WARNING", limit=5)
    assert any("alert" in (r.event_type or "") or "Error rate" in (r.message or "") for r in rows)


@pytest.mark.asyncio
async def test_smtp_failure_fallback_only_log(c4_session_factory):
    """SMTP 发送失败时不抛异常，仅写 log（可复现：mock send_email 抛异常）。"""
    sent = []

    def failing_send(to: str, subject: str, body: str):
        sent.append((to, subject, body))
        raise RuntimeError("mock SMTP failure")

    rules = [{"rule_id": "db_down", "condition": "db_ok == false", "level": "CRITICAL", "component": "health", "title": "DB down", "message_template": "db down"}]
    alert_system = AlertSystem(rules, send_email=failing_send)
    health_bad = HealthResult(db_ok=False, exchange_ok=True, strategy_status={})
    metrics = {"signals_received_count": 0, "orders_executed_count": 0, "error_count": 0, "error_rate": 0.0}

    async with get_db_session() as session:
        log_repo = LogRepository(session)
        alerts = await alert_system.evaluate_rules(session, metrics, health_bad, log_repo)
    assert len(alerts) >= 1
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows = await log_repo.query(limit=5)
    assert any(r.level in ("ERROR", "WARNING") for r in rows)


@pytest.mark.asyncio
async def test_alert_cooldown_same_rule_once_per_minute(c4_session_factory):
    """同 rule_id 在 60 秒内第二次评估不再次触发（只产生 1 条告警）。"""
    rules = [{"rule_id": "cooldown_test", "condition": "db_ok == false", "level": "WARNING", "component": "health", "title": "Cooldown", "message_template": "test"}]
    alert_system = AlertSystem(rules)
    health_bad = HealthResult(db_ok=False, exchange_ok=True, strategy_status={})
    metrics = {"signals_received_count": 0, "orders_executed_count": 0, "error_count": 0, "error_rate": 0.0}

    async with get_db_session() as session:
        log_repo = LogRepository(session)
        alerts1 = await alert_system.evaluate_rules(session, metrics, health_bad, log_repo)
    assert len(alerts1) >= 1
    # 立即再次评估：应被冷却，不产生新 Alert（_last_fired 已更新，60s 内不再 fire）
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        alerts2 = await alert_system.evaluate_rules(session, metrics, health_bad, log_repo)
    assert len(alerts2) == 0

    # 模拟时间过去 60 秒：重置冷却（通过新实例或手动改 _last_fired）
    alert_system2 = AlertSystem(rules)
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        alerts3 = await alert_system2.evaluate_rules(session, metrics, health_bad, log_repo)
    assert len(alerts3) >= 1
