"""
PR16：参数精度与数量校验集成测试。
qty=0 / 负数 / 超精度 → ORDER_REJECTED，不产生 OKX_HTTP_CREATE_ORDER。
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.worker_config import WorkerConfig
from src.config.app_config import (
    AppConfig,
    DatabaseConfig,
    LoggingConfig,
    WebhookConfig,
    ExecutionConfig,
    RiskSectionConfig,
    ExchangeConfig,
    StrategyEntryConfig,
)
from src.common.event_types import ORDER_REJECTED as EV_ORDER_REJECTED
from src.common.reason_codes import ORDER_QTY_ZERO_OR_NEGATIVE, ORDER_QTY_PRECISION_EXCEEDED


def _app_config(db_url=None):
    return AppConfig(
        database=DatabaseConfig(url=db_url or "sqlite+aiosqlite:///./pr16_param.db"),
        logging=LoggingConfig(),
        webhook=WebhookConfig(),
        execution=ExecutionConfig(
            dry_run=False,
            order_qty_precision=8,
        ),
        risk=RiskSectionConfig(cooldown_mode="after_fill"),
        exchange=ExchangeConfig(mode="paper"),
        strategies={"strat-1": StrategyEntryConfig(enabled=True)},
    )


@pytest.fixture
def pr16_param_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def pr16_param_db_url(pr16_param_tmp_path):
    return "sqlite+aiosqlite:///" + (pr16_param_tmp_path / "pr16_param.db").as_posix()


@pytest.fixture
def pr16_param_sync_url(pr16_param_tmp_path):
    return "sqlite:///" + (pr16_param_tmp_path / "pr16_param.db").as_posix()


@pytest.fixture
def pr16_param_schema(pr16_param_sync_url):
    engine = create_engine(pr16_param_sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def pr16_param_session_factory(pr16_param_db_url, pr16_param_schema):
    engine = create_async_engine(pr16_param_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_qty_zero_rejected_no_http(pr16_param_session_factory, pr16_param_db_url):
    """qty=0 时本地拒绝，ORDER_REJECTED，不触发 create_order。"""
    app_config = _app_config(db_url=pr16_param_db_url)
    now = datetime.now(timezone.utc)
    decision_id = "pr16-qty-zero-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-1",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("0"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=WorkerConfig.from_app_config(app_config),
            app_config=app_config,
        )
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "failed"
    assert result.get("reason_code") == ORDER_QTY_ZERO_OR_NEGATIVE
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
    order_rejected = [e for e in events if e.event_type == EV_ORDER_REJECTED]
    assert len(order_rejected) >= 1
    assert order_rejected[0].reason_code == ORDER_QTY_ZERO_OR_NEGATIVE


@pytest.mark.asyncio
async def test_qty_precision_exceeded_rejected(pr16_param_session_factory, pr16_param_db_url):
    """qty 小数位超过配置时本地拒绝。"""
    app_config = _app_config(db_url=pr16_param_db_url)
    app_config.execution.order_qty_precision = 4
    now = datetime.now(timezone.utc)
    decision_id = "pr16-precision-001"
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-1",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1.12345"),
        )
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(
            dom_repo,
            PaperExchangeAdapter(filled=True),
            RiskManager(),
            config=WorkerConfig.from_app_config(app_config),
            app_config=app_config,
        )
        result = await engine.execute_one(decision_id)
    assert result.get("status") == "failed"
    assert result.get("reason_code") == ORDER_QTY_PRECISION_EXCEEDED
