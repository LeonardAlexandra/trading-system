"""
Phase1.2 C8：list_traces 与 PARTIAL 场景验收

- list_traces 支持时间范围、strategy_id、分页
- 每条含 trace_status；PARTIAL 时 missing_nodes 非空
- 可复现 2 个 PARTIAL：缺 decision_snapshot、缺 trade（及 execution）
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
from src.models.decision_order_map import DecisionOrderMap
from src.models.decision_snapshot import DecisionSnapshot
from src.models.trade import Trade
from src.models.log_entry import LogEntry
from src.repositories.dedup_signal_repo import DedupSignalRepository
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
from src.schemas.trace import TRACE_STATUS_PARTIAL, MISSING_NODE_DECISION_SNAPSHOT, MISSING_NODE_TRADE
from src.services import audit_service
from src.repositories.log_repository import LogRepository


@pytest.fixture
def c8_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def c8_db_url(c8_tmp_path):
    return "sqlite+aiosqlite:///" + (c8_tmp_path / "c8_audit.db").as_posix()


@pytest.fixture
def c8_sync_db_url(c8_tmp_path):
    return "sqlite:///" + (c8_tmp_path / "c8_audit.db").as_posix()


@pytest.fixture
def c8_schema(c8_sync_db_url):
    engine = create_engine(c8_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def c8_session_factory(c8_db_url, c8_schema):
    engine = create_async_engine(c8_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_traces_partial_missing_decision_snapshot(c8_session_factory):
    """PARTIAL 场景 1：有 decision 无 decision_snapshot → missing_nodes 含 decision_snapshot。"""
    now = datetime.now(timezone.utc)
    decision_id = "c8-dec-no-snapshot"
    signal_id = "c8-sig-1"
    async with get_db_session() as session:
        await DedupSignalRepository(session).try_insert(signal_id, now)
    async with get_db_session() as session:
        await DecisionOrderMapRepository(session).create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="strat-c8",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
    # 不写入 decision_snapshot、不写入 trade

    async with get_db_session() as session:
        items = await audit_service.list_traces(
            session,
            from_ts=now.replace(year=now.year - 1),
            to_ts=now.replace(year=now.year + 1),
            limit=10,
            offset=0,
        )
    assert len(items) >= 1
    one = next((t for t in items if t.decision_id == decision_id), None)
    assert one is not None
    assert one.trace_status == TRACE_STATUS_PARTIAL
    assert MISSING_NODE_DECISION_SNAPSHOT in one.missing_nodes
    assert one.missing_nodes


@pytest.mark.asyncio
async def test_list_traces_partial_missing_trade(c8_session_factory):
    """PARTIAL 场景 2：有 decision + snapshot，无 trade（无 execution）→ missing_nodes 含 execution、trade。"""
    now = datetime.now(timezone.utc)
    decision_id = "c8-dec-no-trade"
    signal_id = "c8-sig-2"
    async with get_db_session() as session:
        await DedupSignalRepository(session).try_insert(signal_id, now)
    async with get_db_session() as session:
        await DecisionOrderMapRepository(session).create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="strat-c8",
            symbol="ETHUSDT",
            side="SELL",
            created_at=now,
            quantity=Decimal("0.1"),
        )
    async with get_db_session() as session:
        await DecisionSnapshotRepository(session).save(
            DecisionSnapshot(
                decision_id=decision_id,
                strategy_id="strat-c8",
                created_at=now,
                signal_state={"signal_id": signal_id},
                position_state={},
                risk_check_result={"allowed": True},
                decision_result={"decision_id": decision_id},
            )
        )
    # 不写入 trade，不 update_status（无 execution）

    async with get_db_session() as session:
        items = await audit_service.list_traces(
            session,
            from_ts=now.replace(year=now.year - 1),
            to_ts=now.replace(year=now.year + 1),
            strategy_id="strat-c8",
            limit=10,
            offset=0,
        )
    assert len(items) >= 1
    one = next((t for t in items if t.decision_id == decision_id), None)
    assert one is not None
    assert one.trace_status == TRACE_STATUS_PARTIAL
    assert MISSING_NODE_TRADE in one.missing_nodes
    assert one.missing_nodes


@pytest.mark.asyncio
async def test_audit_log_query_interface_matches_log_repository(c8_session_factory):
    """C8 验收：审计日志查询界面（query_logs）结果与 LogRepository.query 一致，仅调用 LogRepository.query。"""
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        repo = LogRepository(session)
        await repo.write("AUDIT", "c8-test", "audit-msg-1", event_type="c8_audit")
        await repo.write("ERROR", "c8-test", "error-msg-1", event_type="c8_error")
        await repo.write("INFO", "other-component", "info-msg", event_type="c8_info")
        await session.commit()

    from_ts = now.replace(year=now.year - 1)
    to_ts = now.replace(year=now.year + 1)

    async with get_db_session() as session:
        direct = await LogRepository(session).query(
            created_at_from=from_ts,
            created_at_to=to_ts,
            component="c8-test",
            level="AUDIT",
            limit=100,
            offset=0,
        )
    async with get_db_session() as session:
        via_interface = await audit_service.query_logs(
            session,
            created_at_from=from_ts,
            created_at_to=to_ts,
            component="c8-test",
            level="AUDIT",
            limit=100,
            offset=0,
        )

    direct_ids = {e.id for e in direct}
    interface_ids = {e["id"] for e in via_interface}
    assert direct_ids == interface_ids, "审计界面筛选结果与 LogRepository.query 一致"
    assert len([e for e in direct if e.level == "AUDIT" and e.component == "c8-test"]) >= 1


# ---------- C8-R1：错误码 400/404/500 ----------


@pytest.mark.asyncio
async def test_audit_traces_400_param_error(c8_db_url, c8_schema, c8_session_factory):
    """C8-R1：参数错误 → HTTP 400，body 含 error_code=INVALID_PARAMS 与 message。"""
    import os
    from fastapi.testclient import TestClient

    os.environ["DATABASE_URL"] = c8_db_url
    from src.app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        # 缺少 to
        r1 = client.get("/api/audit/traces?from=2024-01-01T00:00:00")
        assert r1.status_code == 400, r1.text
        body1 = r1.json()
        assert body1.get("error_code") == "INVALID_PARAMS"
        assert "message" in body1

        # from > to
        r2 = client.get(
            "/api/audit/traces?from=2024-01-02T00:00:00&to=2024-01-01T00:00:00"
        )
        assert r2.status_code == 400, r2.text
        assert r2.json().get("error_code") == "INVALID_PARAMS"

        # 无效 datetime
        r3 = client.get("/api/audit/traces?from=not-a-date&to=2024-01-02T00:00:00")
        assert r3.status_code == 400, r3.text
        assert r3.json().get("error_code") == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_audit_traces_500_service_exception(c8_db_url, c8_schema, c8_session_factory):
    """C8-R1：服务异常 → HTTP 500，body 含 error_code=INTERNAL_ERROR；通过 monkeypatch 注入 list_traces 抛异常。"""
    import os
    from unittest.mock import AsyncMock, patch
    from fastapi.testclient import TestClient

    os.environ["DATABASE_URL"] = c8_db_url
    from src.app.main import create_app
    app = create_app()
    with patch("src.app.routers.audit.audit_service.list_traces", new_callable=AsyncMock) as m:
        m.side_effect = RuntimeError("C8-R1 injected service failure")
        with TestClient(app) as client:
            resp = client.get(
                "/api/audit/traces?from=2024-01-01T00:00:00&to=2024-01-02T00:00:00"
            )
        assert resp.status_code == 500, resp.text
        body = resp.json()
        assert body.get("error_code") == "INTERNAL_ERROR"
        assert "message" in body
        assert "Internal server error" in body.get("message", "")
