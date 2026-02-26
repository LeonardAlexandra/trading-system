"""
Phase1.2 D6：E2E-6 决策快照写入失败可验证点

验证决策快照写入失败时，不产出 TradingDecision、触发强告警、写 ERROR 日志、拒绝本次决策；禁止静默放行。
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

D6_WEBHOOK_SECRET = "d6_snapshot_fail_secret"
D6_STRATEGY_ID = "D6_SNAPSHOT_FAIL_STRAT"


def _make_signature(secret: str, body: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


@pytest.fixture
def d6_db_path(tmp_path):
    return tmp_path / "d6_snapshot_fail.db"


@pytest.fixture
def d6_config_path(tmp_path, d6_db_path):
    path = tmp_path / "d6_config.yaml"
    path.write_text(
        f"""
database:
  url: "sqlite+aiosqlite:///{d6_db_path.as_posix()}"
tradingview:
  webhook_secret: "{D6_WEBHOOK_SECRET}"
strategy:
  strategy_id: "{D6_STRATEGY_ID}"
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
def d6_schema(d6_db_path):
    sync_url = "sqlite:///" + str(d6_db_path)
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
def d6_app(monkeypatch, d6_db_path, d6_config_path, d6_schema, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + str(d6_db_path))
    monkeypatch.setenv("TV_WEBHOOK_SECRET", D6_WEBHOOK_SECRET)
    monkeypatch.setenv("STRATEGY_ID", D6_STRATEGY_ID)
    monkeypatch.setenv("CONFIG_PATH", str(d6_config_path))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    from src.app.main import create_app
    return create_app()


@pytest.fixture
def d6_client(d6_app):
    with TestClient(d6_app) as c:
        yield c


def _webhook_create_decision(client):
    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-02-08T12:00:00Z",
        "indicator_name": "D6_E2E",
        "strategy_id": D6_STRATEGY_ID,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _make_signature(D6_WEBHOOK_SECRET, body)
    resp = client.post(
        "/webhook/tradingview",
        content=body,
        headers={"Content-Type": "application/json", "X-TradingView-Signature": sig},
    )
    assert resp.status_code == 200, f"webhook failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("status") == "accepted"
    decision_id = data.get("decision_id")
    assert decision_id
    return decision_id


def test_d6_snapshot_save_failure_no_trade_failed_log_alert(d6_client, d6_db_path):
    """
    D6：模拟 decision_snapshot 写入失败后：
    - 未向 ExecutionEngine 传递 TradingDecision（无对应 trade/order）
    - 已触发强告警（等价有记录：ERROR/AUDIT 日志含 decision_id/strategy_id/失败原因）
    - 已写入 ERROR 或 AUDIT 日志（含 decision_id/strategy_id/失败原因）
    - 该 signal 在本轮视为决策失败（decision_order_map.status=FAILED）
    - 禁止静默放行或仍产生 trade
    """
    decision_id = _webhook_create_decision(d6_client)

    from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
    with patch.object(
        DecisionSnapshotRepository,
        "save",
        new_callable=AsyncMock,
        side_effect=RuntimeError("D6_injected_snapshot_save_failure"),
    ):
        config = WorkerConfig.from_env()
        n = asyncio.run(run_once(config))
        assert n >= 0

    conn = sqlite3.connect(str(d6_db_path))
    try:
        cur = conn.execute(
            "SELECT status FROM decision_order_map WHERE decision_id = ?",
            (decision_id,),
        )
        row = cur.fetchone()
        assert row is not None, "decision 应存在"
        assert row[0] == "FAILED", (
            f"D6：快照写入失败后 decision 应为 FAILED，实际 {row[0]!r}"
        )

        cur = conn.execute(
            "SELECT COUNT(1) FROM trade WHERE decision_id = ?",
            (decision_id,),
        )
        trade_count = cur.fetchone()[0]
        assert trade_count == 0, (
            f"D6：未向 ExecutionEngine 传递 TradingDecision，不得产生 trade；实际 {trade_count} 条"
        )

        cur = conn.execute(
            """SELECT 1 FROM log WHERE level IN ('ERROR','AUDIT')
               AND (event_type = 'decision_snapshot_save_failed' OR event_type = 'execution_failed' OR message LIKE '%decision_snapshot%' OR message LIKE '%DECISION_SNAPSHOT_SAVE_FAILED%')
               AND (message LIKE ? OR message LIKE ?)
               LIMIT 1""",
            (f"%{decision_id}%", f"%{D6_STRATEGY_ID}%"),
        )
        log_row = cur.fetchone()
        assert log_row is not None, (
            "D6：已写入 ERROR 或 AUDIT 日志，且含 decision_id/strategy_id/失败原因"
        )
    finally:
        conn.close()
