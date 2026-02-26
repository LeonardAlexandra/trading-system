"""
Phase1.2 C2：全链路追溯验收测试（TraceQueryService + HTTP）

验收点：
1) 完整链路：trace_status=COMPLETE，missing_nodes 为空，五节点均有
2) 缺 execution（及 trade）：PARTIAL，missing_nodes 含 execution/trade，返回 signal/decision/snapshot
3) 缺 decision_snapshot：PARTIAL，missing_nodes 含 decision_snapshot
4) 缺 trade：PARTIAL，missing_nodes 含 trade
5) 不存在的 signal_id/decision_id：404 或 NOT_FOUND
6) HTTP：部分存在 => 200 + TraceResult（含 trace_status）；全无 => 404
"""
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401
from src.models.dedup_signal import DedupSignal
from src.models.decision_order_map import DecisionOrderMap
from src.models.decision_snapshot import DecisionSnapshot
from src.models.trade import Trade
from src.models.decision_order_map_status import RESERVED, FILLED
from src.repositories.dedup_signal_repo import DedupSignalRepository
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
from src.schemas.trace import (
    TRACE_STATUS_COMPLETE,
    TRACE_STATUS_NOT_FOUND,
    TRACE_STATUS_PARTIAL,
    MISSING_NODE_DECISION_SNAPSHOT,
    MISSING_NODE_EXECUTION,
    MISSING_NODE_TRADE,
)
from src.services.trace_query_service import TraceQueryService


@pytest.fixture
def c2_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def c2_db_url(c2_tmp_path):
    return "sqlite+aiosqlite:///" + (c2_tmp_path / "c2_trace.db").as_posix()


@pytest.fixture
def c2_sync_db_url(c2_tmp_path):
    return "sqlite:///" + (c2_tmp_path / "c2_trace.db").as_posix()


