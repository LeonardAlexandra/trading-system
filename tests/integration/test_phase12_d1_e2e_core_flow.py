"""
Phase1.2 D1：E2E-1 完整链路可验证点

验证：Webhook 信号 → decision → 同事务 decision_snapshot → 执行并成交 → 按 signal_id/decision_id 查询得完整链路（含 decision_snapshot）；trace_status=COMPLETE。
验收：发送一条 Webhook 后 DB 有 1 条 trade、1 条 decision_snapshot 且 decision_id 一致；get_trace_by_signal_id / get_trace_by_decision_id 返回 200、五节点、trace_status=COMPLETE、missing_nodes 为空。
"""
import asyncio
import base64
import hashlib
import hmac
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.database.connection import Base
import src.models  # noqa: F401
from src.execution.execution_worker import run_once
from src.execution.worker_config import WorkerConfig

D1_WEBHOOK_SECRET = "d1_e2e_secret"
D1_STRATEGY_ID = "D1_E2E_STRATEGY"


def _make_signature(secret: str, body: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


@pytest.fixture
def d1_db_path(tmp_path):
    return tmp_path / "d1_e2e.db"


@pytest.fixture
def d1_config_path(tmp_path, d1_db_path):
    """最小配置：database、tradingview、strategy，供 load_app_config 使用。"""
    path = tmp_path / "d1_config.yaml"
    path.write_text(
        f"""
database:
  url: "sqlite+aiosqlite:///{d1_db_path.as_posix()}"
tradingview:
  webhook_secret: "{D1_WEBHOOK_SECRET}"
strategy:
  strategy_id: "{D1_STRATEGY_ID}"
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
def d1_schema(d1_db_path):
    sync_url = "sqlite:///" + str(d1_db_path)
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
def d1_app(monkeypatch, d1_db_path, d1_config_path, d1_schema, tmp_path):
    async_url = "sqlite+aiosqlite:///" + str(d1_db_path)
    monkeypatch.setenv("DATABASE_URL", async_url)
    monkeypatch.setenv("TV_WEBHOOK_SECRET", D1_WEBHOOK_SECRET)
    monkeypatch.setenv("STRATEGY_ID", D1_STRATEGY_ID)
    monkeypatch.setenv("CONFIG_PATH", str(d1_config_path))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    from src.app.main import create_app
    return create_app()


@pytest.fixture
def d1_client(d1_app):
    with TestClient(d1_app) as c:
        yield c


def test_d1_e2e_core_flow(d1_client, d1_db_path):
    """
    D1 可验证点：发送一条 Webhook 后 DB 有 1 条 trade、1 条 decision_snapshot 且 decision_id 一致；
    get_trace_by_signal_id / get_trace_by_decision_id 返回 200、含五节点、trace_status=COMPLETE、missing_nodes 为空。
    """
    # --- 1. 信号 + 决策 ---
    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-02-08T12:00:00Z",
        "indicator_name": "D1_E2E",
        "strategy_id": D1_STRATEGY_ID,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _make_signature(D1_WEBHOOK_SECRET, body)
    resp = d1_client.post(
        "/webhook/tradingview",
        content=body,
        headers={"Content-Type": "application/json", "X-TradingView-Signature": sig},
    )
    assert resp.status_code == 200, f"signal/decision stage failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("status") == "accepted", f"signal/decision stage: expected accepted, got {data}"
    decision_id = data.get("decision_id")
    assert decision_id, "signal/decision stage: missing decision_id"

    # --- 2. 执行（worker 处理 RESERVED → 写 snapshot + 执行并成交 → 写 trade）---
    config = WorkerConfig.from_env()
    n = asyncio.run(run_once(config))
    assert n >= 1, "execution stage: run_once should process at least 1 decision"

    # --- 3. 验证 DB：1 条 decision_snapshot、1 条 trade，且 decision_id 一致 ---
    conn = sqlite3.connect(str(d1_db_path))
    try:
        cur = conn.execute("SELECT 1 FROM decision_snapshot WHERE decision_id = ?", (decision_id,))
        assert cur.fetchone() is not None, "D1: 应有 1 条 decision_snapshot 对应 decision_id"
        cur = conn.execute("SELECT decision_id FROM trade WHERE decision_id = ?", (decision_id,))
        trade_rows = cur.fetchall()
        assert len(trade_rows) == 1, f"D1: 应有 1 条 trade 对应 decision_id，实际 {len(trade_rows)} 条"
        assert trade_rows[0][0] == decision_id, "D1: trade.decision_id 与 decision_snapshot 一致"
        cur = conn.execute("SELECT signal_id FROM decision_order_map WHERE decision_id = ?", (decision_id,))
        row = cur.fetchone()
        assert row is not None and row[0], "D1: decision_order_map 应有 signal_id"
        signal_id = row[0]
    finally:
        conn.close()

    # --- 4. get_trace_by_decision_id：200、五节点、trace_status=COMPLETE、missing_nodes 为空 ---
    trace_resp = d1_client.get(f"/api/trace/decision/{decision_id}")
    assert trace_resp.status_code == 200, f"trace by decision_id: {trace_resp.status_code} {trace_resp.text}"
    trace_data = trace_resp.json()
    assert trace_data.get("trace_status") == "COMPLETE", (
        f"D1: trace_status 应为 COMPLETE，实际 {trace_data.get('trace_status')!r}"
    )
    missing = trace_data.get("missing_nodes") or []
    assert missing == [], f"D1: missing_nodes 应为空，实际 {missing!r}"
    for key in ("signal", "decision", "decision_snapshot", "execution", "trade"):
        assert trace_data.get(key) is not None, f"D1: TraceResult 应含五节点之一 {key!r}"

    # --- 5. get_trace_by_signal_id：200、五节点、trace_status=COMPLETE、missing_nodes 为空 ---
    trace_sig_resp = d1_client.get(f"/api/trace/signal/{signal_id}")
    assert trace_sig_resp.status_code == 200, f"trace by signal_id: {trace_sig_resp.status_code} {trace_sig_resp.text}"
    trace_sig_data = trace_sig_resp.json()
    assert trace_sig_data.get("trace_status") == "COMPLETE", (
        f"D1: get_trace_by_signal_id trace_status 应为 COMPLETE，实际 {trace_sig_data.get('trace_status')!r}"
    )
    missing_sig = trace_sig_data.get("missing_nodes") or []
    assert missing_sig == [], f"D1: get_trace_by_signal_id missing_nodes 应为空，实际 {missing_sig!r}"
    for key in ("signal", "decision", "decision_snapshot", "execution", "trade"):
        assert trace_sig_data.get(key) is not None, f"D1: get_trace_by_signal_id 应含五节点之一 {key!r}"

    # --- 6. Dashboard / Health（端点可访问）---
    dec_resp = d1_client.get("/api/dashboard/decisions?limit=10")
    assert dec_resp.status_code == 200, f"dashboard decisions {dec_resp.status_code}"
    sum_resp = d1_client.get("/api/dashboard/summary")
    assert sum_resp.status_code == 200, f"dashboard summary {sum_resp.status_code}"
    health_resp = d1_client.get("/api/health/summary")
    assert health_resp.status_code == 200, f"health {health_resp.status_code}"
    assert health_resp.json().get("overall_ok") is True, "health overall_ok 应为 true"
