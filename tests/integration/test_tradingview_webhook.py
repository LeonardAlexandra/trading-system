"""
TradingView Webhook 集成测试（PR4：验签 + 解析，PR5：去重落库 + 决策占位）
"""
import base64
import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.app.main import create_app
from src.database.connection import Base
import src.models  # 确保表注册到 Base.metadata 再 create_all


# 与 fixture 中 monkeypatch 一致，确保应用与测试使用同一 secret
TEST_WEBHOOK_SECRET = "test_webhook_secret"


def _make_signature(secret: str, payload_bytes: bytes) -> str:
    """使用与 TradingViewAdapter 相同的算法生成签名"""
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    ).decode("utf-8")


@pytest.fixture
def app(monkeypatch, tmp_path):
    """在 create_app 之前注入 TV_WEBHOOK_SECRET、STRATEGY_ID、LOG_DIR、DATABASE_URL，并初始化测试 DB schema（PR5 落库依赖表存在）"""
    monkeypatch.setenv("TV_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("STRATEGY_ID", "TEST_STRATEGY_V1")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    tmp_db_path = (tmp_path / "test.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + tmp_db_path)
    # 集成测试落库依赖表存在：用同步引擎在 tmp 文件库上 create_all（不依赖手工 alembic）
    sync_engine = create_engine("sqlite:///" + tmp_db_path)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    return create_app()


