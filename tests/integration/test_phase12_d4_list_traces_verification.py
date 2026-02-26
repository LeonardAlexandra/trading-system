"""
Phase1.2 D4：E2E-4 多笔回放可验证点

验证多笔回放 API 与审计查询界面与 1.2a 数据一致。
- list_traces 指定时间范围返回 list[TraceSummary]。
- 审计查询界面筛选结果与 log 表一致。
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401
from src.models.decision_order_map import DecisionOrderMap
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.log_repository import LogRepository
from src.services import audit_service


@pytest.fixture
def d4_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def d4_db_url(d4_tmp_path):
    return "sqlite+aiosqlite:///" + (d4_tmp_path / "d4_audit.db").as_posix()


@pytest.fixture
def d4_sync_db_url(d4_tmp_path):
    return "sqlite:///" + (d4_tmp_path / "d4_audit.db").as_posix()


@pytest.fixture
def d4_schema(d4_sync_db_url):
    engine = create_engine(d4_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
def d4_config_path(d4_tmp_path, d4_db_url):
    path = d4_tmp_path / "d4_config.yaml"
    path.write_text(
        f"""
database:
  url: "{d4_db_url}"
tradingview:
  webhook_secret: "d4_secret"
strategy:
  strategy_id: "D4_STRAT"
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
async def d4_session_factory(d4_db_url, d4_schema):
    engine = create_async_engine(d4_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.fixture
def d4_app(monkeypatch, d4_db_url, d4_config_path, d4_schema):
    monkeypatch.setenv("DATABASE_URL", d4_db_url)
    monkeypatch.setenv("CONFIG_PATH", str(d4_config_path))
    from src.app.main import create_app
    return create_app()


@pytest.fixture
def d4_client(d4_app):
    with TestClient(d4_app) as client:
        yield client


@pytest.mark.asyncio
async def test_d4_list_traces_returns_list_trace_summary(d4_session_factory, d4_client):
    """
    D4 可验证点：list_traces 指定时间范围返回 list[TraceSummary]。
    每条必含 decision_id, trace_status, missing_nodes；与 1.2a 数据一致。
    """
    now = datetime.now(timezone.utc)
    decision_id = "d4-dec-list"
    start_ts = (now - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    end_ts = (now + timedelta(days=1)).isoformat().replace("+00:00", "Z")

    async with get_db_session() as session:
        await DecisionOrderMapRepository(session).create_reserved(
            decision_id=decision_id,
            signal_id="d4-sig-1",
            strategy_id="D4_STRAT",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )

    d4_client.get("/healthz")
    resp = d4_client.get(f"/api/audit/traces?from={start_ts}&to={end_ts}&limit=100")
    assert resp.status_code == 200, f"list_traces 应返回 200，实际 {resp.status_code} {resp.text}"
    data = resp.json()
    assert "items" in data, "响应应含 items"
    items = data["items"]
    assert isinstance(items, list), "items 应为 list[TraceSummary]（数组）"
    assert len(items) >= 1, "时间范围内应至少 1 条"
    for row in items:
        assert "decision_id" in row, "每条应含 decision_id"
        assert "trace_status" in row, "每条应含 trace_status"
        assert "missing_nodes" in row, "每条应含 missing_nodes"
        assert row["trace_status"] in ("COMPLETE", "PARTIAL", "NOT_FOUND"), (
            f"trace_status 应为 COMPLETE/PARTIAL/NOT_FOUND，实际 {row['trace_status']!r}"
        )
        assert isinstance(row["missing_nodes"], list), "missing_nodes 应为数组"
    one = next((r for r in items if r["decision_id"] == decision_id), None)
    assert one is not None, "应含本次插入的 decision_id"


@pytest.mark.asyncio
async def test_d4_audit_query_interface_matches_log_table(d4_session_factory, d4_client):
    """
    D4 可验证点：审计查询界面筛选结果与 log 表一致。
    即 GET /api/audit/logs 返回的 items 与 LogRepository.query(相同参数) 结果一致。
    """
    now = datetime.now(timezone.utc)
    from_ts = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    to_ts = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    async with get_db_session() as session:
        repo = LogRepository(session)
        await repo.write("AUDIT", "d4-audit-comp", "d4-audit-msg", event_type="d4_audit")
        await repo.write("ERROR", "d4-audit-comp", "d4-error-msg", event_type="d4_error")

    d4_client.get("/healthz")
    resp = d4_client.get(
        f"/api/audit/logs?from={from_ts}&to={to_ts}&component=d4-audit-comp&level=AUDIT&limit=100"
    )
    assert resp.status_code == 200, f"审计日志查询应返回 200，实际 {resp.status_code} {resp.text}"
    api_data = resp.json()
    api_items = api_data.get("items") or []
    api_ids = {item["id"] for item in api_items}

    async with get_db_session() as session:
        direct = await LogRepository(session).query(
            created_at_from=datetime.fromisoformat(from_ts.replace("Z", "+00:00")),
            created_at_to=datetime.fromisoformat(to_ts.replace("Z", "+00:00")),
            component="d4-audit-comp",
            level="AUDIT",
            limit=100,
            offset=0,
        )
    direct_ids = {e.id for e in direct}
    assert api_ids == direct_ids, (
        "审计查询界面筛选结果应与 log 表一致：GET /api/audit/logs 返回的 id 集合应等于 LogRepository.query(相同参数) 的 id 集合"
    )
    assert len([e for e in direct if e.component == "d4-audit-comp" and e.level == "AUDIT"]) >= 1
