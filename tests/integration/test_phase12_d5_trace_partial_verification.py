"""
Phase1.2 D5：E2E-5 链路缺失可验证点

验证有 decision 无 execution、有 decision 无 decision_snapshot、有 execution 无 trade、
signal_id 不存在等场景下，get_trace 响应符合 B.2（200、trace_status=PARTIAL 或 NOT_FOUND、
missing_nodes 正确、body 含已存在节点）。
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401
from src.models.dedup_signal import DedupSignal
from src.models.decision_order_map import DecisionOrderMap
from src.models.decision_snapshot import DecisionSnapshot
from src.repositories.dedup_signal_repo import DedupSignalRepository
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
from src.schemas.trace import (
    MISSING_NODE_DECISION_SNAPSHOT,
    MISSING_NODE_EXECUTION,
    MISSING_NODE_TRADE,
    TRACE_STATUS_NOT_FOUND,
    TRACE_STATUS_PARTIAL,
)


@pytest.fixture
def d5_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def d5_db_url(d5_tmp_path):
    return "sqlite+aiosqlite:///" + (d5_tmp_path / "d5_trace.db").as_posix()


@pytest.fixture
def d5_sync_db_url(d5_tmp_path):
    return "sqlite:///" + (d5_tmp_path / "d5_trace.db").as_posix()


@pytest.fixture
def d5_schema(d5_sync_db_url):
    engine = create_engine(d5_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
def d5_config_path(d5_tmp_path, d5_db_url):
    path = d5_tmp_path / "d5_config.yaml"
    path.write_text(
        f"""
database:
  url: "{d5_db_url}"
tradingview:
  webhook_secret: "d5_secret"
strategy:
  strategy_id: "D5_STRAT"
exchange:
  name: binance
  sandbox: true
  api_key: ""
  api_secret: ""
product_type: spot
risk:
  max_single_trade_risk: 0.01
  max_account_risk: 0.05
logging:
  level: INFO
  database: false
execution:
  poll_interval_seconds: 1
  batch_size: 10
  max_concurrency: 5
  max_attempts: 3
  backoff_seconds: [1, 5, 30]
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
async def d5_session_factory(d5_db_url, d5_schema):
    engine = create_async_engine(d5_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.fixture
def d5_app(monkeypatch, d5_db_url, d5_config_path, d5_schema):
    monkeypatch.setenv("DATABASE_URL", d5_db_url)
    monkeypatch.setenv("CONFIG_PATH", str(d5_config_path))
    from src.app.main import create_app
    return create_app()


@pytest.fixture
def d5_client(d5_app):
    with TestClient(d5_app) as client:
        yield client


@pytest.mark.asyncio
async def test_d5_decision_no_execution_partial_body_has_signal_decision_snapshot(
    d5_session_factory, d5_client
):
    """
    D5：构造「有 decision 无 execution」→ get_trace 返回 200，trace_status=PARTIAL，
    missing_nodes 含 execution、trade，body 含 signal/decision/snapshot。
    """
    now = datetime.now(timezone.utc)
    decision_id = "d5-dec-no-exec"
    signal_id = "d5-sig-no-exec"
    async with get_db_session() as session:
        await DedupSignalRepository(session).try_insert(signal_id, now)
    async with get_db_session() as session:
        await DecisionOrderMapRepository(session).create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="D5_STRAT",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
    async with get_db_session() as session:
        await DecisionSnapshotRepository(session).save(
            DecisionSnapshot(
                decision_id=decision_id,
                strategy_id="D5_STRAT",
                created_at=now,
                signal_state={"signal_id": signal_id},
                position_state={},
                risk_check_result={"allowed": True},
                decision_result={"symbol": "BTCUSDT", "side": "BUY"},
            )
        )
    # 不写入 execution（不更新 order_id/status）、不写入 trade

    d5_client.get("/healthz")
    resp = d5_client.get(f"/api/trace/decision/{decision_id}")
    assert resp.status_code == 200, f"有 decision 无 execution 时应返回 200，实际 {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("trace_status") == TRACE_STATUS_PARTIAL, (
        f"trace_status 应为 PARTIAL，实际 {data.get('trace_status')!r}"
    )
    missing = data.get("missing_nodes") or []
    assert MISSING_NODE_EXECUTION in missing, f"missing_nodes 应含 execution，实际 {missing}"
    assert MISSING_NODE_TRADE in missing, f"missing_nodes 应含 trade，实际 {missing}"
    assert data.get("signal") is not None, "body 应含 signal"
    assert data.get("decision") is not None, "body 应含 decision"
    assert data.get("decision_snapshot") is not None, "body 应含 decision_snapshot"


