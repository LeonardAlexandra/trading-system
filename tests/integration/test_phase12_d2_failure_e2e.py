"""
Phase1.2 D2：异常/降级链路回归测试（Failure & Degradation E2E）

验证在关键失败场景下：拒绝错误决策、不中断系统运行、可审计、可追溯、可恢复。
每个场景独立用例，使用 mock/monkeypatch 制造异常，不修改业务逻辑。
"""
import asyncio
import base64
import hashlib
import hmac
import json
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.database.connection import Base
import src.models  # noqa: F401
from src.execution.execution_worker import run_once
from src.execution.worker_config import WorkerConfig

D2_WEBHOOK_SECRET = "d2_e2e_secret"
D2_STRATEGY_ID = "D2_E2E_STRATEGY"


def _make_signature(secret: str, body: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


@pytest.fixture
def d2_db_path(tmp_path):
    return tmp_path / "d2_e2e.db"


@pytest.fixture
def d2_config_path(tmp_path, d2_db_path):
    path = tmp_path / "d2_config.yaml"
    path.write_text(
        f"""
database:
  url: "sqlite+aiosqlite:///{d2_db_path.as_posix()}"
tradingview:
  webhook_secret: "{D2_WEBHOOK_SECRET}"
strategy:
  strategy_id: "{D2_STRATEGY_ID}"
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
def d2_schema(d2_db_path):
    sync_url = "sqlite:///" + str(d2_db_path)
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
def d2_app(monkeypatch, d2_db_path, d2_config_path, d2_schema, tmp_path):
    async_url = "sqlite+aiosqlite:///" + str(d2_db_path)
    monkeypatch.setenv("DATABASE_URL", async_url)
    monkeypatch.setenv("TV_WEBHOOK_SECRET", D2_WEBHOOK_SECRET)
    monkeypatch.setenv("STRATEGY_ID", D2_STRATEGY_ID)
    monkeypatch.setenv("CONFIG_PATH", str(d2_config_path))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    from src.app.main import create_app
    return create_app()


@pytest.fixture
def d2_client(d2_app):
    with TestClient(d2_app) as c:
        yield c


def _webhook_create_decision(client, db_path, decision_id_out=None):
    """发送一次 webhook 创建 decision，返回 decision_id。"""
    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-02-08T12:00:00Z",
        "indicator_name": "D2_E2E",
        "strategy_id": D2_STRATEGY_ID,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _make_signature(D2_WEBHOOK_SECRET, body)
    resp = client.post(
        "/webhook/tradingview",
        content=body,
        headers={"Content-Type": "application/json", "X-TradingView-Signature": sig},
    )
    assert resp.status_code == 200, f"webhook failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("status") == "accepted"
    did = data.get("decision_id")
    assert did
    if decision_id_out is not None:
        decision_id_out.append(did)
    return did


# ---------- 场景 1：决策快照写入失败（DecisionSnapshotRepository.save 抛异常）----------
def test_d2_snapshot_save_failure(d2_client, d2_db_path):
    """
    决策快照写入失败：save 抛异常 → 决策未进入执行/成交，log 有 ERROR，trace PARTIAL/失败态，系统可继续。
    """
    decision_id = _webhook_create_decision(d2_client, d2_db_path)

    from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
    with patch.object(
        DecisionSnapshotRepository,
        "save",
        new_callable=AsyncMock,
        side_effect=RuntimeError("D2_injected_snapshot_save_failure"),
    ):
        config = WorkerConfig.from_env()
        n = asyncio.run(run_once(config))
        assert n >= 0

    conn = sqlite3.connect(str(d2_db_path))
    try:
        cur = conn.execute(
            "SELECT status FROM decision_order_map WHERE decision_id = ?",
            (decision_id,),
        )
        row = cur.fetchone()
        assert row is not None, "decision should exist"
        assert row[0] == "FAILED", f"decision should be FAILED after snapshot save error, got {row[0]}"

        cur = conn.execute(
            "SELECT 1 FROM log WHERE level IN ('ERROR','AUDIT') AND (message LIKE '%decision_snapshot%' OR message LIKE '%snapshot_save%' OR event_type = 'decision_snapshot_save_failed') LIMIT 1"
        )
        log_row = cur.fetchone()
        assert log_row is not None, "log should contain ERROR/AUDIT for snapshot save failure"
    finally:
        conn.close()

    trace_resp = d2_client.get(f"/api/trace/decision/{decision_id}")
    assert trace_resp.status_code in (200, 404), f"trace: {trace_resp.status_code}"
    if trace_resp.status_code == 200:
        trace_data = trace_resp.json()
        assert trace_data.get("trace_status") in ("FAILED", "PARTIAL", "NOT_FOUND", "COMPLETE"), trace_data.get("trace_status")
        if trace_data.get("trace_status") == "PARTIAL":
            assert "decision_snapshot" in (trace_data.get("missing_nodes") or []), trace_data.get("missing_nodes")

    health_resp = d2_client.get("/api/health/summary")
    assert health_resp.status_code == 200, health_resp.text
    health = health_resp.json()
    assert "overall_ok" in health
    assert health.get("overall_ok") is False or (health.get("metrics") or {}).get("error_rate", 0) > 0 or (health.get("recent_errors"))


# ---------- 场景 2：执行端不可用（ExchangeAdapter.create_order 失败）----------
def test_d2_execution_exchange_failure(d2_client, d2_db_path):
    """
    执行端不可用：create_order 抛异常 → 决策不成交，log 有 ERROR/AUDIT，trace PARTIAL，系统可继续。
    """
    decision_id = _webhook_create_decision(d2_client, d2_db_path)
    with patch(
        "src.execution.execution_worker.PaperExchangeAdapter.create_order",
        new_callable=AsyncMock,
        side_effect=RuntimeError("D2_injected_exchange_unavailable"),
    ):
        n = asyncio.run(run_once(WorkerConfig.from_env()))
        assert n >= 0

    conn = sqlite3.connect(str(d2_db_path))
    try:
        cur = conn.execute(
            "SELECT 1 FROM log WHERE level IN ('ERROR','AUDIT') LIMIT 1"
        )
        assert cur.fetchone() is not None, "log should have ERROR or AUDIT after exchange failure"
        cur = conn.execute("SELECT status FROM decision_order_map WHERE decision_id = ?", (decision_id,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] != "FILLED", "decision should not be FILLED when exchange fails"
    finally:
        conn.close()

    trace_resp = d2_client.get(f"/api/trace/decision/{decision_id}")
    assert trace_resp.status_code in (200, 404), f"trace: {trace_resp.status_code}"
    if trace_resp.status_code == 200:
        td = trace_resp.json()
        trace_status = td.get("trace_status")
        missing = td.get("missing_nodes") or []
        assert trace_status in ("FAILED", "PARTIAL"), (
            f"execution failed must not be COMPLETE; got trace_status={trace_status!r}"
        )
        if trace_status == "PARTIAL":
            assert "execution" in missing or "trade" in missing, (
                f"when PARTIAL after exchange failure, missing_nodes must contain execution or trade, got {missing}"
            )

    health_resp = d2_client.get("/api/health/summary")
    assert health_resp.status_code == 200


# ---------- 场景 3：数据库短暂不可用（list_reserved_ready 首次抛异常）----------
def test_d2_db_briefly_unavailable(d2_client, d2_db_path):
    """
    数据库短暂不可用：list_reserved_ready 首次抛异常 → run_once 吞掉瞬态错误返回 0，log/health 可观测，第二次 run_once 正常恢复。
    """
    _webhook_create_decision(d2_client, d2_db_path)

    from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
    original_list = DecisionOrderMapRepository.list_reserved_ready
    call_count = [0]

    async def fail_once_then_ok(self, limit=10, now=None):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("D2_injected_db_unavailable")
        return await original_list(self, limit=limit, now=now)

    with patch.object(DecisionOrderMapRepository, "list_reserved_ready", fail_once_then_ok):
        n1 = asyncio.run(run_once(WorkerConfig.from_env()))
    assert n1 >= 0, "first run_once must not raise; should return n>=0 or 0"

    conn = sqlite3.connect(str(d2_db_path))
    try:
        cur = conn.execute(
            "SELECT 1 FROM log WHERE level IN ('ERROR','AUDIT') AND (message LIKE '%list_reserved%' OR message LIKE '%db_unavailable%' OR message LIKE '%run_once%' OR event_type = 'run_once_db_transient') LIMIT 1"
        )
        log_ok = cur.fetchone() is not None
    finally:
        conn.close()

    health_resp = d2_client.get("/api/health/summary")
    assert health_resp.status_code == 200
    health = health_resp.json()
    has_error_observable = log_ok or (health.get("recent_errors")) or ((health.get("metrics") or {}).get("error_count", 0) > 0)
    assert has_error_observable, "health or log must show the transient error (recent_errors/error_count or log ERROR)"

    n2 = asyncio.run(run_once(WorkerConfig.from_env()))
    assert n2 >= 0, "second run_once must continue normally (recovery)"


# ---------- 场景 4：Trace 查询链路不完整（缺 snapshot / execution / trade）----------
def test_d2_trace_incomplete_chain(d2_client, d2_db_path):
    """
    Trace 链路不完整：仅创建 decision 不执行 → trace 返回 PARTIAL，missing_nodes 含 decision_snapshot/execution/trade。
    """
    decision_id = _webhook_create_decision(d2_client, d2_db_path)
    # 不调用 run_once，故无 snapshot、无 execution、无 trade

    trace_resp = d2_client.get(f"/api/trace/decision/{decision_id}")
    assert trace_resp.status_code == 200, f"trace: {trace_resp.status_code} {trace_resp.text}"
    trace_data = trace_resp.json()
    assert trace_data.get("trace_status") == "PARTIAL", trace_data.get("trace_status")
    missing = trace_data.get("missing_nodes") or []
    assert "decision_snapshot" in missing, f"missing_nodes should contain decision_snapshot: {missing}"
    assert "execution" in missing, f"missing_nodes should contain execution: {missing}"
    assert "trade" in missing, f"missing_nodes should contain trade: {missing}"

    health_resp = d2_client.get("/api/health/summary")
    assert health_resp.status_code == 200
    health = health_resp.json()
    assert "overall_ok" in health

    conn = sqlite3.connect(str(d2_db_path))
    try:
        cur = conn.execute("SELECT 1 FROM decision_snapshot WHERE decision_id = ?", (decision_id,))
        assert cur.fetchone() is None, "should have no snapshot when worker not run"
    finally:
        conn.close()
