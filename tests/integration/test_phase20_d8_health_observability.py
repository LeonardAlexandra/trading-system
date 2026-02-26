import os
import time
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from src.database.connection import Base
from src.monitoring.models import HealthResult
import src.models  # noqa: F401


@pytest.fixture
def d8_db_urls(tmp_path):
    db_path = tmp_path / "d8_health.db"
    return {
        "async": "sqlite+aiosqlite:///" + db_path.as_posix(),
        "sync": "sqlite:///" + db_path.as_posix(),
    }


@pytest.fixture
def d8_schema(d8_db_urls):
    engine = create_engine(d8_db_urls["sync"])
    Base.metadata.create_all(engine)
    engine.dispose()


def _set_startup_env(monkeypatch, d8_db_urls, tmp_path):
    monkeypatch.setenv("TV_WEBHOOK_SECRET", "d8_secret")
    monkeypatch.setenv("STRATEGY_ID", "D8_STRATEGY")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DATABASE_URL", d8_db_urls["async"])


def test_health_summary_handler_e2e_under_100ms(monkeypatch, d8_db_urls, d8_schema, tmp_path):
    _set_startup_env(monkeypatch, d8_db_urls, tmp_path)
    from src.app.main import create_app

    fake_health = HealthResult(db_ok=True, exchange_ok=True, strategy_status={"summary": "ok", "strategies": {}})
    with patch("src.monitoring.health_checker.HealthChecker.check_all", new=AsyncMock(return_value=fake_health)):
        with patch("src.app.routers.health._probe_database_latency_ms", new=AsyncMock(return_value=(True, 1.0))):
            app = create_app()
            with TestClient(app) as client:
                started = time.perf_counter()
                resp = client.get("/api/health/summary")
                elapsed_ms = (time.perf_counter() - started) * 1000.0

    assert resp.status_code == 200, resp.text
    assert elapsed_ms < 100.0, f"health summary handler too slow: {elapsed_ms:.3f}ms"


def test_health_summary_sql_guard_no_violations(monkeypatch, d8_db_urls, d8_schema, tmp_path):
    _set_startup_env(monkeypatch, d8_db_urls, tmp_path)
    from src.app.main import create_app

    captured_sql: list[str] = []
    violations: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        sql = " ".join((statement or "").strip().split())
        lowered = sql.lower()
        captured_sql.append(sql)

        if "count(" in lowered and "limit" not in lowered:
            violations.append(f"COUNT_NO_LIMIT: {sql}")

        # recent_errors/recent_alerts 都来自 log 表，强制要求 LIMIT
        if "select" in lowered and " from log " in f" {lowered} ":
            if "limit" not in lowered:
                violations.append(f"LOG_SELECT_NO_LIMIT: {sql}")

    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    fake_health = HealthResult(db_ok=True, exchange_ok=True, strategy_status={"summary": "ok", "strategies": {}})
    try:
        with patch("src.monitoring.health_checker.HealthChecker.check_all", new=AsyncMock(return_value=fake_health)):
            with patch("src.app.routers.health._probe_database_latency_ms", new=AsyncMock(return_value=(True, 1.0))):
                app = create_app()
                with TestClient(app) as client:
                    resp = client.get("/api/health/summary")
        assert resp.status_code == 200, resp.text
        assert len(captured_sql) > 0, "expected captured SQL statements for audit"
        print(f"D8_SQL_CAPTURE_TOTAL={len(captured_sql)}")
        print(f"D8_SQL_VIOLATIONS_TOTAL={len(violations)}")
        assert not violations, "SQL guard violations found:\n" + "\n".join(violations)
    finally:
        event.remove(Engine, "before_cursor_execute", _before_cursor_execute)
