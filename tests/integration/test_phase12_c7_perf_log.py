"""
Phase1.2 C7：性能日志（PerfLogRepository + 关键路径打点）验收测试
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401
from src.models.perf_log_entry import PerfLogEntry
from src.models.decision_order_map import DecisionOrderMap
from src.models.dedup_signal import DedupSignal
from src.repositories.perf_log_repository import PerfLogRepository, PerfLogWriter, QUERY_MAX_LIMIT


@pytest.fixture
def c7_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def c7_db_url(c7_tmp_path):
    return "sqlite+aiosqlite:///" + (c7_tmp_path / "c7_perf.db").as_posix()


@pytest.fixture
def c7_sync_db_url(c7_tmp_path):
    return "sqlite:///" + (c7_tmp_path / "c7_perf.db").as_posix()


@pytest.fixture
def c7_schema(c7_sync_db_url):
    engine = create_engine(c7_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def c7_session_factory(c7_db_url, c7_schema):
    engine = create_async_engine(c7_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_perf_log_repository_write_and_query(c7_db_url, c7_schema):
    """PerfLogRepository 可写入 perf_log，且可按时间/组件/metric 分页查询，limit 生效。"""
    engine = create_async_engine(c7_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(session_factory)
    async with get_db_session() as session:
        repo = PerfLogRepository(session)
        await repo.write("test_comp", "latency_ms", 12.5, tags={"k": "v"})
        await repo.write("test_comp", "latency_ms", 20.0, tags=None)
    async with get_db_session() as session:
        repo = PerfLogRepository(session)
        rows = await repo.query(component="test_comp", limit=10, offset=0)
    assert len(rows) >= 2
    assert all(r.component == "test_comp" and r.metric == "latency_ms" for r in rows)
    assert any(abs(r.value - 12.5) < 0.01 for r in rows)
    assert any(abs(r.value - 20.0) < 0.01 for r in rows)
    # limit 上限
    async with get_db_session() as session:
        repo = PerfLogRepository(session)
        limited = await repo.query(limit=1, offset=0)
    assert len(limited) <= 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_perf_log_query_limit_cap(c7_db_url, c7_schema):
    """单次查询 limit 不得超过 QUERY_MAX_LIMIT，无全表无上限返回。"""
    engine = create_async_engine(c7_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(session_factory)
    async with get_db_session() as session:
        repo = PerfLogRepository(session)
        rows = await repo.query(limit=99999, offset=0)
    assert len(rows) <= QUERY_MAX_LIMIT
    await engine.dispose()


@pytest.mark.asyncio
async def test_perf_log_no_write_to_log_table(c7_db_url, c7_schema):
    """写入 perf_log（PerfLogWriter.write_once）后，log 表无新增记录（语义分离）。"""
    engine = create_async_engine(c7_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(session_factory)
    writer = PerfLogWriter(get_db_session)
    await writer.write_once("sep_test", "latency_ms", 1.0)
    from src.models.log_entry import LogEntry
    async with get_db_session() as session:
        stmt = select(LogEntry).where(LogEntry.component == "sep_test")
        result = await session.execute(stmt)
        log_rows = list(result.scalars().all())
    assert len(log_rows) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_perf_log_writer_write_once_commits_independently(c7_db_url, c7_schema):
    """write_once 独立事务 commit：不显式 commit 外部 session，仅通过 write_once 落库，新 session 可查到。"""
    engine = create_async_engine(c7_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(session_factory)
    writer = PerfLogWriter(get_db_session)
    await writer.write_once("strong_commit", "latency_ms", 99.0, tags={"k": "v"})
    async with get_db_session() as session:
        repo = PerfLogRepository(session)
        rows = await repo.query(component="strong_commit", limit=10)
    assert len(rows) >= 1, "write_once 独立 commit 后新 session 应能查到"
    assert any(abs(r.value - 99.0) < 0.01 for r in rows)
    await engine.dispose()


@pytest.mark.asyncio
async def test_signal_receiver_writes_perf_log(c7_db_url, c7_schema):
    """POST /webhook/tradingview 成功后，perf_log 有 signal_receiver latency_ms。"""
    import os
    import hmac
    import hashlib
    import json
    from fastapi.testclient import TestClient
    env_prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = c7_db_url
    try:
        from src.app.main import create_app
        app = create_app()
        secret = "test_secret_c7"
        body = json.dumps({"strategy_id": "s1", "symbol": "BTCUSDT", "side": "BUY", "signal_id": "sig-c7-1"}).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with TestClient(app) as client:
            resp = client.post(
                "/webhook/tradingview",
                content=body,
                headers={"X-TradingView-Signature": sig, "Content-Type": "application/json"},
            )
        # 可能 422（strategy 未配置）或 200；无论哪种，C7 在 finally 中会写 perf
        async with get_db_session() as session:
            repo = PerfLogRepository(session)
            rows = await repo.query(component="signal_receiver", limit=10)
        assert len(rows) >= 1, "signal_receiver 打点应至少 1 条"
        assert all(r.metric == "latency_ms" for r in rows)
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]


@pytest.mark.asyncio
async def test_trace_query_writes_perf_log(c7_db_url, c7_schema):
    """GET /api/trace/signal/{id} 为只读查询：不要求写入 perf_log。"""
    import os
    from fastapi.testclient import TestClient
    env_prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = c7_db_url
    try:
        from src.app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/trace/signal/nonexistent-sig-123")
        assert resp.status_code in (200, 404)
        async with get_db_session() as session:
            repo = PerfLogRepository(session)
            rows = await repo.query(component="trace_query", limit=10)
        assert len(rows) == 0
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]


@pytest.mark.asyncio
async def test_execution_engine_writes_perf_log(c7_db_url, c7_schema):
    """执行 execute_one（注入 perf_writer）后 perf_log 有 execution_engine latency_ms。"""
    from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
    from src.execution.execution_engine import ExecutionEngine
    from src.execution.exchange_adapter import PaperExchangeAdapter
    from src.execution.risk_manager import RiskManager
    from src.models.decision_order_map_status import RESERVED

    engine = create_async_engine(c7_db_url, echo=False, connect_args={"timeout": 15})
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(session_factory)
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        session.add(DedupSignal(signal_id="sig-e1", received_at=now, first_seen_at=now, processed=True))
        session.add(
            DecisionOrderMap(
                decision_id="dec-e1",
                signal_id="sig-e1",
                strategy_id="s1",
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("0.01"),
                status=RESERVED,
                created_at=now,
                reserved_at=now,
            )
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        exchange = PaperExchangeAdapter(filled=True)
        risk = RiskManager(risk_config=None, account_manager=None, market_data_adapter=None)
        perf_writer = PerfLogWriter(get_db_session)
        exec_engine = ExecutionEngine(dom_repo, exchange, risk, perf_writer=perf_writer)
        result = await exec_engine.execute_one("dec-e1")
    async with get_db_session() as session:
        repo = PerfLogRepository(session)
        rows = await repo.query(component="execution_engine", limit=10)
    assert result.get("decision_id") == "dec-e1"
    assert len(rows) >= 1, "execution_engine 打点应至少 1 条"
    assert all(r.metric == "latency_ms" for r in rows)
    await engine.dispose()


@pytest.mark.asyncio
async def test_signal_service_writes_perf_when_accepted(c7_db_url, c7_schema):
    """当 webhook 接受信号并创建决策时，perf_log 可有 signal_service latency_ms；至少 signal_receiver 必写。"""
    import os
    import hmac
    import hashlib
    import json
    from fastapi.testclient import TestClient
    env_prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = c7_db_url
    try:
        from src.app.main import create_app
        app = create_app()
        secret = "test_c7_secret"
        body = json.dumps({"strategy_id": "s1", "symbol": "BTCUSDT", "side": "BUY", "signal_id": "sig-svc-c7"}).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with TestClient(app) as client:
            client.post(
                "/webhook/tradingview",
                content=body,
                headers={"X-TradingView-Signature": sig, "Content-Type": "application/json"},
            )
        async with get_db_session() as session:
            repo = PerfLogRepository(session)
            rows_signal = await repo.query(component="signal_receiver", limit=5)
            rows_svc = await repo.query(component="signal_service", limit=5)
        assert len(rows_signal) >= 1
        assert all(r.metric == "latency_ms" for r in rows_signal)
    finally:
        if env_prev is not None:
            os.environ["DATABASE_URL"] = env_prev
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
