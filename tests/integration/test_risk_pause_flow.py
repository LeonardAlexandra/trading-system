"""
Phase1.1 D3：风控失败 → 挂起全链路测试（C4 → C5 → C6）

跨模块集成测试：验证 full_check 不通过 → PAUSED + STRATEGY_PAUSED 终态日志（同事务）
→ 挂起后新信号返回 HTTP 200 + status=rejected, reason=STRATEGY_PAUSED。
不 mock C5/C6，真实调用 RiskManager full_check 与 pause_strategy。
"""
import base64
import hashlib
import hmac
import json
import pytest
from decimal import Decimal
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import create_engine
from fastapi.testclient import TestClient

from src.app.dependencies import get_db_session, set_session_factory
from src.database.connection import Base
from src.execution.position_manager import PositionManager, ReconcileItem
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.execution.strategy_manager import pause_strategy
from src.models.strategy_runtime_state import StrategyRuntimeState, STATUS_PAUSED
from src.models.position_reconcile_log import PositionReconcileLog, STRATEGY_PAUSED
from src.repositories.trade_repo import TradeRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository

from tests.fixtures.risk_pause_fixtures import (
    D3_STRATEGY_ID,
    risk_config_that_fails,
    reconcile_item_that_triggers_risk_fail,
)

# 与 webhook 验签一致
D3_WEBHOOK_SECRET = "d3_risk_pause_webhook_secret"


def _make_signature(secret: str, payload_bytes: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    ).decode("utf-8")


async def _ensure_runtime_state(session: AsyncSession, strategy_id: str) -> None:
    await session.execute(
        text(
            "INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, 'RUNNING', 30)"
        ),
        {"sid": strategy_id},
    )
    await session.flush()


@pytest.fixture
async def d3_risk_pause_setup(tmp_path: Path, monkeypatch):
    """
    D3 全链路前置：文件 DB + 应用配置 + 执行 reconcile 触发风控失败 → pause（C4→C5→C6）。
    应用与测试共用同一 DB 文件，以便后续 webhook 请求读到 PAUSED 状态。
    """
    db_file = tmp_path / "test_d3.db"
    db_url_sync = "sqlite:///" + str(db_file)
    db_url_async = "sqlite+aiosqlite:///" + str(db_file)

    Base.metadata.create_all(create_engine(db_url_sync))
    monkeypatch.setenv("DATABASE_URL", db_url_async)
    monkeypatch.setenv("TV_WEBHOOK_SECRET", D3_WEBHOOK_SECRET)
    monkeypatch.setenv("STRATEGY_ID", D3_STRATEGY_ID)
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
        await _ensure_runtime_state(session, D3_STRATEGY_ID)
        await session.commit()

    async with get_db_session() as session:
        async with session.begin():
            trade_repo = TradeRepository(session)
            position_repo = PositionRepository(session)
            log_repo = PositionReconcileLogRepository(session)
            state_repo = StrategyRuntimeStateRepository(session)
            risk_manager = RiskManager(
                position_repo=position_repo,
                risk_config=risk_config_that_fails(),
            )
            pm = PositionManager(trade_repo, position_repo, log_repo)

            async def on_risk_check_failed(sid: str, reason_code: str, message: str):
                await pause_strategy(
                    session,
                    sid,
                    reason_code,
                    message,
                    state_repo=state_repo,
                    reconcile_log_repo=log_repo,
                    position_repo=position_repo,
                    lock_holder_id="d3-test",
                )

            out = await pm.reconcile(
                session,
                D3_STRATEGY_ID,
                [reconcile_item_that_triggers_risk_fail()],
                lock_holder_id="d3-test",
                risk_manager=risk_manager,
                on_risk_check_failed=on_risk_check_failed,
            )

    assert out["risk_check_passed"] is False, "D3: full_check must fail to trigger pause"
    assert out.get("risk_reason_code") == "POSITION_LIMIT_EXCEEDED"

    yield app, D3_STRATEGY_ID, D3_WEBHOOK_SECRET
    await engine.dispose()


