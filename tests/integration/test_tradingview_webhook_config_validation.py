"""
PR10 Webhook 配置校验集成测试：缺失 webhook secret 或策略配置时返回 422 + reason_code=INVALID_CONFIGURATION
"""
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.app.main import create_app
from src.database.connection import Base
import src.models


@pytest.fixture
def app_missing_webhook_secret(monkeypatch, tmp_path):
    """不设置 TV_WEBHOOK_SECRET，且使用无 webhook_secret 的配置，验证缺失 secret 时返回 422 INVALID_CONFIGURATION"""
    monkeypatch.delenv("TV_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("STRATEGY_ID", "TEST_STRATEGY_V1")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    tmp_db_path = (tmp_path / "test_no_secret.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + tmp_db_path)
    # 使用临时配置文件，不含 tradingview.webhook_secret
    minimal_yaml = tmp_path / "minimal_no_secret.yaml"
    minimal_yaml.write_text(
        "database:\n  url: \"\"\nstrategy:\n  strategy_id: \"TEST_STRATEGY_V1\"\ntradingview: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_PATH", str(minimal_yaml))
    # 防止 load_dotenv() 从 .env 重新注入 TV_WEBHOOK_SECRET
    monkeypatch.setattr("src.utils.config.load_dotenv", lambda *a, **k: None)
    sync_engine = create_engine("sqlite:///" + tmp_db_path)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    return create_app()


@pytest.fixture
def client_missing_webhook_secret(app_missing_webhook_secret):
    with TestClient(app_missing_webhook_secret) as c:
        yield c


def test_missing_webhook_secret_returns_422_with_invalid_configuration(client_missing_webhook_secret):
    """缺失 webhook secret 时：POST 任意 body，应返回 422 且 reason_code=INVALID_CONFIGURATION（PR10）"""
    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-01-27T10:00:00Z",
        "indicator_name": "TEST",
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = client_missing_webhook_secret.post(
        "/webhook/tradingview",
        content=payload_bytes,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    data = response.json()
    assert data.get("reason_code") == "INVALID_WEBHOOK_CONFIGURATION"
    assert "detail" in data
    assert "request_id" in data
    assert "secret" in data["detail"].lower() or "config" in data["detail"].lower()
