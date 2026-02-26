# Phase2.0 D5 证据包（E2E-2.0 Trace 链路完整性验证）

## 修改文件清单
- 新增：`tests/e2e/test_e2e_phase2_trace_integrity.py`
- 新增：`docs/runlogs/phase20_d5_pytest_output.txt`
- 新增：`docs/runlogs/phase20_d5_pytest_output_with_markers.txt`
- 新增：`docs/Phase2.0_D5_证据包.md`

## Trace API 关键代码
### src/app/routers/trace.py
```python
"""
Phase1.2 C2：全链路追溯 HTTP 路由（蓝本 D.2 写死）
C7：Trace 查询打点 latency_ms。
"""
import time

from fastapi import APIRouter, Response

from src.app.dependencies import get_db_session
from src.repositories.perf_log_repository import PerfLogWriter
from src.schemas.trace import TRACE_STATUS_NOT_FOUND, TRACE_STATUS_FAILED
from src.services.trace_query_service import TraceQueryService

router = APIRouter(prefix="/api/trace", tags=["trace"])


@router.get("/signal/{signal_id}")
async def get_trace_by_signal(signal_id: str):
    """
    按 signal_id 查询全链路追溯结果。
    查不到任何节点返回 404；查到部分或全部返回 200，body 为 TraceResult。
    """
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_signal_id(signal_id)
    
    if result.trace_status == TRACE_STATUS_NOT_FOUND:
        return Response(content="", status_code=404)
    # AC-D2-TRACE-404-01: FAILED decision 必须返回 200 而非 404
    return result.to_dict()


@router.get("/decision/{decision_id}")
async def get_trace_by_decision(decision_id: str):
    """
    按 decision_id 查询全链路追溯结果。
    查不到任何节点返回 404；查到部分或全部返回 200，body 为 TraceResult。
    """
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_decision_id(decision_id)
    
    if result.trace_status == TRACE_STATUS_NOT_FOUND:
        return Response(content="", status_code=404)
    # AC-D2-TRACE-404-01: FAILED decision 必须返回 200 而非 404
    return result.to_dict()
```

