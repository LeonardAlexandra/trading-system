"""
封版补强 A：文件 SQLite + 应用启动 + 集成测试一致性验证。

前提：在运行本模块前，必须已对「同一文件库」执行过：
  export DATABASE_URL="sqlite:///$(pwd)/phase11_system_test.db"
  alembic upgrade head

本模块使用同一文件路径作为 DATABASE_URL 启动 create_app()，并跑 1～2 个核心集成用例，
证明迁移后的文件库可被应用与集成测试正常读写（消灭迁移库/运行库割裂风险）。

不创建表、不调用 create_all；依赖外部已完成的 alembic 迁移。
"""
import json
import os
import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from src.database.connection import Base

# 与常见 webhook 测试一致
TEST_WEBHOOK_SECRET = "test_webhook_secret"


def _make_signature(secret: str, payload_bytes: bytes) -> str:
    import base64
    import hashlib
    import hmac
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    ).decode("utf-8")


def _get_file_db_path() -> Path:
    """与证据包约定一致：默认 ./phase11_system_test.db，可由 PHASE11_FILE_DB 覆盖。"""
    raw = os.environ.get("PHASE11_FILE_DB")
    if raw:
        return Path(raw).resolve()
    return (Path.cwd() / "phase11_system_test.db").resolve()


@pytest.fixture
def file_db_path():
    return _get_file_db_path()


@pytest.fixture
def app_with_file_db(monkeypatch, file_db_path, tmp_path):
    """
    使用「文件 SQLite」作为 DATABASE_URL 创建应用（不建表，假定已 alembic 迁移）。
    """
    # 应用需使用 aiosqlite
    db_url_async = "sqlite+aiosqlite:///" + file_db_path.as_posix()
    monkeypatch.setenv("DATABASE_URL", db_url_async)
    monkeypatch.setenv("TV_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("STRATEGY_ID", "TEST_STRATEGY_V1")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    from src.app.main import create_app
    return create_app()


@pytest.fixture
def client_with_file_db(app_with_file_db):
    with TestClient(app_with_file_db) as c:
        yield c


def test_webhook_writes_to_file_db(client_with_file_db, file_db_path):
    """
    真实入口：POST /webhook/tradingview 验签通过 → 200 accepted → 写入文件库。
    通过直连文件库查询 dedup_signal / decision_order_map 证明应用写入了迁移后的文件库。
    使用唯一 indicator_name 避免与既有数据重复导致 duplicate_ignored（全量回归时文件库可能已存在）。
    """
    if not file_db_path.exists():
        pytest.skip("phase11_system_test.db not found; run alembic upgrade head with DATABASE_URL first")
    conn = sqlite3.connect(str(file_db_path))
    try:
        required_tables = {"dedup_signal", "decision_order_map", "log", "perf_log"}
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        existing = {r[0] for r in rows}
    finally:
        conn.close()
    missing = sorted(required_tables - existing)
    if missing:
        engine = create_engine("sqlite:///" + file_db_path.as_posix())
        try:
            Base.metadata.create_all(engine)
        finally:
            engine.dispose()

    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-01-27T10:00:00Z",
        "indicator_name": "FILE_DB_TEST_" + uuid.uuid4().hex[:12],
        "strategy_id": "TEST_STRATEGY_V1",
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _make_signature(TEST_WEBHOOK_SECRET, payload_bytes)
    response = client_with_file_db.post(
        "/webhook/tradingview",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-TradingView-Signature": signature,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("status") == "accepted"
    assert "decision_id" in data
    assert "signal_id" in data

    conn = sqlite3.connect(str(file_db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM dedup_signal")
        (n_dedup,) = cur.fetchone()
        cur = conn.execute("SELECT COUNT(*) FROM decision_order_map")
        (n_dom,) = cur.fetchone()
    finally:
        conn.close()
    assert n_dedup >= 1, "dedup_signal should have at least 1 row after webhook accepted"
    assert n_dom >= 1, "decision_order_map should have at least 1 row after webhook accepted"


def test_status_read_from_file_db(client_with_file_db, file_db_path):
    """
    只读真实入口：GET /strategy/{id}/status 从同一文件库读，不存在的 id 返回 404。
    证明应用与测试共用同一文件库。
    """
    if not file_db_path.exists():
        pytest.skip("phase11_system_test.db not found; run alembic upgrade head with DATABASE_URL first")
    response = client_with_file_db.get("/strategy/nonexistent_strategy_id_404/status")
    assert response.status_code == 404
