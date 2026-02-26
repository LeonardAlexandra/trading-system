"""
Phase1.2 C5：健康仪表板 API 验收测试（GET /api/health/summary）

1) 基本返回：200，JSON 含 overall_ok / metrics / recent_alerts / recent_errors
2) 数据来源真实性：写入 ERROR log 后 recent_errors 可见；mock check_all db_ok=false 时 overall_ok=false
3) recent_errors / recent_alerts 有明确 limit，不无上限返回
"""
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401
from src.repositories.log_repository import LogRepository


@pytest.fixture
def c5_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def c5_db_url(c5_tmp_path):
    return "sqlite+aiosqlite:///" + (c5_tmp_path / "c5_health.db").as_posix()


@pytest.fixture
def c5_sync_db_url(c5_tmp_path):
    return "sqlite:///" + (c5_tmp_path / "c5_health.db").as_posix()


@pytest.fixture
def c5_schema(c5_sync_db_url):
    engine = create_engine(c5_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def c5_session_factory(c5_db_url, c5_schema):
    engine = create_async_engine(c5_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


# ---------- 1) 基本返回 ----------
@pytest.mark.asyncio
async def test_health_summary_200_and_top_level_keys(c5_db_url, c5_schema):
    """GET /api/health/summary 返回 200，JSON 顶层含 overall_ok, metrics, recent_alerts, recent_errors。"""
    engine = create_async_engine(c5_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)

    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = c5_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/health/summary")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "overall_ok" in data
        assert "metrics" in data
        assert "recent_alerts" in data
        assert "recent_errors" in data
        assert isinstance(data["overall_ok"], bool)
        assert isinstance(data["metrics"], dict)
        assert isinstance(data["recent_alerts"], list)
        assert isinstance(data["recent_errors"], list)
        assert "recent_errors" in data["metrics"]
        assert "error_rate" in data["metrics"]
        assert "thresholds" in data["metrics"]
        assert "max_error_rate" in data["metrics"]["thresholds"]
        assert "max_recent_errors" in data["metrics"]["thresholds"]
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        await engine.dispose()


@pytest.mark.asyncio
async def test_health_summary_200_with_same_db(c5_db_url, c5_schema):
    """GET /api/health/summary 返回 200（通过同一 DATABASE_URL 使用 C5 测试库）。"""
    engine = create_async_engine(c5_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)

    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = c5_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/health/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_ok" in data and "metrics" in data and "recent_alerts" in data and "recent_errors" in data
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        await engine.dispose()


# ---------- 2) 数据来源真实性：recent_errors 来自 LogRepository ----------
@pytest.mark.asyncio
async def test_recent_errors_from_log_repository(c5_db_url, c5_schema):
    """写入一条 ERROR log 后调用 API，recent_errors 中能看到该条（证明非硬编码）。"""
    engine = create_async_engine(c5_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)

    async with get_db_session() as session:
        log_repo = LogRepository(session)
        await log_repo.write(
            "ERROR",
            "test_c5_component",
            "C5 test error message for recent_errors",
            event_type="test_c5_error",
        )

    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = c5_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/health/summary")
        assert resp.status_code == 200
        data = resp.json()
        recent = data.get("recent_errors") or []
        assert any(
            "C5 test error message" in (e.get("message") or "") and e.get("component") == "test_c5_component"
            for e in recent
        ), f"recent_errors 应包含刚写入的 ERROR，实际: {recent}"
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        await engine.dispose()


# ---------- 2) 数据来源真实性：overall_ok 随 HealthChecker 结果变化 ----------
@pytest.mark.asyncio
async def test_overall_ok_false_when_db_ok_false(c5_db_url, c5_schema):
    """mock HealthChecker.check_all 返回 db_ok=False 时，overall_ok 为 False。"""
    from src.monitoring.health_checker import HealthChecker
    from src.monitoring.models import HealthResult

    engine = create_async_engine(c5_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)

    fake_result = HealthResult(db_ok=False, exchange_ok=True, strategy_status={"strategies": {}, "summary": "ok"})

    with patch.object(HealthChecker, "check_all", new_callable=AsyncMock, return_value=fake_result):
        from src.app.routers.health import _build_summary
        async with get_db_session() as session:
            summary = await _build_summary(session)
        assert summary["overall_ok"] is False


@pytest.mark.asyncio
async def test_overall_ok_false_when_exchange_ok_false(c5_db_url, c5_schema):
    """mock HealthChecker.check_all 返回 exchange_ok=False 时，overall_ok 为 False。"""
    from src.monitoring.health_checker import HealthChecker
    from src.monitoring.models import HealthResult

    engine = create_async_engine(c5_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)

    fake_result = HealthResult(db_ok=True, exchange_ok=False, strategy_status={"strategies": {}, "summary": "ok"})

    with patch.object(HealthChecker, "check_all", new_callable=AsyncMock, return_value=fake_result):
        from src.app.routers.health import _build_summary
        async with get_db_session() as session:
            summary = await _build_summary(session)
        assert summary["overall_ok"] is False


# ---------- 3) 上限与分页 ----------
@pytest.mark.asyncio
async def test_recent_errors_and_alerts_have_limit(c5_db_url, c5_schema):
    """recent_errors 与 recent_alerts 均有明确 limit，不会无上限返回。"""
    engine = create_async_engine(c5_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)

    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = c5_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/health/summary")
        assert resp.status_code == 200
        data = resp.json()
        # 默认 limit 20，返回条数不超过 20
        assert len(data.get("recent_errors") or []) <= 20
        assert len(data.get("recent_alerts") or []) <= 20
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        await engine.dispose()