### src/services/trace_query_service.py（status/missing_nodes/FAILED 相关核心片段）
```python
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._dedup_repo = DedupSignalRepository(session)
        self._dom_repo = DecisionOrderMapRepository(session)
        self._snapshot_repo = DecisionSnapshotRepository(session)

    async def get_trace_by_signal_id(self, signal_id: str) -> TraceResult:
        """
        按 signal_id 聚合整条链路。
        查不到任何节点时返回 NOT_FOUND；部分存在时返回 PARTIAL + 已存在节点 + missing_nodes。
        """
        missing: List[str] = []
        signal_data: Optional[Dict[str, Any]] = None
        decision_row: Optional[DecisionOrderMap] = None
        snapshot_row: Optional[DecisionSnapshot] = None
        trade_row: Optional[Trade] = None

        # 1. signal
        signal = await self._dedup_repo.get(signal_id)
        if signal is None:
            return TraceResult(
                trace_status=TRACE_STATUS_NOT_FOUND,
                missing_nodes=ALL_MISSING_NODES.copy(),
                signal=None,
                decision=None,
                decision_snapshot=None,
                execution=None,
                trade=None,
            )
        signal_data = _signal_to_dict(signal)

        # 2. decision (by signal_id)
        stmt_dom = select(DecisionOrderMap).where(DecisionOrderMap.signal_id == signal_id).limit(1)
        result = await self.session.execute(stmt_dom)
        decision_row = result.scalar_one_or_none()
        if decision_row is None:
            missing.extend([MISSING_NODE_DECISION, MISSING_NODE_DECISION_SNAPSHOT, MISSING_NODE_EXECUTION, MISSING_NODE_TRADE])
            return TraceResult(
                trace_status=TRACE_STATUS_PARTIAL,
                missing_nodes=missing,
                signal=signal_data,
                decision=None,
                decision_snapshot=None,
                execution=None,
                trade=None,
            )

        decision_id = decision_row.decision_id
        decision_data = _decision_to_dict(decision_row)
        signal_data = _signal_to_dict(signal, decision_row)

        # 3. decision_snapshot
        snapshot_row = await self._snapshot_repo.get_by_decision_id(decision_id)
        if snapshot_row is None:
            missing.append(MISSING_NODE_DECISION_SNAPSHOT)

        # 4. execution（来自同一 decision_order_map 行；蓝本：有 decision 无 execution 时 missing 含 execution）
        # 视为“有 execution”仅当已提交（非仅 RESERVED 或已有 order_id）且非 FAILED
        has_execution = (
            (decision_row.local_order_id is not None
             or decision_row.exchange_order_id is not None
             or decision_row.status != RESERVED)
            and decision_row.status != STATUS_FAILED
        )
        execution_data = _execution_to_dict(decision_row) if has_execution else None
        if not has_execution:
            missing.append(MISSING_NODE_EXECUTION)

        # 5. trade
        stmt_trade = select(Trade).where(Trade.decision_id == decision_id).limit(1)
        res_trade = await self.session.execute(stmt_trade)
        trade_row = res_trade.scalar_one_or_none()
        if trade_row is None:
            missing.append(MISSING_NODE_TRADE)

        # 判断最终状态：如果 decision 状态为 FAILED，则 trace_status 至少为 PARTIAL/FAILED
        final_status = TRACE_STATUS_COMPLETE if not missing else TRACE_STATUS_PARTIAL
        if decision_row.status == STATUS_FAILED:
            final_status = TRACE_STATUS_FAILED

        missing_reason = None
        if decision_row.status == STATUS_FAILED:
            # 兼容字段名：优先取 reason，若模型无此字段则尝试 last_error
            fail_reason_val = getattr(decision_row, 'reason', None) or getattr(decision_row, 'last_error', None)
            missing_reason = {"failed_reason": fail_reason_val or "Decision marked as FAILED"}

        return TraceResult(
            trace_status=final_status,
            missing_nodes=missing,
            missing_reason=missing_reason,
            signal=signal_data,
            decision=decision_data,
            decision_snapshot=_snapshot_to_dict(snapshot_row) if snapshot_row else None,
            execution=execution_data,
            trade=_trade_to_dict(trade_row) if trade_row else None,
        )

    async def get_trace_by_decision_id(self, decision_id: str) -> TraceResult:
        """
        按 decision_id 聚合整条链路。
        查不到 decision 即 NOT_FOUND；否则按 signal_id 拉 signal，再补 snapshot/execution/trade。
        """
        decision_row = await self._dom_repo.get_by_decision_id(decision_id)
        if decision_row is None:
            return TraceResult(
                trace_status=TRACE_STATUS_NOT_FOUND,
                missing_nodes=ALL_MISSING_NODES.copy(),
                signal=None,
                decision=None,
                decision_snapshot=None,
                execution=None,
                trade=None,
            )

        signal_id = decision_row.signal_id
        missing: List[str] = []
        signal_data: Optional[Dict[str, Any]] = None
        snapshot_row: Optional[DecisionSnapshot] = None
        trade_row: Optional[Trade] = None

        if signal_id:
            signal = await self._dedup_repo.get(signal_id)
            if signal is not None:
                signal_data = _signal_to_dict(signal, decision_row)
            else:
                missing.append(MISSING_NODE_SIGNAL)
        else:
            missing.append(MISSING_NODE_SIGNAL)

        decision_data = _decision_to_dict(decision_row)
        snapshot_row = await self._snapshot_repo.get_by_decision_id(decision_id)
        if snapshot_row is None:
            missing.append(MISSING_NODE_DECISION_SNAPSHOT)
        # 视为“有 execution”仅当已提交（非仅 RESERVED 或已有 order_id）且非 FAILED
        has_execution = (
            (decision_row.local_order_id is not None
             or decision_row.exchange_order_id is not None
             or decision_row.status != RESERVED)
            and decision_row.status != STATUS_FAILED
        )
        execution_data = _execution_to_dict(decision_row) if has_execution else None
        if not has_execution:
            missing.append(MISSING_NODE_EXECUTION)

        stmt_trade = select(Trade).where(Trade.decision_id == decision_id).limit(1)
        res_trade = await self.session.execute(stmt_trade)
        trade_row = res_trade.scalar_one_or_none()
        if trade_row is None:
            missing.append(MISSING_NODE_TRADE)

        # 判断最终状态：如果 decision 状态为 FAILED，则 trace_status 强制为 FAILED
        final_status = TRACE_STATUS_COMPLETE if not missing else TRACE_STATUS_PARTIAL
        if decision_row.status == STATUS_FAILED:
            final_status = TRACE_STATUS_FAILED

        missing_reason = None
        if decision_row.status == STATUS_FAILED:
            # 兼容字段名：优先取 reason，若模型无此字段则尝试 last_error
            fail_reason_val = getattr(decision_row, 'reason', None) or getattr(decision_row, 'last_error', None)
            missing_reason = {"failed_reason": fail_reason_val or "Decision marked as FAILED"}

        return TraceResult(
            trace_status=final_status,
            missing_nodes=missing,
            missing_reason=missing_reason,
            signal=signal_data,
            decision=decision_data,
            decision_snapshot=_snapshot_to_dict(snapshot_row) if snapshot_row else None,
            execution=execution_data,
            trade=_trade_to_dict(trade_row) if trade_row else None,
        )

    async def list_decisions(
        self,
        strategy_id: str,
        start_ts: datetime,
        end_ts: datetime,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DecisionSummary]:
        """按 strategy_id + 时间范围分页列表。"""
        stmt = (
            select(DecisionOrderMap)
            .where(
                DecisionOrderMap.strategy_id == strategy_id,
                DecisionOrderMap.created_at >= start_ts,
                DecisionOrderMap.created_at <= end_ts,
            )
            .order_by(DecisionOrderMap.created_at.desc())
            .limit(limit)
            .offset(offset)
```

