import time

import pytest

from src.app.routers import health as health_router
from src.monitoring.models import HealthResult


async def _mock_alerts(_session, _limit):
    return []


async def _mock_errors_empty(self, **kwargs):
    return []


async def _mock_errors_many(self, **kwargs):
    return [type("E", (), {"created_at": None, "component": "", "message": "", "event_type": ""})() for _ in range(30)]


@pytest.mark.asyncio
async def test_error_rate_over_threshold_returns_degraded(monkeypatch):
    async def mock_check_all(self, session, exchange_adapter):
        return HealthResult(db_ok=True, exchange_ok=True, strategy_status={"summary": "ok", "strategies": {}})

    async def mock_db_probe(session):
        return True, 1.0

    monkeypatch.setattr(health_router.HealthChecker, "check_all", mock_check_all)
    monkeypatch.setattr(health_router, "_probe_database_latency_ms", mock_db_probe)
    monkeypatch.setattr(health_router.LogRepository, "query", _mock_errors_many)
    monkeypatch.setattr(health_router, "_fetch_recent_alerts", _mock_alerts)

    summary = await health_router._build_summary(
        session=None,
        error_rate_threshold=0.1,
        recent_errors_threshold=20,
        recent_alerts_limit=20,
        recent_errors_limit=20,
    )
    assert summary["status"] == "degraded"
    assert summary["metrics"]["thresholds"]["max_error_rate"] == 0.1


@pytest.mark.asyncio
async def test_database_connection_exception_returns_unhealthy(monkeypatch):
    async def mock_check_all(self, session, exchange_adapter):
        return HealthResult(db_ok=True, exchange_ok=True, strategy_status={"summary": "ok", "strategies": {}})

    async def mock_db_probe(session):
        return False, 9.5

    monkeypatch.setattr(health_router.HealthChecker, "check_all", mock_check_all)
    monkeypatch.setattr(health_router, "_probe_database_latency_ms", mock_db_probe)
    monkeypatch.setattr(health_router.LogRepository, "query", _mock_errors_empty)
    monkeypatch.setattr(health_router, "_fetch_recent_alerts", _mock_alerts)

    summary = await health_router._build_summary(
        session=None,
        error_rate_threshold=0.1,
        recent_errors_threshold=20,
        recent_alerts_limit=20,
        recent_errors_limit=20,
    )
    assert summary["status"] == "unhealthy"
    assert summary["components"]["database"]["ok"] is False


@pytest.mark.asyncio
async def test_normal_case_returns_healthy(monkeypatch):
    async def mock_check_all(self, session, exchange_adapter):
        return HealthResult(db_ok=True, exchange_ok=True, strategy_status={"summary": "ok", "strategies": {}})

    async def mock_db_probe(session):
        return True, 1.2

    monkeypatch.setattr(health_router.HealthChecker, "check_all", mock_check_all)
    monkeypatch.setattr(health_router, "_probe_database_latency_ms", mock_db_probe)
    monkeypatch.setattr(health_router.LogRepository, "query", _mock_errors_empty)
    monkeypatch.setattr(health_router, "_fetch_recent_alerts", _mock_alerts)

    summary = await health_router._build_summary(
        session=None,
        error_rate_threshold=0.1,
        recent_errors_threshold=20,
        recent_alerts_limit=20,
        recent_errors_limit=20,
    )
    assert summary["status"] == "healthy"
    assert summary["overall_ok"] is True


@pytest.mark.asyncio
async def test_health_check_execution_under_100ms_with_mocks(monkeypatch):
    async def mock_check_all(self, session, exchange_adapter):
        return HealthResult(db_ok=True, exchange_ok=True, strategy_status={"summary": "ok", "strategies": {}})

    async def mock_db_probe(session):
        return True, 0.8

    monkeypatch.setattr(health_router.HealthChecker, "check_all", mock_check_all)
    monkeypatch.setattr(health_router, "_probe_database_latency_ms", mock_db_probe)
    monkeypatch.setattr(health_router.LogRepository, "query", _mock_errors_empty)
    monkeypatch.setattr(health_router, "_fetch_recent_alerts", _mock_alerts)

    started = time.perf_counter()
    summary = await health_router._build_summary(
        session=None,
        error_rate_threshold=0.1,
        recent_errors_threshold=20,
        recent_alerts_limit=20,
        recent_errors_limit=20,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert summary["status"] == "healthy"
    assert elapsed_ms < 100.0


def test_prometheus_output_is_strict_collectable_format():
    summary = {
        "status": "healthy",
        "components": {
            "database": {"ok": True},
            "queue": {"ok": True},
            "execution_worker": {"ok": True},
            "exchange": {"ok": False},
        },
        "metrics": {"error_rate": 0.01, "recent_errors": 2},
    }
    output = health_router._build_prometheus_metrics(summary)

    assert "..." not in output
    assert 'health_status{status="healthy"} 1' in output
    assert 'health_status{status="degraded"} 0' in output
    assert 'health_status{status="unhealthy"} 0' in output

    assert 'component_status{component="database"} 1' in output
    assert 'component_status{component="queue"} 1' in output
    assert 'component_status{component="execution_worker"} 1' in output
    assert 'component_status{component="exchange"} 0' in output