@pytest.fixture
def client(app):
    """使用 context manager 触发生命周期，确保 app.state.config 已初始化"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def app_without_strategy_id(monkeypatch, tmp_path):
    """与 app 相同，但不设置 STRATEGY_ID，用于验证缺配置时返回 4xx 而非 500"""
    monkeypatch.setenv("TV_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.delenv("STRATEGY_ID", raising=False)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    tmp_db_path = (tmp_path / "test.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + tmp_db_path)
    sync_engine = create_engine("sqlite:///" + tmp_db_path)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    return create_app()


@pytest.fixture
def client_without_strategy_id(app_without_strategy_id):
    """使用未配置 STRATEGY_ID 的应用，用于测试缺配置时的 4xx 行为"""
    with TestClient(app_without_strategy_id) as c:
        yield c


def test_valid_signature_returns_200(client):
    """验签通过 -> 200 OK，返回 accepted + decision_id + signal_id（PR5）；PR11 payload 含 strategy_id"""
    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-01-27T10:00:00Z",
        "indicator_name": "TEST",
        "strategy_id": "TEST_STRATEGY_V1",
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _make_signature(TEST_WEBHOOK_SECRET, payload_bytes)

    response = client.post(
        "/webhook/tradingview",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-TradingView-Signature": signature,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert "decision_id" in data
    assert "signal_id" in data


def test_invalid_signature_returns_401(client):
    """验签失败 -> 401"""
    payload = {"symbol": "BTCUSDT", "action": "BUY", "timestamp": "2026-01-27T10:00:00Z"}
    payload_bytes = json.dumps(payload).encode("utf-8")
    wrong_signature = _make_signature("wrong_secret", payload_bytes)

    response = client.post(
        "/webhook/tradingview",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-TradingView-Signature": wrong_signature,
        },
    )

    assert response.status_code == 401
    detail = response.json().get("detail", "")
    assert "signature" in detail.lower() or "invalid" in detail.lower()


def test_malformed_payload_returns_400(client):
    """验签通过但 payload 缺必填字段 -> 400"""
    payload = {"symbol": "BTCUSDT"}  # 缺少 action/side、timestamp
    payload_bytes = json.dumps(payload).encode("utf-8")
    signature = _make_signature(TEST_WEBHOOK_SECRET, payload_bytes)

    response = client.post(
        "/webhook/tradingview",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-TradingView-Signature": signature,
        },
    )

    assert response.status_code == 400
    data = response.json()
    assert data.get("detail") == "invalid_payload"
    assert data.get("reason_code") == "MALFORMED_PAYLOAD"


def test_missing_signature_returns_401(client):
    """缺少 X-TradingView-Signature 头 -> 401"""
    payload = {"symbol": "BTCUSDT", "action": "BUY", "timestamp": "2026-01-27T10:00:00Z"}
    payload_bytes = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/webhook/tradingview",
        content=payload_bytes,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401


def test_missing_strategy_id_returns_4xx_not_500(client_without_strategy_id):
    """STRATEGY_ID 未配置时：合法签名 + 合法 payload 应返回 4xx（配置错误），不得返回 500（系统故障）"""
    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-01-27T10:00:00Z",
        "indicator_name": "TEST",
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _make_signature(TEST_WEBHOOK_SECRET, payload_bytes)

    response = client_without_strategy_id.post(
        "/webhook/tradingview",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-TradingView-Signature": signature,
        },
    )

    assert response.status_code != 500, "配置错误不得返回 500"
    assert response.status_code == 422
    data = response.json()
    assert data.get("reason_code") == "MISSING_STRATEGY_ID"


def test_duplicate_signal_returns_duplicate_ignored_and_db_single_row(client, tmp_path):
    """同一 payload 发两次：第一次 accepted，第二次 duplicate_ignored；DB 仅一条 DedupSignal、一条 DecisionOrderMap（PR5）；PR11 payload 含 strategy_id"""
    import sqlite3

    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-01-27T10:00:00Z",
        "indicator_name": "DUP",
        "strategy_id": "TEST_STRATEGY_V1",
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _make_signature(TEST_WEBHOOK_SECRET, payload_bytes)
    headers = {
        "Content-Type": "application/json",
        "X-TradingView-Signature": signature,
    }

    r1 = client.post("/webhook/tradingview", content=payload_bytes, headers=headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["status"] == "accepted"
    assert "decision_id" in d1
    assert "signal_id" in d1

    r2 = client.post("/webhook/tradingview", content=payload_bytes, headers=headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["status"] == "duplicate_ignored"

    db_path = tmp_path / "test.db"
    if not db_path.exists():
        pytest.skip("DB file not created (app may use in-memory DB)")
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM dedup_signal")
        (n_dedup,) = cur.fetchone()
        cur = conn.execute("SELECT COUNT(*) FROM decision_order_map")
        (n_dom,) = cur.fetchone()
    finally:
        conn.close()
    assert n_dedup == 1
    assert n_dom == 1


def test_signal_id_based_on_semantic_fields_not_payload_structure(client, tmp_path):
    """验证 signal_id 由语义字段决定：两份 JSON 结构/顺序/无关字段不同但语义一致的 payload，第二次应被去重（duplicate_ignored），DB 仅 1 条。"""
    import sqlite3

    # 语义完全一致：symbol / action / timeframe / timestamp / indicator
    # Payload A：key 顺序 + 无多余字段
    payload_a = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timeframe": "1h",
        "timestamp": "2026-01-27T10:00:00Z",
        "indicator_name": "SEMANTIC_ID",
        "strategy_id": "TEST_STRATEGY_V1",
    }
    # Payload B：key 顺序不同，且多一个无关字段（不应影响 signal_id）；PR11 含 strategy_id
    payload_b = {
        "indicator_name": "SEMANTIC_ID",
        "timestamp": "2026-01-27T10:00:00Z",
        "action": "BUY",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "comment": "extra field not used for signal_id",
        "strategy_id": "TEST_STRATEGY_V1",
    }

    bytes_a = json.dumps(payload_a, separators=(",", ":"), sort_keys=True).encode("utf-8")
    bytes_b = json.dumps(payload_b, separators=(",", ":"), sort_keys=False).encode("utf-8")
    sig_a = _make_signature(TEST_WEBHOOK_SECRET, bytes_a)
    sig_b = _make_signature(TEST_WEBHOOK_SECRET, bytes_b)
    headers_a = {"Content-Type": "application/json", "X-TradingView-Signature": sig_a}
    headers_b = {"Content-Type": "application/json", "X-TradingView-Signature": sig_b}

    r1 = client.post("/webhook/tradingview", content=bytes_a, headers=headers_a)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["status"] == "accepted"
    assert "decision_id" in d1
    assert "signal_id" in d1

    r2 = client.post("/webhook/tradingview", content=bytes_b, headers=headers_b)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["status"] == "duplicate_ignored"

    db_path = tmp_path / "test.db"
    if not db_path.exists():
        pytest.skip("DB file not created (app may use in-memory DB)")
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM dedup_signal")
        (n_dedup,) = cur.fetchone()
        cur = conn.execute("SELECT COUNT(*) FROM decision_order_map")
        (n_dom,) = cur.fetchone()
    finally:
        conn.close()
    assert n_dedup == 1, "dedup_signal should have exactly 1 row when semantics are identical"
    assert n_dom == 1, "decision_order_map should have exactly 1 row when semantics are identical"