@pytest.fixture
def c2_schema(c2_sync_db_url):
    engine = create_engine(c2_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def c2_session_factory(c2_db_url, c2_schema):
    engine = create_async_engine(c2_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


# ---------- 1) 完整链路 ----------
@pytest.mark.asyncio
async def test_trace_complete_full_chain(c2_session_factory):
    """完整链路：trace_status=COMPLETE，missing_nodes 为空，五节点均有。"""
    now = datetime.now(timezone.utc)
    signal_id = "sig-complete"
    decision_id = "dec-complete"
    async with get_db_session() as session:
        dedup_repo = DedupSignalRepository(session)
        await dedup_repo.try_insert(signal_id, now)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="strat-c2",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        await dom_repo.update_status(
            decision_id,
            FILLED,
            local_order_id="loc-1",
            exchange_order_id="ex-1",
        )
    async with get_db_session() as session:
        snap_repo = DecisionSnapshotRepository(session)
        snap = DecisionSnapshot(
            decision_id=decision_id,
            strategy_id="strat-c2",
            created_at=now,
            signal_state={"signal_id": signal_id, "symbol": "BTCUSDT"},
            position_state={},
            risk_check_result={"allowed": True},
            decision_result={"decision_id": decision_id},
        )
        await snap_repo.save(snap)
    async with get_db_session() as session:
        trade = Trade(
            trade_id="tr-complete-1",
            strategy_id="strat-c2",
            decision_id=decision_id,
            execution_id=decision_id,
            signal_id=signal_id,
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            price=Decimal("50000"),
            executed_at=now,
        )
        session.add(trade)
        await session.flush()

    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_signal_id(signal_id)
    assert result.trace_status == TRACE_STATUS_COMPLETE
    assert result.missing_nodes == []
    assert result.signal is not None and result.signal.get("signal_id") == signal_id
    assert result.decision is not None and result.decision.get("decision_id") == decision_id
    assert result.decision_snapshot is not None
    assert result.execution is not None
    assert result.trade is not None and result.trade.get("trade_id") == "tr-complete-1"


# ---------- 2) 缺 execution（及 trade）----------
@pytest.mark.asyncio
async def test_trace_partial_missing_execution_and_trade(c2_session_factory):
    """缺 execution（及 trade）：PARTIAL，missing_nodes 含 execution、trade，返回 signal/decision/snapshot。"""
    now = datetime.now(timezone.utc)
    signal_id = "sig-no-exec"
    decision_id = "dec-no-exec"
    async with get_db_session() as session:
        dedup_repo = DedupSignalRepository(session)
        await dedup_repo.try_insert(signal_id, now)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="strat-c2",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        # 不调用 update_status，保持 RESERVED、无 order_id
    async with get_db_session() as session:
        snap_repo = DecisionSnapshotRepository(session)
        snap = DecisionSnapshot(
            decision_id=decision_id,
            strategy_id="strat-c2",
            created_at=now,
            signal_state={"signal_id": signal_id},
            position_state={},
            risk_check_result={"allowed": True},
            decision_result={"decision_id": decision_id},
        )
        await snap_repo.save(snap)

    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_signal_id(signal_id)
    assert result.trace_status == TRACE_STATUS_PARTIAL
    assert MISSING_NODE_EXECUTION in result.missing_nodes
    assert MISSING_NODE_TRADE in result.missing_nodes
    assert result.signal is not None
    assert result.decision is not None
    assert result.decision_snapshot is not None
    assert result.execution is None
    assert result.trade is None


# ---------- 3) 缺 decision_snapshot ----------
@pytest.mark.asyncio
async def test_trace_partial_missing_decision_snapshot(c2_session_factory):
    """缺 decision_snapshot：PARTIAL，missing_nodes 含 decision_snapshot。"""
    now = datetime.now(timezone.utc)
    signal_id = "sig-no-snap"
    decision_id = "dec-no-snap"
    async with get_db_session() as session:
        dedup_repo = DedupSignalRepository(session)
        await dedup_repo.try_insert(signal_id, now)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="strat-c2",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        await dom_repo.update_status(
            decision_id,
            FILLED,
            local_order_id="loc-2",
            exchange_order_id="ex-2",
        )
    # 不写入 decision_snapshot
    async with get_db_session() as session:
        trade = Trade(
            trade_id="tr-no-snap-1",
            strategy_id="strat-c2",
            decision_id=decision_id,
            execution_id=decision_id,
            signal_id=signal_id,
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.01"),
            price=Decimal("50000"),
            executed_at=now,
        )
        session.add(trade)
        await session.flush()

    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_signal_id(signal_id)
    assert result.trace_status == TRACE_STATUS_PARTIAL
    assert MISSING_NODE_DECISION_SNAPSHOT in result.missing_nodes
    assert result.signal is not None
    assert result.decision is not None
    assert result.decision_snapshot is None
    assert result.execution is not None
    assert result.trade is not None


# ---------- 4) 缺 trade ----------
@pytest.mark.asyncio
async def test_trace_partial_missing_trade(c2_session_factory):
    """缺 trade：PARTIAL，missing_nodes 含 trade。"""
    now = datetime.now(timezone.utc)
    signal_id = "sig-no-trade"
    decision_id = "dec-no-trade"
    async with get_db_session() as session:
        dedup_repo = DedupSignalRepository(session)
        await dedup_repo.try_insert(signal_id, now)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="strat-c2",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
        await dom_repo.update_status(
            decision_id,
            FILLED,
            local_order_id="loc-3",
            exchange_order_id="ex-3",
        )
    async with get_db_session() as session:
        snap_repo = DecisionSnapshotRepository(session)
        snap = DecisionSnapshot(
            decision_id=decision_id,
            strategy_id="strat-c2",
            created_at=now,
            signal_state={"signal_id": signal_id},
            position_state={},
            risk_check_result={"allowed": True},
            decision_result={"decision_id": decision_id},
        )
        await snap_repo.save(snap)
    # 不写入 trade

    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_signal_id(signal_id)
    assert result.trace_status == TRACE_STATUS_PARTIAL
    assert MISSING_NODE_TRADE in result.missing_nodes
    assert result.signal is not None
    assert result.decision is not None
    assert result.decision_snapshot is not None
    assert result.execution is not None
    assert result.trade is None


# ---------- 5) 不存在的 signal_id / decision_id ----------
@pytest.mark.asyncio
async def test_trace_not_found_signal_id(c2_session_factory):
    """不存在的 signal_id：NOT_FOUND，不返回任何节点。"""
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_signal_id("non-existent-signal-id")
    assert result.trace_status == TRACE_STATUS_NOT_FOUND
    assert set(result.missing_nodes) == {"signal", "decision", "decision_snapshot", "execution", "trade"}
    assert result.signal is None
    assert result.decision is None
    assert result.decision_snapshot is None
    assert result.execution is None
    assert result.trade is None


@pytest.mark.asyncio
async def test_trace_not_found_decision_id(c2_session_factory):
    """不存在的 decision_id：NOT_FOUND。"""
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_decision_id("non-existent-decision-id")
    assert result.trace_status == TRACE_STATUS_NOT_FOUND
    assert result.signal is None
    assert result.decision is None


# ---------- 6) HTTP 行为 ----------
@pytest.mark.asyncio
async def test_http_trace_signal_404_when_not_found(c2_session_factory):
    """GET /api/trace/signal/{id} 查不到任何节点时返回 404。"""
    from fastapi.testclient import TestClient
    from src.app.main import create_app
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/trace/signal/non-existent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_http_trace_decision_404_when_not_found(c2_session_factory):
    """GET /api/trace/decision/{id} 查不到任何节点时返回 404。"""
    from fastapi.testclient import TestClient
    from src.app.main import create_app
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/trace/decision/non-existent-decision-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_http_trace_200_with_trace_status_when_partial(c2_session_factory, c2_db_url):
    """部分存在时返回 200，body 含 trace_status、missing_nodes、已有节点。"""
    now = datetime.now(timezone.utc)
    signal_id = "sig-http-partial"
    decision_id = "dec-http-partial"
    async with get_db_session() as session:
        dedup_repo = DedupSignalRepository(session)
        await dedup_repo.try_insert(signal_id, now)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="strat-c2",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
    # 无 snapshot、无 execution（RESERVED）、无 trade

    env_prev = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = c2_db_url
        from fastapi.testclient import TestClient
        from src.app.main import create_app
        app = create_app()
        client = TestClient(app)
        resp = client.get(f"/api/trace/signal/{signal_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "trace_status" in data
        assert data["trace_status"] == TRACE_STATUS_PARTIAL
        assert "missing_nodes" in data
        assert len(data["missing_nodes"]) > 0
        assert data.get("signal") is not None
        assert data.get("decision") is not None
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]


@pytest.mark.asyncio
async def test_list_decisions_and_get_recent_n(c2_session_factory):
    """list_decisions / list_decisions_by_time / get_recent_n 返回 DecisionSummary 列表。"""
    now = datetime.now(timezone.utc)
    start_ts = now - timedelta(seconds=1)
    end_ts = now + timedelta(seconds=1)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        for i in range(3):
            await dom_repo.create_reserved(
                decision_id=f"dec-list-{i}",
                signal_id=f"sig-{i}",
                strategy_id="strat-c2",
                symbol="BTCUSDT",
                side="BUY",
                created_at=now,
                quantity=Decimal("0.01"),
            )
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        recent = await svc.get_recent_n(2)
    assert len(recent) == 2
    assert all(hasattr(s, "decision_id") and hasattr(s, "strategy_id") for s in recent)
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        by_time = await svc.list_decisions_by_time(start_ts, end_ts, limit=10)
    assert len(by_time) >= 3
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        by_strategy = await svc.list_decisions("strat-c2", start_ts, end_ts, limit=10)
    assert len(by_strategy) >= 3


@pytest.mark.asyncio
async def test_get_trace_by_decision_id_partial(c2_session_factory):
    """按 decision_id 查询：有 decision 无 signal 时 PARTIAL，missing 含 signal。"""
    now = datetime.now(timezone.utc)
    decision_id = "dec-only-no-signal"
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=None,
            strategy_id="strat-c2",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_decision_id(decision_id)
    assert result.trace_status == TRACE_STATUS_PARTIAL
    assert "signal" in result.missing_nodes
    assert result.decision is not None
    assert result.decision.get("decision_id") == decision_id