@pytest.mark.asyncio
async def test_d3_full_chain_paused_and_log_and_signal_rejected(d3_risk_pause_setup):
    """
    D3：风控失败 → PAUSED + STRATEGY_PAUSED 终态日志（同事务）→ 挂起后新信号 HTTP 200 + rejected。
    断言：状态 PAUSED、终态日志存在且含可解析差异快照、无部分成功、新信号被拒绝且返回 200。
    """
    app, strategy_id, secret = d3_risk_pause_setup

    # ---------- 断言 PAUSED 与 STRATEGY_PAUSED 终态日志（D3-03, D3-04, D3-05, D3-06）----------
    async with get_db_session() as session:
        state_repo = StrategyRuntimeStateRepository(session)
        state = await state_repo.get_by_strategy_id(strategy_id)
        assert state is not None, "D3: strategy_runtime_state row must exist"
        assert getattr(state, "status", None) == STATUS_PAUSED, (
            "D3: status must be PAUSED after risk fail"
        )

        log_repo = PositionReconcileLogRepository(session)
        logs = await log_repo.list_by_strategy(strategy_id, limit=20)
        paused_logs = [l for l in logs if getattr(l, "event_type", None) == STRATEGY_PAUSED]
        assert len(paused_logs) >= 1, "D3: STRATEGY_PAUSED log must exist"
        log_row = paused_logs[0]
        assert getattr(log_row, "diff_snapshot", None), "D3: STRATEGY_PAUSED must contain diff_snapshot (C6)"
        raw = (log_row.diff_snapshot or "").strip()
        assert len(raw) > 0, "D3: diff_snapshot non-empty"
        snapshot = json.loads(raw)
        assert isinstance(snapshot, dict), "D3: diff_snapshot must be parseable dict/JSON"
        assert "reason_code" in snapshot
        assert snapshot["reason_code"] == "POSITION_LIMIT_EXCEEDED"
        assert "positions" in snapshot

    # ---------- 断言无部分成功：有 PAUSED 必有终态日志，上面已同时断言 ----------
    # （不存在“仅有 PAUSED 无日志”或“仅有日志无 PAUSED”）

    # ---------- 断言挂起后新信号返回 HTTP 200 + status=rejected, reason=STRATEGY_PAUSED（D3-02）----------
    payload = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-02-05T12:00:00Z",
        "indicator_name": "D3",
        "strategy_id": strategy_id,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _make_signature(secret, payload_bytes)

    with TestClient(app) as client:
        response = client.post(
            "/webhook/tradingview",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-TradingView-Signature": signature,
            },
        )

    assert response.status_code == 200, "D3: PAUSED 时信号必须返回 200，不得 4xx/5xx"
    data = response.json()
    assert data.get("status") == "rejected", "D3: body 必须包含 status=rejected"
    assert data.get("reason") == "STRATEGY_PAUSED", "D3: body 必须包含 reason=STRATEGY_PAUSED"


@pytest.mark.asyncio
async def test_d3_no_partial_success_state_without_log(d3_risk_pause_setup):
    """
    D3-06：不存在“状态 PAUSED 但无 STRATEGY_PAUSED 终态日志”。
    """
    app, strategy_id, secret = d3_risk_pause_setup
    async with get_db_session() as session:
        state_repo = StrategyRuntimeStateRepository(session)
        state = await state_repo.get_by_strategy_id(strategy_id)
        log_repo = PositionReconcileLogRepository(session)
        logs = await log_repo.list_by_strategy(strategy_id, limit=20)
        paused_logs = [l for l in logs if getattr(l, "event_type", None) == STRATEGY_PAUSED]
        if state and getattr(state, "status", None) == STATUS_PAUSED:
            assert len(paused_logs) >= 1, "D3-06: PAUSED 时必须有 STRATEGY_PAUSED 日志"
        if len(paused_logs) >= 1:
            assert state is not None and getattr(state, "status", None) == STATUS_PAUSED, (
                "D3-06: 有 STRATEGY_PAUSED 日志时状态必须为 PAUSED"
            )