## 测试代码
文件：`tests/e2e/test_e2e_phase2_trace_integrity.py`
```python
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
```

## pytest 原始输出
### 指定命令
命令：`pytest tests/e2e/test_e2e_phase2_trace_integrity.py`
来源：`docs/runlogs/phase20_d5_pytest_output.txt`
```text
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 1 item

tests/e2e/test_e2e_phase2_trace_integrity.py .                           [100%]

============================== 1 passed in 0.58s ===============================
```

### 含审计输出
命令：`pytest tests/e2e/test_e2e_phase2_trace_integrity.py -s`
来源：`docs/runlogs/phase20_d5_pytest_output_with_markers.txt`
```text
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 1 item

tests/e2e/test_e2e_phase2_trace_integrity.py D5_PHASE12_COUNTS_BEFORE={"decision_order_map": 4, "decision_snapshot": 2, "dedup_signal": 4, "execution_events": 0, "log": 0, "trade": 0}
2026-02-26 16:54:02,553 - src.app.main - INFO - Application started
2026-02-26 16:54:02,562 - httpx - INFO - HTTP Request: GET http://testserver/api/trace/decision/d5-dec-no-exec "HTTP/1.1 200 OK"
D5_RESPONSE_SC1={"decision": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-no-exec", "quantity": "0.01000000", "reason": null, "reserved_at": "2026-02-26T08:54:02", "side": "BUY", "signal_id": "d5-sig-no-exec", "status": "RESERVED", "strategy_id": "D5_TRACE_STRAT", "symbol": "BTCUSDT"}, "decision_snapshot": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-no-exec", "decision_result": {"status": "reserved"}, "id": 1, "position_state": {}, "risk_check_result": {"allowed": true}, "signal_state": {"signal_id": "d5-sig-no-exec"}, "strategy_id": "D5_TRACE_STRAT"}, "missing_nodes": ["execution", "trade"], "signal": {"action": "BUY", "created_at": "2026-02-26T08:54:02", "first_seen_at": "2026-02-26T08:54:02.532078", "processed": false, "received_at": "2026-02-26T08:54:02.532078", "signal_id": "d5-sig-no-exec", "symbol": "BTCUSDT"}, "trace_status": "PARTIAL"}
2026-02-26 16:54:02,565 - httpx - INFO - HTTP Request: GET http://testserver/api/trace/decision/d5-dec-no-snapshot "HTTP/1.1 200 OK"
D5_RESPONSE_SC2={"decision": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-no-snapshot", "quantity": "0.10000000", "reason": null, "reserved_at": "2026-02-26T08:54:02", "side": "SELL", "signal_id": "d5-sig-no-snapshot", "status": "RESERVED", "strategy_id": "D5_TRACE_STRAT", "symbol": "ETHUSDT"}, "missing_nodes": ["decision_snapshot", "execution", "trade"], "signal": {"action": "SELL", "created_at": "2026-02-26T08:54:02", "first_seen_at": "2026-02-26T08:54:02.532078", "processed": false, "received_at": "2026-02-26T08:54:02.532078", "signal_id": "d5-sig-no-snapshot", "symbol": "ETHUSDT"}, "trace_status": "PARTIAL"}
2026-02-26 16:54:02,568 - httpx - INFO - HTTP Request: GET http://testserver/api/trace/decision/d5-dec-exec-no-trade "HTTP/1.1 200 OK"
D5_RESPONSE_SC3={"decision": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-exec-no-trade", "quantity": "0.02000000", "reason": null, "reserved_at": "2026-02-26T08:54:02", "side": "BUY", "signal_id": "d5-sig-exec-no-trade", "status": "FILLED", "strategy_id": "D5_TRACE_STRAT", "symbol": "BTCUSDT"}, "decision_snapshot": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-exec-no-trade", "decision_result": {"status": "filled"}, "id": 2, "position_state": {}, "risk_check_result": {"allowed": true}, "signal_state": {"signal_id": "d5-sig-exec-no-trade"}, "strategy_id": "D5_TRACE_STRAT"}, "execution": {"decision_id": "d5-dec-exec-no-trade", "exchange_order_id": "d5-order-1", "execution_id": "d5-dec-exec-no-trade", "local_order_id": null, "order_id": "d5-order-1", "status": "FILLED", "updated_at": "2026-02-26T08:54:02"}, "missing_nodes": ["trade"], "signal": {"action": "BUY", "created_at": "2026-02-26T08:54:02", "first_seen_at": "2026-02-26T08:54:02.532078", "processed": false, "received_at": "2026-02-26T08:54:02.532078", "signal_id": "d5-sig-exec-no-trade", "symbol": "BTCUSDT"}, "trace_status": "PARTIAL"}
2026-02-26 16:54:02,570 - httpx - INFO - HTTP Request: GET http://testserver/api/trace/signal/d5-sig-not-exist "HTTP/1.1 404 Not Found"
D5_RESPONSE_SC4=HTTP_404
2026-02-26 16:54:02,573 - httpx - INFO - HTTP Request: GET http://testserver/api/trace/decision/d5-dec-failed "HTTP/1.1 200 OK"
D5_RESPONSE_FAILED={"decision": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-failed", "quantity": "0.03000000", "reason": null, "reserved_at": "2026-02-26T08:54:02", "side": "BUY", "signal_id": "d5-sig-failed", "status": "FAILED", "strategy_id": "D5_TRACE_STRAT", "symbol": "BTCUSDT"}, "missing_nodes": ["decision_snapshot", "execution", "trade"], "missing_reason": {"failed_reason": "risk_gate_failed"}, "signal": {"action": "BUY", "created_at": "2026-02-26T08:54:02", "first_seen_at": "2026-02-26T08:54:02.532078", "processed": false, "received_at": "2026-02-26T08:54:02.532078", "signal_id": "d5-sig-failed", "symbol": "BTCUSDT"}, "trace_status": "FAILED"}
2026-02-26 16:54:02,574 - src.app.main - INFO - Application shutdown
2026-02-26 16:54:02,575 - src.app.main - INFO - Database engine disposed
D5_TRACE_WRITE_SQL_COUNT=0
D5_PHASE12_COUNTS_AFTER={"decision_order_map": 4, "decision_snapshot": 2, "dedup_signal": 4, "execution_events": 0, "log": 0, "trade": 0}
.

============================== 1 passed in 0.58s ===============================
```

