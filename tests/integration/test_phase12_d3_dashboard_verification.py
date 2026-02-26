"""
Phase1.2 D3：E2E-3 Dashboard 可验证点

验证最小 Dashboard 页面展示与 API 一致，无前端自算指标。
- 打开最小 Dashboard 页面，展示最近决策/执行/成交、汇总、健康指标。
- 页面数据与 GET /api/dashboard/* 及 GET /api/health/summary 返回一致。
- 无前端自算 pnl/笔数。
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.database.connection import Base
import src.models  # noqa: F401
from src.app.main import create_app


@pytest.fixture
def d3_db_path(tmp_path):
    return tmp_path / "d3_dashboard.db"


@pytest.fixture
def d3_config_path(tmp_path, d3_db_path):
    path = tmp_path / "d3_config.yaml"
    path.write_text(
        f"""
database:
  url: "sqlite+aiosqlite:///{d3_db_path.as_posix()}"
tradingview:
  webhook_secret: "d3_secret"
strategy:
  strategy_id: "D3_STRAT"
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
def d3_schema(d3_db_path):
    sync_url = "sqlite:///" + str(d3_db_path)
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
def d3_app(monkeypatch, d3_db_path, d3_config_path, d3_schema):
    async_url = "sqlite+aiosqlite:///" + str(d3_db_path)
    monkeypatch.setenv("DATABASE_URL", async_url)
    monkeypatch.setenv("CONFIG_PATH", str(d3_config_path))
    return create_app()


@pytest.fixture
def d3_client(d3_app):
    with TestClient(d3_app) as c:
        yield c


def test_d3_dashboard_page_returns_200_and_shows_sections(d3_client):
    """
    D3 可验证点：打开最小 Dashboard 页面，展示最近决策/执行/成交、汇总、健康指标。
    页面必须包含四个区块标题及对 GET /api/dashboard/* 与 GET /api/health/summary 的调用。
    """
    resp = d3_client.get("/dashboard")
    assert resp.status_code == 200, f"GET /dashboard 应返回 200，实际 {resp.status_code}"
    html = resp.text
    assert "决策列表" in html, "页面应展示决策列表区块"
    assert "执行/成交列表" in html, "页面应展示执行/成交列表区块"
    assert "汇总" in html, "页面应展示汇总区块"
    assert "健康状态" in html, "页面应展示健康指标区块"
    assert "/api/dashboard/decisions" in html, "页面应调用 GET /api/dashboard/decisions"
    assert "/api/dashboard/executions" in html, "页面应调用 GET /api/dashboard/executions"
    assert "/api/dashboard/summary" in html, "页面应调用 GET /api/dashboard/summary"
    assert "/api/health/summary" in html, "页面应调用 GET /api/health/summary"


def test_d3_dashboard_page_data_from_api_only(d3_client):
    """
    D3 可验证点：页面数据与 GET /api/dashboard/* 及 GET /api/health/summary 返回一致；
    无前端自算 pnl/笔数（列表与汇总仅展示 API 返回字段，不包含 reduce/sum 等聚合计算）。
    """
    resp = d3_client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    # 汇总区必须直接使用 API 返回的 group_key, trade_count, pnl_sum 展示，禁止前端对数组做 sum/count 得到 pnl 或笔数
    assert "group_key" in html and "trade_count" in html and "pnl_sum" in html, (
        "汇总区应展示 API 返回的 group_key, trade_count, pnl_sum，即数据来自 GET /api/dashboard/summary"
    )
    # 禁止前端自算：script 中不得出现 .reduce( 聚合得到 pnl/笔数；汇总区使用 API 的 trade_count、pnl_sum 直接展示
    script_start = html.find("<script>")
    script_end = html.find("</script>")
    assert script_start != -1 and script_end != -1, "页面应包含 script"
    script = html[script_start:script_end]
    assert "reduce(" not in script, "禁止前端用 reduce 自算 pnl/笔数；须直接使用 API 返回的 trade_count、pnl_sum"
    assert "row[k]" in script or "row[" in script, "列表数据应为 API 返回的 row 字段直接展示"


def test_d3_dashboard_apis_return_consistent_structure(d3_client):
    """
    D3：GET /api/dashboard/* 与 GET /api/health/summary 可调用且返回结构与页面消费一致。
    页面与 API 一致即：页面 fetch 上述接口并原样展示返回的 decisions/executions/summary/health。
    """
    dec = d3_client.get("/api/dashboard/decisions?limit=10")
    assert dec.status_code == 200
    assert isinstance(dec.json(), list), "decisions 应为数组"

    exe = d3_client.get("/api/dashboard/executions?limit=10")
    assert exe.status_code == 200
    assert isinstance(exe.json(), list), "executions 应为数组"

    summary = d3_client.get("/api/dashboard/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert isinstance(data, list), "summary 应为数组"
    for item in data:
        assert "group_key" in item and "trade_count" in item and "pnl_sum" in item, (
            "summary 每项应含 group_key, trade_count, pnl_sum（页面直接展示，无前端自算）"
        )

    health = d3_client.get("/api/health/summary")
    assert health.status_code == 200
    h = health.json()
    assert isinstance(h, dict), "health/summary 应为对象"
    assert "overall_ok" in h, "health 应含 overall_ok（页面直接展示）"
