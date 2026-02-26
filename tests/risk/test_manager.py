"""
PR15c：RiskManager 余额/敞口检查单元测试。
- enable_balance_checks=true 且余额不足 => 拒绝，reason 包含 insufficient balance
- enable_balance_checks=false => 不做余额检查，保持通过
"""
from decimal import Decimal
from types import SimpleNamespace
import pytest

from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.common.reason_codes import INSUFFICIENT_BALANCE


@pytest.fixture
def decision_buy():
    """BUY 1 qty 的 decision 对象。"""
    return SimpleNamespace(
        decision_id="test-d-1",
        strategy_id="strat-1",
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("1"),
    )


@pytest.mark.asyncio
async def test_balance_checks_reject_when_insufficient(decision_buy):
    """enable_balance_checks=true 且余额不足 => RiskManager 拒绝，reason 含 insufficient balance。"""
    class SmallBalanceAdapter:
        async def get_account_info(self):
            from src.adapters.models import AccountInfo
            return AccountInfo(balances={"USDT": {"available": "10", "total": "10"}}, equity=None)

    class PriceAdapter:
        async def get_market_data(self, symbol: str):
            from src.adapters.models import MarketData
            return MarketData(symbol=symbol, last_price=100.0, orderbook=None)

    risk_config = RiskConfig(enable_balance_checks=True, quote_asset_for_balance="USDT")
    risk = RiskManager(
        risk_config=risk_config,
        account_manager=SmallBalanceAdapter(),
        market_data_adapter=PriceAdapter(),
    )
    result = await risk.check(decision_buy)
    assert result.get("allowed") is False
    assert result.get("reason_code") == INSUFFICIENT_BALANCE
    assert "insufficient balance" in (result.get("message") or "").lower()


@pytest.mark.asyncio
async def test_balance_checks_disabled_pass(decision_buy):
    """enable_balance_checks=false 时不检查余额，保持通过（其他规则未触发时）。"""
    class SmallBalanceAdapter:
        async def get_account_info(self):
            from src.adapters.models import AccountInfo
            return AccountInfo(balances={"USDT": {"available": "10", "total": "10"}}, equity=None)

    class PriceAdapter:
        async def get_market_data(self, symbol: str):
            from src.adapters.models import MarketData
            return MarketData(symbol=symbol, last_price=100.0, orderbook=None)

    risk_config = RiskConfig(enable_balance_checks=False)
    risk = RiskManager(
        risk_config=risk_config,
        account_manager=SmallBalanceAdapter(),
        market_data_adapter=PriceAdapter(),
    )
    result = await risk.check(decision_buy)
    assert result.get("allowed") is True
    assert result.get("reason_code") is None


@pytest.mark.asyncio
async def test_balance_checks_pass_when_sufficient(decision_buy):
    """enable_balance_checks=true 且余额充足 => 通过。"""
    class SufficientBalanceAdapter:
        async def get_account_info(self):
            from src.adapters.models import AccountInfo
            return AccountInfo(balances={"USDT": {"available": "10000", "total": "10000"}}, equity=None)

    class PriceAdapter:
        async def get_market_data(self, symbol: str):
            from src.adapters.models import MarketData
            return MarketData(symbol=symbol, last_price=100.0, orderbook=None)

    risk_config = RiskConfig(enable_balance_checks=True, quote_asset_for_balance="USDT")
    risk = RiskManager(
        risk_config=risk_config,
        account_manager=SufficientBalanceAdapter(),
        market_data_adapter=PriceAdapter(),
    )
    result = await risk.check(decision_buy)
    assert result.get("allowed") is True
    assert result.get("reason_code") is None