## 响应 JSON 示例
### 场景1（有 decision 无 execution）
```json
{"decision": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-no-exec", "quantity": "0.01000000", "reason": null, "reserved_at": "2026-02-26T08:54:02", "side": "BUY", "signal_id": "d5-sig-no-exec", "status": "RESERVED", "strategy_id": "D5_TRACE_STRAT", "symbol": "BTCUSDT"}, "decision_snapshot": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-no-exec", "decision_result": {"status": "reserved"}, "id": 1, "position_state": {}, "risk_check_result": {"allowed": true}, "signal_state": {"signal_id": "d5-sig-no-exec"}, "strategy_id": "D5_TRACE_STRAT"}, "missing_nodes": ["execution", "trade"], "signal": {"action": "BUY", "created_at": "2026-02-26T08:54:02", "first_seen_at": "2026-02-26T08:54:02.532078", "processed": false, "received_at": "2026-02-26T08:54:02.532078", "signal_id": "d5-sig-no-exec", "symbol": "BTCUSDT"}, "trace_status": "PARTIAL"}
```
### 场景2（有 decision 无 decision_snapshot）
```json
{"decision": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-no-snapshot", "quantity": "0.10000000", "reason": null, "reserved_at": "2026-02-26T08:54:02", "side": "SELL", "signal_id": "d5-sig-no-snapshot", "status": "RESERVED", "strategy_id": "D5_TRACE_STRAT", "symbol": "ETHUSDT"}, "missing_nodes": ["decision_snapshot", "execution", "trade"], "signal": {"action": "SELL", "created_at": "2026-02-26T08:54:02", "first_seen_at": "2026-02-26T08:54:02.532078", "processed": false, "received_at": "2026-02-26T08:54:02.532078", "signal_id": "d5-sig-no-snapshot", "symbol": "ETHUSDT"}, "trace_status": "PARTIAL"}
```
### 场景3（有 execution 无 trade）
```json
{"decision": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-exec-no-trade", "quantity": "0.02000000", "reason": null, "reserved_at": "2026-02-26T08:54:02", "side": "BUY", "signal_id": "d5-sig-exec-no-trade", "status": "FILLED", "strategy_id": "D5_TRACE_STRAT", "symbol": "BTCUSDT"}, "decision_snapshot": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-exec-no-trade", "decision_result": {"status": "filled"}, "id": 2, "position_state": {}, "risk_check_result": {"allowed": true}, "signal_state": {"signal_id": "d5-sig-exec-no-trade"}, "strategy_id": "D5_TRACE_STRAT"}, "execution": {"decision_id": "d5-dec-exec-no-trade", "exchange_order_id": "d5-order-1", "execution_id": "d5-dec-exec-no-trade", "local_order_id": null, "order_id": "d5-order-1", "status": "FILLED", "updated_at": "2026-02-26T08:54:02"}, "missing_nodes": ["trade"], "signal": {"action": "BUY", "created_at": "2026-02-26T08:54:02", "first_seen_at": "2026-02-26T08:54:02.532078", "processed": false, "received_at": "2026-02-26T08:54:02.532078", "signal_id": "d5-sig-exec-no-trade", "symbol": "BTCUSDT"}, "trace_status": "PARTIAL"}
```
### 场景4（不存在 signal_id）
```text
D5_RESPONSE_SC4=HTTP_404
```
### FAILED 场景
```json
{"decision": {"created_at": "2026-02-26T08:54:02.532078", "decision_id": "d5-dec-failed", "quantity": "0.03000000", "reason": null, "reserved_at": "2026-02-26T08:54:02", "side": "BUY", "signal_id": "d5-sig-failed", "status": "FAILED", "strategy_id": "D5_TRACE_STRAT", "symbol": "BTCUSDT"}, "missing_nodes": ["decision_snapshot", "execution", "trade"], "missing_reason": {"failed_reason": "risk_gate_failed"}, "signal": {"action": "BUY", "created_at": "2026-02-26T08:54:02", "first_seen_at": "2026-02-26T08:54:02.532078", "processed": false, "received_at": "2026-02-26T08:54:02.532078", "signal_id": "d5-sig-failed", "symbol": "BTCUSDT"}, "trace_status": "FAILED"}
```

## Phase1.2 表行数对比
- BEFORE
```json
```
- AFTER
```json
{"decision_order_map": 4, "decision_snapshot": 2, "dedup_signal": 4, "execution_events": 0, "log": 0, "trade": 0}
```

## 只读边界（写入拦截）
```text
D5_TRACE_WRITE_SQL_COUNT=0
```

## 与 AC 逐条对照说明
- [x] PARTIAL 状态正确（场景1/2/3 返回 PARTIAL）。
- [x] missing_nodes 正确（execution/trade、decision_snapshot、trade 分别命中）。
- [x] NOT_FOUND 语义正确（不存在 signal_id 返回 404，符合允许语义）。
- [x] FAILED 可查询（FAILED decision 返回 200，trace_status=FAILED，含 failed_reason）。
- [x] 无 404 掩盖失败（FAILED 场景明确 200）。
- [x] 无写操作（Trace 查询窗口 `D5_TRACE_WRITE_SQL_COUNT=0`）。
- [x] 响应结构符合规范（trace_status/missing_nodes + 已存在节点字段断言通过）。
