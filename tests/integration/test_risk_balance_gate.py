"""
PR15c：集成测试——开启资金检查时余额不足会拒单。
启动执行链路时设置 risk.enable_balance_checks=true，并注入小 USDT 余额；
执行 BUY 决策后断言为风控拒绝（FAILED/INSUFFICIENT_BALANCE），且未创建订单（无 FILLED）。
"""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models
from src.models.decision_order_map_status import RESERVED, FILLED, FAILED
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.balance_repository import BalanceRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.adapters.market_data import MarketDataAdapter
from src.account.manager import AccountManager
from src.common.reason_codes import INSUFFICIENT_BALANCE


@pytest.fixture
def gate_tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def gate_db_url(gate_tmp_path):
    return "sqlite+aiosqlite:///" + (gate_tmp_path / "gate.db").as_posix()


@pytest.fixture
def gate_sync_db_url(gate_tmp_path):
    return "sqlite:///" + (gate_tmp_path / "gate.db").as_posix()


@pytest.fixture
def gate_schema(gate_sync_db_url):
    engine = create_engine(gate_sync_db_url)
    Base.metadata.create_all(engine)
    engine.dispose()


@pytest.fixture
async def gate_session_factory(gate_db_url, gate_schema):
    engine = create_async_engine(gate_db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_risk_balance_gate_rejects_when_insufficient(gate_session_factory):
    """
    开启资金检查且 USDT 可用余额很小：BUY 决策执行后风控拒绝，无订单/成交。
    - 预置 RESERVED decision BUY 1 BTCUSDT
    - 预置 balance_repo 中 USDT=10
    - market_data 价格 100 => notional=100 > 10
    - RiskManager enable_balance_checks=true，account_manager 从 balance_repo 取余额
    - 断言 status=failed, reason_code=INSUFFICIENT_BALANCE，decision 终态 FAILED，无 FILLED
    """
    now = datetime.now(timezone.utc)
    decision_id = "test-risk-balance-gate-001"

    # 预置余额 USDT=10（供 AccountManager fallback）
    async with get_db_session() as session:
        balance_repo = BalanceRepository(session)
        await balance_repo.upsert("USDT", Decimal("10"))

    # 预置 RESERVED decision
    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        await repo.create_reserved(
            decision_id=decision_id,
            signal_id="sig-gate-1",
            strategy_id="strat-1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=now,
            quantity=Decimal("1"),
        )

    # Exchange 需 get_account_info 失败才会走 balance_repo；Paper 默认返回 10000，所以用自定义 adapter 抛异常
    class AdapterThatFailsAccountInfo(PaperExchangeAdapter):
        async def get_account_info(self):
            from src.adapters.models import AccountInfoError
            raise AccountInfoError("use balance_repo")

    exchange = AdapterThatFailsAccountInfo(filled=True)
    exchange_config = {"paper": {"prices": {"BTCUSDT": 100.0}}}
    market_data_adapter = MarketDataAdapter(
        exchange_config=exchange_config,
        exchange_adapter=exchange,
        timeout_seconds=3.0,
    )

    async with get_db_session() as session:
        balance_repo = BalanceRepository(session)
        account_manager = AccountManager(exchange_adapter=exchange, balance_repo=balance_repo)
        risk_config = RiskConfig(enable_balance_checks=True, quote_asset_for_balance="USDT")
        risk = RiskManager(
            risk_config=risk_config,
            account_manager=account_manager,
            market_data_adapter=market_data_adapter,
        )
        dom_repo = DecisionOrderMapRepository(session)
        engine = ExecutionEngine(dom_repo, exchange, risk)
        result = await engine.execute_one(decision_id)

    assert result.get("status") == "failed"
    assert result.get("reason_code") == INSUFFICIENT_BALANCE

    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        row = await repo.get_by_decision_id(decision_id)
        assert row is not None
        assert row.status == FAILED
        assert row.last_error == INSUFFICIENT_BALANCE
        # 风控拒绝未下单，无 exchange_order_id 或 status 非 FILLED
        assert row.status != FILLED