@pytest.mark.asyncio
async def test_d5_decision_no_snapshot_partial_missing_decision_snapshot(
    d5_session_factory, d5_client
):
    """
    D5：构造「有 decision 无 decision_snapshot」→ trace_status=PARTIAL，missing_nodes 含 decision_snapshot。
    """
    now = datetime.now(timezone.utc)
    decision_id = "d5-dec-no-snap"
    signal_id = "d5-sig-no-snap"
    async with get_db_session() as session:
        await DedupSignalRepository(session).try_insert(signal_id, now)
    async with get_db_session() as session:
        await DecisionOrderMapRepository(session).create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="D5_STRAT",
            symbol="ETHUSDT",
            side="SELL",
            created_at=now,
            quantity=Decimal("0.1"),
        )
    # 不写入 decision_snapshot

    d5_client.get("/healthz")
    resp = d5_client.get(f"/api/trace/decision/{decision_id}")
    assert resp.status_code == 200, f"有 decision 无 snapshot 时应返回 200，实际 {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("trace_status") == TRACE_STATUS_PARTIAL
    missing = data.get("missing_nodes") or []
    assert MISSING_NODE_DECISION_SNAPSHOT in missing, (
        f"missing_nodes 应含 decision_snapshot，实际 {missing}"
    )


@pytest.mark.asyncio
async def test_d5_execution_no_trade_partial_missing_trade(d5_session_factory, d5_client):
    """
    D5：构造「有 execution 无 trade」→ trace_status=PARTIAL，missing_nodes 含 trade。
    """
    now = datetime.now(timezone.utc)
    decision_id = "d5-dec-exec-no-trade"
    signal_id = "d5-sig-exec-no-trade"
    async with get_db_session() as session:
        await DedupSignalRepository(session).try_insert(signal_id, now)
    async with get_db_session() as session:
        await DecisionOrderMapRepository(session).create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="D5_STRAT",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
    async with get_db_session() as session:
        await DecisionSnapshotRepository(session).save(
            DecisionSnapshot(
                decision_id=decision_id,
                strategy_id="D5_STRAT",
                created_at=now,
                signal_state={"signal_id": signal_id},
                position_state={},
                risk_check_result={"allowed": True},
                decision_result={"symbol": "BTCUSDT", "side": "BUY"},
            )
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        row = await dom_repo.get_by_decision_id(decision_id)
        assert row is not None
        row.exchange_order_id = "d5-ex-order-1"
        row.status = "FILLED"
        await session.flush()
    # 不写入 trade 表

    d5_client.get("/healthz")
    resp = d5_client.get(f"/api/trace/decision/{decision_id}")
    assert resp.status_code == 200, f"有 execution 无 trade 时应返回 200，实际 {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("trace_status") == TRACE_STATUS_PARTIAL
    missing = data.get("missing_nodes") or []
    assert MISSING_NODE_TRADE in missing, f"missing_nodes 应含 trade，实际 {missing}"


@pytest.mark.asyncio
async def test_d5_nonexistent_signal_id_404_or_not_found(d5_session_factory, d5_client):
    """
    D5：不存在的 signal_id → 返回 404 或 200 + trace_status=NOT_FOUND，并无节点。
    """
    d5_client.get("/healthz")
    resp = d5_client.get("/api/trace/signal/d5-nonexistent-signal-id-xyz")
    if resp.status_code == 404:
        return
    assert resp.status_code == 200, f"允许 404 或 200，实际 {resp.status_code}"
    data = resp.json()
    assert data.get("trace_status") == TRACE_STATUS_NOT_FOUND, (
        f"200 时 trace_status 应为 NOT_FOUND，实际 {data.get('trace_status')!r}"
    )
    assert data.get("signal") is None and data.get("decision") is None, (
        "NOT_FOUND 时 body 应无节点或无有效节点"
    )


@pytest.mark.asyncio
async def test_d5_partial_not_404_and_has_trace_status_missing_nodes(d5_session_factory, d5_client):
    """
    D5：禁止部分数据存在时返回 404 或 body 为空且无 trace_status、missing_nodes。
    有 decision 无 snapshot 时必返回 200 + PARTIAL + missing_nodes。
    """
    now = datetime.now(timezone.utc)
    decision_id = "d5-dec-partial-check"
    signal_id = "d5-sig-partial-check"
    async with get_db_session() as session:
        await DedupSignalRepository(session).try_insert(signal_id, now)
    async with get_db_session() as session:
        await DecisionOrderMapRepository(session).create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="D5_STRAT",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )

    d5_client.get("/healthz")
    resp = d5_client.get(f"/api/trace/decision/{decision_id}")
    assert resp.status_code != 404, "部分数据存在（有 decision）时不得返回 404"
    assert resp.status_code == 200
    data = resp.json()
    assert "trace_status" in data, "body 必须含 trace_status"
    assert "missing_nodes" in data, "body 必须含 missing_nodes"
    assert data["trace_status"] == TRACE_STATUS_PARTIAL
    assert isinstance(data["missing_nodes"], list) and len(data["missing_nodes"]) > 0
