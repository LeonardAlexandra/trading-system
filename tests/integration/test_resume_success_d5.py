"""
Phase1.1 D5：恢复成功全链路测试（PAUSED → RUNNING）

真实走 B1 路由 POST /strategy/{id}/resume，强校验通过后验证：
状态 PAUSED → RUNNING、STRATEGY_RESUMED 终态日志落库、恢复后信号可被正常接收。
"""
import base64
import hashlib
import hmac
import json
import pytest
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import create_engine
from fastapi.testclient import TestClient

from src.app.dependencies import get_db_session, set_session_factory
from src.database.connection import Base
from src.models.strategy_runtime_state import STATUS_PAUSED, STATUS_RUNNING
from src.models.position_reconcile_log import STRATEGY_RESUMED
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.models.decision_order_map_status import (
    RESERVED,
    SUBMITTING,
    PENDING_EXCHANGE,
    PLACED,
    FILLED,
)
# D6 证据补强：允许状态集合断言，避免把状态机锁死；验证 D5.1 锚点不破坏状态推进
D5_1_ANCHOR_ALLOWED_STATUSES = frozenset({RESERVED, SUBMITTING, PENDING_EXCHANGE, PLACED, FILLED})

D5_STRATEGY_ID = "D5_RESUME_OK_STRAT"
D5_WEBHOOK_SECRET = "d5_resume_ok_webhook_secret"


def _make_signature(secret: str, payload_bytes: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    ).decode("utf-8")


async def _ensure_runtime_state(session: AsyncSession, strategy_id: str, status: str) -> None:
    await session.execute(
        text(
            "INSERT OR REPLACE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, :st, 30)"
        ),
        {"sid": strategy_id, "st": status},
    )
    await session.flush()


@pytest.fixture
async def d5_resume_success_setup(tmp_path: Path, monkeypatch):
    """
    D5：可恢复状态——PAUSED、无超仓（风控通过）。应用与测试共用同一 DB。
    """
    db_file = tmp_path / "test_d5_resume.db"
    db_url_sync = "sqlite:///" + str(db_file)
    db_url_async = "sqlite+aiosqlite:///" + str(db_file)

    Base.metadata.create_all(create_engine(db_url_sync))
    monkeypatch.setenv("DATABASE_URL", db_url_async)
    monkeypatch.setenv("TV_WEBHOOK_SECRET", D5_WEBHOOK_SECRET)
    monkeypatch.setenv("STRATEGY_ID", D5_STRATEGY_ID)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))

    from src.app.main import create_app
    app = create_app()

    engine = create_async_engine(
        db_url_async,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)

    async with get_db_session() as session:
        await _ensure_runtime_state(session, D5_STRATEGY_ID, STATUS_PAUSED)
        await session.commit()

    yield app, D5_STRATEGY_ID, D5_WEBHOOK_SECRET
    await engine.dispose()


@pytest.mark.asyncio
async def test_d5_resume_success_then_running_and_strategy_resumed_and_signal_accepted(d5_resume_success_setup):
    """
    D5 全链路：真实 B1 恢复成功 → 状态 RUNNING、STRATEGY_RESUMED 落库 → 恢复后信号可被正常接收。
    """
    app, strategy_id, secret = d5_resume_success_setup

    with TestClient(app) as client:
        response = client.post(f"/strategy/{strategy_id}/resume")

    assert response.status_code == 200, "D5: 强校验通过须返回 2xx"
    body = response.json()
    assert body.get("status") == "resumed"
    assert body.get("strategy_id") == strategy_id

    async with get_db_session() as session:
        state_repo = StrategyRuntimeStateRepository(session)
        state = await state_repo.get_by_strategy_id(strategy_id)
        assert state is not None
        assert getattr(state, "status", None) == STATUS_RUNNING, "D5: 状态须变为 RUNNING"

        log_repo = PositionReconcileLogRepository(session)
        logs = await log_repo.list_by_strategy(strategy_id, limit=10)
        resumed_logs = [l for l in logs if getattr(l, "event_type", None) == STRATEGY_RESUMED]
        assert len(resumed_logs) >= 1, "D5: STRATEGY_RESUMED 终态日志须已落库"

    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-02-05T14:00:00Z",
        "indicator_name": "D5",
        "strategy_id": strategy_id,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _make_signature(secret, payload_bytes)

    with TestClient(app) as client:
        signal_response = client.post(
            "/webhook/tradingview",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-TradingView-Signature": signature,
            },
        )

    assert signal_response.status_code == 200
    signal_data = signal_response.json()
    assert signal_data.get("status") == "accepted", "D5: 恢复后信号须可被正常接收"

    # D5.1：accepted 之后，DB 断言证明系统进入处理流程——decision_order_map 出现与本次 webhook 对应的 RESERVED 占位
    decision_id = signal_data.get("decision_id")
    signal_id_from_response = signal_data.get("signal_id")
    assert decision_id and signal_id_from_response, "D5.1: accepted 响应须含 decision_id 与 signal_id"
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        dom_row = await dom_repo.get_by_decision_id(decision_id)
    assert dom_row is not None, "D5.1: accepted 后须在 decision_order_map 中落库占位记录"
    assert dom_row.strategy_id == strategy_id, "D5.1: 占位记录 strategy_id 须与本次 webhook 一致"
    assert dom_row.signal_id == signal_id_from_response, "D5.1: 占位记录 signal_id 须与响应一致"
    # D6 证据补强：状态集合断言，验证 D5.1 锚点不破坏状态机——status 须为可推进状态之一（非 FAILED/TIMEOUT/UNKNOWN）
    actual_status = getattr(dom_row, "status", None)
    assert actual_status in D5_1_ANCHOR_ALLOWED_STATUSES, (
        f"D5.1/D6: decision_order_map 锚点状态须可正常推进，got {actual_status!r}, "
        f"allowed={D5_1_ANCHOR_ALLOWED_STATUSES}"
    )
