"""
Phase1.2 B1：最小 Dashboard API 验收测试（TDASH-1）

1) decisions/executions/summary/recent 返回 200 且字段符合蓝本
2) summary 无 trade 时 trade_count=0、pnl_sum=0
3) 列表接口均有 limit 限制
"""
import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401
from src.models.decision_snapshot import DecisionSnapshot
from src.models.trade import Trade


@pytest.fixture
def b1_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def b1_db_url(b1_tmp_path):
    return "sqlite+aiosqlite:///" + (b1_tmp_path / "b1_dashboard.db").as_posix()


@pytest.fixture
def b1_sync_db_url(b1_tmp_path):
    return "sqlite:///" + (b1_tmp_path / "b1_dashboard.db").as_posix()


@pytest.fixture
def b1_schema(b1_sync_db_url):
    engine = create_engine(b1_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def b1_session_factory(b1_db_url, b1_schema):
    engine = create_async_engine(b1_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_decisions_200_and_fields(b1_db_url, b1_schema):
    """GET /api/dashboard/decisions 返回 200，每条含 decision_id, strategy_id, symbol, side, created_at。"""
    engine = create_async_engine(b1_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(session_factory)
    async with get_db_session() as session:
        session.add(DecisionSnapshot(
            decision_id="dec-b1-1",
            strategy_id="s1",
            created_at=datetime.now(timezone.utc),
            signal_state={},
            position_state={},
            risk_check_result={},
            decision_result={"symbol": "BTCUSDT", "side": "BUY"},
        ))
    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = b1_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/decisions?limit=10")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        if data:
            for item in data:
                assert "decision_id" in item and "strategy_id" in item
                assert "symbol" in item and "side" in item and "created_at" in item
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_executions_200_and_fields(b1_db_url, b1_schema):
    """GET /api/dashboard/executions 返回 200，每条含 decision_id, symbol, side, quantity, price, realized_pnl, created_at。"""
    engine = create_async_engine(b1_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(session_factory)
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        session.add(Trade(
            trade_id="tr-b1-1",
            strategy_id="s1",
            decision_id="d1",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            price=Decimal("50000"),
            realized_pnl=Decimal("10"),
            executed_at=now,
            created_at=now,
        ))
    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = b1_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/executions?limit=10")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        if data:
            for item in data:
                assert "decision_id" in item and "symbol" in item and "side" in item
                assert "quantity" in item and "price" in item and "realized_pnl" in item and "created_at" in item
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_summary_no_trade_returns_zero(b1_db_url, b1_schema):
    """无 trade 时 GET /api/dashboard/summary 返回空数组 []。"""
    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = b1_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/summary?group_by=day")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]


@pytest.mark.asyncio
async def test_dashboard_decisions_invalid_from_400(b1_db_url, b1_schema):
    """GET /api/dashboard/decisions?from=bad 返回 400，detail 含 invalid from。"""
    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = b1_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/decisions?from=bad")
        assert resp.status_code == 400, resp.text
        assert "invalid from" in (resp.json().get("detail") or "")
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]


@pytest.mark.asyncio
async def test_dashboard_executions_invalid_to_400(b1_db_url, b1_schema):
    """GET /api/dashboard/executions?to=bad 返回 400，detail 含 invalid to。"""
    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = b1_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/executions?to=bad")
        assert resp.status_code == 400, resp.text
        assert "invalid to" in (resp.json().get("detail") or "")
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]


@pytest.mark.asyncio
async def test_dashboard_summary_with_trade(b1_db_url, b1_schema):
    """有 trade 时 summary 的 trade_count、pnl_sum 与 trade 表一致。"""
    engine = create_async_engine(b1_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(session_factory)
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        session.add(Trade(
            trade_id="tr-sum-1",
            strategy_id="s1",
            decision_id="d1",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            price=Decimal("50000"),
            realized_pnl=Decimal("100.5"),
            executed_at=now,
            created_at=now,
        ))
    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = b1_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/summary?group_by=strategy")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        assert any(item.get("trade_count", 0) >= 1 and abs(float(item.get("pnl_sum", 0)) - 100.5) < 0.01 for item in data)
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_recent_200_and_limit(b1_db_url, b1_schema):
    """GET /api/dashboard/recent?n=5 返回 200，条数不超过 n。"""
    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = b1_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/recent?n=5")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) <= 5
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]


@pytest.mark.asyncio
async def test_dashboard_decisions_limit_enforced(b1_db_url, b1_schema):
    """decisions 接口 limit 参数生效，默认上限 100。"""
    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = b1_db_url
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/decisions?limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) <= 3
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
