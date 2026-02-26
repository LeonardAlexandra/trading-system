"""
Fail-fast 配置注入集成测试：启动阶段 load_app_config + validate，app.state.app_config 必须已注入
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.app.main import create_app
from src.config.app_config import AppConfig
from src.common.config_errors import ConfigValidationError
from src.common.reason_codes import INVALID_DATABASE_CONFIGURATION
from src.database.connection import Base
import src.models


@pytest.fixture
def app_with_config(monkeypatch, tmp_path):
    """与 webhook 测试一致：注入必要 env，创建 DB schema，供 lifespan 加载配置并注入 app_config"""
    monkeypatch.setenv("TV_WEBHOOK_SECRET", "test_secret")
    monkeypatch.setenv("STRATEGY_ID", "TEST_STRATEGY_V1")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    tmp_db_path = (tmp_path / "startup_injection.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + tmp_db_path)
    sync_engine = create_engine("sqlite:///" + tmp_db_path)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    return create_app()


def test_app_startup_config_injection(app_with_config):
    """创建 app 并触发生命周期后，app.state.app_config 必须存在且为 AppConfig，validate() 不抛异常"""
    app = app_with_config
    with TestClient(app) as client:
        client.get("/healthz")
    assert hasattr(app.state, "app_config"), "lifespan 应注入 app_config"
    assert app.state.app_config is not None
    assert isinstance(app.state.app_config, AppConfig)
    app.state.app_config.validate()  # 启动时已校验，此处再次调用不应抛


def test_startup_fails_on_invalid_config(monkeypatch):
    """无效配置（如 database.url 为空）时，lifespan 中 load_app_config 抛 ConfigValidationError，应用启动失败"""
    def load_app_config_raising():
        raise ConfigValidationError(
            INVALID_DATABASE_CONFIGURATION,
            "database.url is required",
        )
    monkeypatch.setattr("src.app.main.load_app_config", load_app_config_raising)
    app = create_app()
    with pytest.raises(ConfigValidationError) as exc_info:
        with TestClient(app) as client:
            client.get("/healthz")
    assert exc_info.value.reason_code == INVALID_DATABASE_CONFIGURATION
    assert "database.url" in (exc_info.value.message or "")
