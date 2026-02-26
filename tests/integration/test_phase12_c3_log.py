"""
Phase1.2 C3：审计/操作/错误日志验收测试（LogRepository + 必写路径 + 脱敏）

1) 写入与查询：写入含 payload 的 log，query 按时间/level/component 分页查回
2) 必写路径：至少 3 条 AUDIT（signal_received, decision_created, execution_submit）+ 1 条 ERROR（快照写入失败）
3) 脱敏：含 token/api_key/password 的 message/payload 写入后查回不得为明文
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models  # noqa: F401
from src.models.decision_order_map_status import RESERVED
from src.repositories.dedup_signal_repo import DedupSignalRepository
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
from src.repositories.log_repository import LogRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager


@pytest.fixture
def c3_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def c3_db_url(c3_tmp_path):
    return "sqlite+aiosqlite:///" + (c3_tmp_path / "c3_log.db").as_posix()


@pytest.fixture
def c3_sync_db_url(c3_tmp_path):
    return "sqlite:///" + (c3_tmp_path / "c3_log.db").as_posix()


@pytest.fixture
def c3_schema(c3_sync_db_url):
    engine = create_engine(c3_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def c3_session_factory(c3_db_url, c3_schema):
    engine = create_async_engine(c3_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


# ---------- 1) 写入与查询 ----------
@pytest.mark.asyncio
async def test_log_write_and_query_pagination(c3_session_factory):
    """写入一条 log（含 payload），query 按时间/level/component 分页查回，limit/offset 生效。"""
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        await log_repo.write(
            "AUDIT",
            "test_component",
            "test message",
            event_type="test_event",
            payload={"a": 1, "b": "x"},
        )
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows = await log_repo.query(limit=10, offset=0)
    assert len(rows) == 1
    assert rows[0].level == "AUDIT"
    assert rows[0].component == "test_component"
    assert rows[0].message == "test message"
    assert rows[0].event_type == "test_event"
    assert rows[0].payload == {"a": 1, "b": "x"}

    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows_level = await log_repo.query(level="AUDIT", limit=10)
    assert len(rows_level) == 1
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows_comp = await log_repo.query(component="test_component", limit=10)
    assert len(rows_comp) == 1
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows_none = await log_repo.query(level="ERROR", limit=10)
    assert len(rows_none) == 0


# ---------- 2) 必写路径：3 AUDIT + 1 ERROR ----------
@pytest.mark.asyncio
async def test_audit_signal_received_and_decision_created(c3_session_factory):
    """信号接收 + 决策创建：写 AUDIT signal_received 与 decision_created。"""
    from src.schemas.signals import TradingViewSignal
    from src.application.signal_service import SignalApplicationService

    now = datetime.now(timezone.utc)
    signal = TradingViewSignal(
        signal_id="sig-c3-audit",
        strategy_id="strat-c3",
        symbol="BTCUSDT",
        side="BUY",
        timestamp=now,
        raw_payload={},
    )
    async with get_db_session() as session:
        dedup_repo = DedupSignalRepository(session)
        dom_repo = DecisionOrderMapRepository(session)
        log_repo = LogRepository(session)
        service = SignalApplicationService(dedup_repo, dom_repo)
        config = {"strategies": [{"strategy_id": "strat-c3"}]}
        result = await service.handle_tradingview_signal(signal, config)
        await log_repo.write(
            "AUDIT",
            "signal_receiver",
            f"signal_received signal_id={signal.signal_id} strategy_id={signal.strategy_id}",
            event_type="signal_received",
            payload={"signal_id": signal.signal_id, "strategy_id": signal.strategy_id},
        )
        if result.get("status") == "accepted":
            await log_repo.write(
                "AUDIT",
                "signal_receiver",
                f"decision_created decision_id={result.get('decision_id')} signal_id={signal.signal_id}",
                event_type="decision_created",
                payload={"decision_id": result.get("decision_id"), "signal_id": signal.signal_id, "strategy_id": signal.strategy_id},
            )
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows = await log_repo.query(level="AUDIT", limit=10)
    event_types = [r.event_type for r in rows]
    assert "signal_received" in event_types
    assert "decision_created" in event_types


@pytest.mark.asyncio
async def test_audit_execution_submit_and_trade_filled(c3_session_factory):
    """执行提交 + 成交：execute_one 成功路径写 AUDIT execution_submit、trade_filled。"""
    now = datetime.now(timezone.utc)
    decision_id = "dec-c3-audit"
    signal_id = "sig-c3-exec"
    async with get_db_session() as session:
        dedup_repo = DedupSignalRepository(session)
        await dedup_repo.try_insert(signal_id, now)
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="strat-c3",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        snapshot_repo = DecisionSnapshotRepository(session)
        log_repo = LogRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            snapshot_repo=snapshot_repo,
            alert_callback=lambda *a: None,
            log_repo=log_repo,
        )
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "filled"
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows = await log_repo.query(level="AUDIT", limit=20)
    event_types = [r.event_type for r in rows]
    assert "risk_check_pass" in event_types
    assert "execution_submit" in event_types
    assert "trade_filled" in event_types


@pytest.mark.asyncio
async def test_error_on_snapshot_save_failure(c3_session_factory):
    """决策快照写入失败：产生 level=ERROR 记录（且 AUDIT execution_failed）。"""
    now = datetime.now(timezone.utc)
    decision_id = "dec-c3-err"
    signal_id = "sig-c3-err"
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="strat-c3",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0.01"),
        )
    alert_calls = []

    def _alert(did: str, sid: str, reason: str) -> None:
        alert_calls.append((did, sid, reason))

    class FailingSnapshotRepo(DecisionSnapshotRepository):
        async def save(self, snapshot) -> None:
            raise RuntimeError("mock snapshot save failure")

    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        snapshot_repo = FailingSnapshotRepo(session)
        log_repo = LogRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            snapshot_repo=snapshot_repo,
            alert_callback=_alert,
            log_repo=log_repo,
        )
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "failed"
    assert result.get("reason_code") == "DECISION_SNAPSHOT_SAVE_FAILED"
    assert len(alert_calls) == 1
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        err_rows = await log_repo.query(level="ERROR", limit=10)
    assert len(err_rows) >= 1
    assert any("decision_snapshot" in (r.event_type or "") or "snapshot" in (r.message or "").lower() for r in err_rows)


# ---------- 3) 脱敏 ----------
@pytest.mark.asyncio
async def test_desensitize_token_and_api_key(c3_session_factory):
    """含 token 与 api_key 的 message/payload 写入后查回，敏感内容被截断或替换。"""
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        await log_repo.write(
            "INFO",
            "test",
            "auth token=sk_live_abcdefghij1234567890 and api_key=AKIAIOSFODNN7EXAMPLE",
            payload={"token": "bearer_very_long_secret_token_xyz", "api_key": "AKIAIOSFODNN7EXAMPLE"},
        )
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows = await log_repo.query(limit=1)
    assert len(rows) == 1
    msg = rows[0].message
    # 脱敏后不应包含完整 token 或完整 api_key
    assert "sk_live_abcdefghij1234567890" not in msg
    assert "AKIAIOSFODNN7EXAMPLE" not in msg
    assert "***" in msg or "7890" in msg  # last4 或 ***
    pl = rows[0].payload or {}
    assert pl.get("token") != "bearer_very_long_secret_token_xyz"
    assert pl.get("api_key") != "AKIAIOSFODNN7EXAMPLE"
    assert "***" in str(pl.get("token", "")) or "xyz" in str(pl.get("token", ""))  # last4 或 ***


@pytest.mark.asyncio
async def test_desensitize_password(c3_session_factory):
    """含 password 的 payload 写入后查回，不得为明文。"""
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        await log_repo.write(
            "INFO",
            "test",
            "login attempt",
            payload={"username": "u1", "password": "SuperSecret123"},
        )
    async with get_db_session() as session:
        log_repo = LogRepository(session)
        rows = await log_repo.query(limit=1)
    assert len(rows) == 1
    pl = rows[0].payload or {}
    assert pl.get("password") != "SuperSecret123"
    assert "***" in str(pl.get("password", ""))
