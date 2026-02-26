import os
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.app.main import create_app
from src.database.connection import Base, get_engine
from src.models.dedup_signal import DedupSignal
from src.models.decision_order_map import DecisionOrderMap
from src.models.decision_order_map_status import FAILED, FILLED, RESERVED
from src.models.decision_snapshot import DecisionSnapshot
from src.models.execution_event import ExecutionEvent
from src.models.log_entry import LogEntry
from src.models.trade import Trade
from src.schemas.trace import (
    MISSING_NODE_DECISION_SNAPSHOT,
    MISSING_NODE_EXECUTION,
    MISSING_NODE_TRADE,
    TRACE_STATUS_FAILED,
    TRACE_STATUS_NOT_FOUND,
    TRACE_STATUS_PARTIAL,
)
import src.models  # noqa: F401


def _dt() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def d5_db_urls(tmp_path):
    db_path = tmp_path / "d5_trace_integrity.db"
    return {
        "async": "sqlite+aiosqlite:///" + db_path.as_posix(),
        "sync": "sqlite:///" + db_path.as_posix(),
    }


@pytest.fixture
def d5_schema(d5_db_urls):
    engine = create_engine(d5_db_urls["sync"])
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def d5_seed_session_factory(d5_db_urls, d5_schema):
    engine = create_async_engine(d5_db_urls["async"], echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _phase12_counts(session: AsyncSession) -> dict[str, int]:
    return {
        "dedup_signal": int((await session.execute(select(func.count()).select_from(DedupSignal))).scalar() or 0),
        "decision_order_map": int((await session.execute(select(func.count()).select_from(DecisionOrderMap))).scalar() or 0),
        "decision_snapshot": int((await session.execute(select(func.count()).select_from(DecisionSnapshot))).scalar() or 0),
        "trade": int((await session.execute(select(func.count()).select_from(Trade))).scalar() or 0),
        "execution_events": int((await session.execute(select(func.count()).select_from(ExecutionEvent))).scalar() or 0),
        "log": int((await session.execute(select(func.count()).select_from(LogEntry))).scalar() or 0),
    }


@pytest.mark.asyncio
async def test_e2e_phase2_trace_integrity(monkeypatch, d5_db_urls, d5_seed_session_factory):
    # 使用独立测试 DB 启动 app
    monkeypatch.setenv("DATABASE_URL", d5_db_urls["async"])
    monkeypatch.setenv("TV_WEBHOOK_SECRET", "d5_trace_secret")
    monkeypatch.setenv("STRATEGY_ID", "D5_TRACE_STRAT")

    # 预置场景数据（Phase1.2）
    async with d5_seed_session_factory() as session:
        now = _dt()
        # 1) 有 decision 无 execution（含 snapshot）
        s1 = "d5-sig-no-exec"
        d1 = "d5-dec-no-exec"
        session.add(DedupSignal(signal_id=s1, first_seen_at=now, received_at=now, processed=False))
        session.add(
            DecisionOrderMap(
                decision_id=d1,
                signal_id=s1,
                strategy_id="D5_TRACE_STRAT",
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("0.01"),
                status=RESERVED,
                created_at=now,
            )
        )
        session.add(
            DecisionSnapshot(
                decision_id=d1,
                strategy_id="D5_TRACE_STRAT",
                created_at=now,
                signal_state={"signal_id": s1},
                position_state={},
                risk_check_result={"allowed": True},
                decision_result={"status": "reserved"},
            )
        )

        # 2) 有 decision 无 decision_snapshot
        s2 = "d5-sig-no-snapshot"
        d2 = "d5-dec-no-snapshot"
        session.add(DedupSignal(signal_id=s2, first_seen_at=now, received_at=now, processed=False))
        session.add(
            DecisionOrderMap(
                decision_id=d2,
                signal_id=s2,
                strategy_id="D5_TRACE_STRAT",
                symbol="ETHUSDT",
                side="SELL",
                quantity=Decimal("0.10"),
                status=RESERVED,
                created_at=now,
            )
        )

        # 3) 有 execution 无 trade（含 snapshot）
        s3 = "d5-sig-exec-no-trade"
        d3 = "d5-dec-exec-no-trade"
        session.add(DedupSignal(signal_id=s3, first_seen_at=now, received_at=now, processed=False))
        session.add(
            DecisionOrderMap(
                decision_id=d3,
                signal_id=s3,
                strategy_id="D5_TRACE_STRAT",
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("0.02"),
                status=FILLED,
                exchange_order_id="d5-order-1",
                created_at=now,
            )
        )
        session.add(
            DecisionSnapshot(
                decision_id=d3,
                strategy_id="D5_TRACE_STRAT",
                created_at=now,
                signal_state={"signal_id": s3},
                position_state={},
                risk_check_result={"allowed": True},
                decision_result={"status": "filled"},
            )
        )

        # FAILED 场景：不得 404，需带失败原因
        s4 = "d5-sig-failed"
        d4 = "d5-dec-failed"
        session.add(DedupSignal(signal_id=s4, first_seen_at=now, received_at=now, processed=False))
        session.add(
            DecisionOrderMap(
                decision_id=d4,
                signal_id=s4,
                strategy_id="D5_TRACE_STRAT",
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("0.03"),
                status=FAILED,
                last_error="risk_gate_failed",
                created_at=now,
            )
        )
        await session.commit()
        counts_before = await _phase12_counts(session)

    print("D5_PHASE12_COUNTS_BEFORE=" + json.dumps(counts_before, ensure_ascii=False, sort_keys=True))

    app = create_app()
    with TestClient(app) as client:
        # 只读边界：Trace 调用窗口内禁止写 SQL
        write_sql: list[str] = []

        def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            sql = " ".join((statement or "").strip().split())
            lowered = sql.lower()
            if lowered.startswith("insert") or lowered.startswith("update") or lowered.startswith("delete") or lowered.startswith("replace"):
                write_sql.append(sql)

        db_engine = get_engine()
        assert db_engine is not None
        event.listen(db_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
        try:
            # 场景1：有 decision 无 execution
            r1 = client.get("/api/trace/decision/d5-dec-no-exec")
            assert r1.status_code == 200
            j1 = r1.json()
            print("D5_RESPONSE_SC1=" + json.dumps(j1, ensure_ascii=False, sort_keys=True))
            assert j1["trace_status"] == TRACE_STATUS_PARTIAL
            assert MISSING_NODE_EXECUTION in (j1.get("missing_nodes") or [])
            assert MISSING_NODE_TRADE in (j1.get("missing_nodes") or [])
            assert j1.get("decision") is not None
            assert j1.get("decision_snapshot") is not None

            # 场景2：有 decision 无 decision_snapshot
            r2 = client.get("/api/trace/decision/d5-dec-no-snapshot")
            assert r2.status_code == 200
            j2 = r2.json()
            print("D5_RESPONSE_SC2=" + json.dumps(j2, ensure_ascii=False, sort_keys=True))
            assert j2["trace_status"] == TRACE_STATUS_PARTIAL
            assert MISSING_NODE_DECISION_SNAPSHOT in (j2.get("missing_nodes") or [])

            # 场景3：有 execution 无 trade
            r3 = client.get("/api/trace/decision/d5-dec-exec-no-trade")
            assert r3.status_code == 200
            j3 = r3.json()
            print("D5_RESPONSE_SC3=" + json.dumps(j3, ensure_ascii=False, sort_keys=True))
            assert j3["trace_status"] == TRACE_STATUS_PARTIAL
            assert MISSING_NODE_TRADE in (j3.get("missing_nodes") or [])
            assert j3.get("execution") is not None

            # 场景4：不存在 signal_id
            r4 = client.get("/api/trace/signal/d5-sig-not-exist")
            if r4.status_code == 404:
                print("D5_RESPONSE_SC4=HTTP_404")
            else:
                assert r4.status_code == 200
                j4 = r4.json()
                print("D5_RESPONSE_SC4=" + json.dumps(j4, ensure_ascii=False, sort_keys=True))
                assert j4["trace_status"] == TRACE_STATUS_NOT_FOUND
                assert j4.get("signal") is None
                assert j4.get("decision") is None

            # FAILED 场景：可查，不得 404
            rf = client.get("/api/trace/decision/d5-dec-failed")
            assert rf.status_code == 200
            jf = rf.json()
            print("D5_RESPONSE_FAILED=" + json.dumps(jf, ensure_ascii=False, sort_keys=True))
            assert jf["trace_status"] == TRACE_STATUS_FAILED
            assert jf["trace_status"] != TRACE_STATUS_NOT_FOUND
            assert "missing_reason" in jf and "failed_reason" in (jf.get("missing_reason") or {})
        finally:
            event.remove(db_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)

    print(f"D5_TRACE_WRITE_SQL_COUNT={len(write_sql)}")
    assert len(write_sql) == 0

    async with d5_seed_session_factory() as session:
        counts_after = await _phase12_counts(session)
    print("D5_PHASE12_COUNTS_AFTER=" + json.dumps(counts_after, ensure_ascii=False, sort_keys=True))
    assert counts_after == counts_before
