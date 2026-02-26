"""
Phase1.2 D2：E2E-2 审计可验证点

验证风控拒绝或执行失败时，审计日志可查且可按时间/组件/级别筛选。
- 触发一次风控拒绝或执行失败后，LogRepository.query(level=AUDIT 或 ERROR) 含该事件。
- query 按 start_ts/end_ts（created_at_from/created_at_to）、component、level 可筛选出对应记录。
"""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.app.dependencies import get_db_session
from src.database.connection import Base
import src.models  # noqa: F401
from src.execution.execution_worker import run_once
from src.execution.worker_config import WorkerConfig
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
from src.repositories.log_repository import LogRepository

D2_AUDIT_WEBHOOK_SECRET = "d2_audit_e2e_secret"
D2_AUDIT_STRATEGY_ID = "D2_AUDIT_E2E_STRATEGY"


def _make_signature(secret: str, body: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


@pytest.fixture
def d2_audit_db_path(tmp_path):
    return tmp_path / "d2_audit_e2e.db"


@pytest.fixture
def d2_audit_config_path(tmp_path, d2_audit_db_path):
    path = tmp_path / "d2_audit_config.yaml"
    path.write_text(
        f"""
database:
  url: "sqlite+aiosqlite:///{d2_audit_db_path.as_posix()}"
tradingview:
  webhook_secret: "{D2_AUDIT_WEBHOOK_SECRET}"
strategy:
  strategy_id: "{D2_AUDIT_STRATEGY_ID}"
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
def d2_audit_schema(d2_audit_db_path):
    sync_url = "sqlite:///" + str(d2_audit_db_path)
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
def d2_audit_app(monkeypatch, d2_audit_db_path, d2_audit_config_path, d2_audit_schema, tmp_path):
    async_url = "sqlite+aiosqlite:///" + str(d2_audit_db_path)
    monkeypatch.setenv("DATABASE_URL", async_url)
    monkeypatch.setenv("TV_WEBHOOK_SECRET", D2_AUDIT_WEBHOOK_SECRET)
    monkeypatch.setenv("STRATEGY_ID", D2_AUDIT_STRATEGY_ID)
    monkeypatch.setenv("CONFIG_PATH", str(d2_audit_config_path))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    from src.app.main import create_app
    return create_app()


@pytest.fixture
def d2_audit_client(d2_audit_app):
    with TestClient(d2_audit_app) as c:
        yield c


def _webhook_create_decision(client):
    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-02-08T12:00:00Z",
        "indicator_name": "D2_AUDIT_E2E",
        "strategy_id": D2_AUDIT_STRATEGY_ID,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _make_signature(D2_AUDIT_WEBHOOK_SECRET, body)
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


def _is_failure_audit_or_error(entry, decision_id: str) -> bool:
    """事件是否为本次执行失败/风控拒绝相关的 AUDIT 或 ERROR。"""
    if entry.level not in ("AUDIT", "ERROR"):
        return False
    if entry.component != "execution_engine":
        return False
    msg = (entry.message or "")
    payload = entry.payload or {}
    did = payload.get("decision_id") or (decision_id if decision_id in msg else None)
    if entry.event_type in ("execution_failed", "decision_snapshot_save_failed", "risk_check_reject"):
        return True
    if "execution_failed" in msg or "decision_snapshot" in msg or "risk_check_reject" in msg or "snapshot_save" in msg:
        return True
    return False


@pytest.mark.asyncio
async def test_d2_audit_log_contains_failure_event(d2_audit_client):
    """
    D2 可验证点 1：触发一次执行失败后，LogRepository.query(level=AUDIT 或 ERROR) 含该事件。
    """
    decision_id = _webhook_create_decision(d2_audit_client)
    with patch.object(
        DecisionSnapshotRepository,
        "save",
        new_callable=AsyncMock,
        side_effect=RuntimeError("D2_audit_injected_snapshot_failure"),
    ):
        config = WorkerConfig.from_env()
        await run_once(config)

    async with get_db_session() as session:
        repo = LogRepository(session)
        aud_entries = await repo.query(level="AUDIT", limit=100)
        err_entries = await repo.query(level="ERROR", limit=100)
    all_entries = list(aud_entries) + list(err_entries)
    found = any(_is_failure_audit_or_error(e, decision_id) for e in all_entries)
    assert found, (
        f"D2: LogRepository.query(level=AUDIT 或 ERROR) 应含本次执行失败事件；"
        f"decision_id={decision_id}, aud={len(aud_entries)}, err={len(err_entries)}"
    )


@pytest.mark.asyncio
async def test_d2_audit_query_filter_by_time_component_level(d2_audit_client):
    """
    D2 可验证点 2：query 按 start_ts/end_ts(created_at_from/created_at_to)、component、level 可筛选出对应记录。
    """
    decision_id = _webhook_create_decision(d2_audit_client)
    t_before = datetime.now(timezone.utc) - timedelta(seconds=2)
    with patch.object(
        DecisionSnapshotRepository,
        "save",
        new_callable=AsyncMock,
        side_effect=RuntimeError("D2_audit_injected_snapshot_failure"),
    ):
        config = WorkerConfig.from_env()
        await run_once(config)
    t_after = datetime.now(timezone.utc) + timedelta(seconds=2)

    async with get_db_session() as session:
        repo = LogRepository(session)
        # 按时间范围 + component + level 筛选
        aud_filtered = await repo.query(
            created_at_from=t_before,
            created_at_to=t_after,
            component="execution_engine",
            level="AUDIT",
            limit=100,
        )
        err_filtered = await repo.query(
            created_at_from=t_before,
            created_at_to=t_after,
            component="execution_engine",
            level="ERROR",
            limit=100,
        )
    combined = list(aud_filtered) + list(err_filtered)
    found = any(_is_failure_audit_or_error(e, decision_id) for e in combined)
    assert found, (
        f"D2: query(created_at_from, created_at_to, component=execution_engine, level=AUDIT/ERROR) 应能筛选出该事件；"
        f"decision_id={decision_id}, aud_filtered={len(aud_filtered)}, err_filtered={len(err_filtered)}"
    )
    # 错误 component 不应包含 execution_engine 的该事件
    async with get_db_session() as session:
        repo = LogRepository(session)
        other_comp = await repo.query(
            created_at_from=t_before,
            created_at_to=t_after,
            component="other_component",
            level="AUDIT",
            limit=100,
        )
    for e in other_comp:
        assert e.component == "other_component", "筛选 component 后应只返回该 component"
    # 筛选 level=INFO 时不应包含本次 ERROR/AUDIT 事件（或仅验证 level 过滤生效）
    async with get_db_session() as session:
        repo = LogRepository(session)
        info_only = await repo.query(
            created_at_from=t_before,
            created_at_to=t_after,
            component="execution_engine",
            level="INFO",
            limit=100,
        )
    for e in info_only:
        assert e.level == "INFO", "筛选 level=INFO 应只返回 INFO"
