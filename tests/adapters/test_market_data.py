"""
PR15c：MarketDataAdapter 单元测试。
- 能获取配置价格并返回 MarketData
- 当 symbol 无配置价格时抛 MarketDataError
- 模拟超时/异常时抛 MarketDataError
"""
import asyncio
import pytest

from src.adapters.market_data import MarketDataAdapter
from src.adapters.models import MarketData, MarketDataError


@pytest.mark.asyncio
async def test_get_market_data_returns_configured_price():
    """有 paper.prices[symbol] 时返回 MarketData。"""
    config = {"paper": {"prices": {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0}}}
    adapter = MarketDataAdapter(exchange_config=config, exchange_adapter=None, timeout_seconds=5.0)
    result = await adapter.get_market_data("BTCUSDT")
    assert isinstance(result, MarketData)
    assert result.symbol == "BTCUSDT"
    assert result.last_price == 50000.0

    result2 = await adapter.get_market_data("ETHUSDT")
    assert result2.symbol == "ETHUSDT"
    assert result2.last_price == 3000.0


@pytest.mark.asyncio
async def test_get_market_data_no_config_price_raises():
    """symbol 无配置价格时抛 MarketDataError。"""
    config = {"paper": {"prices": {"BTCUSDT": 50000.0}}}
    adapter = MarketDataAdapter(exchange_config=config, exchange_adapter=None, timeout_seconds=5.0)
    with pytest.raises(MarketDataError) as exc_info:
        await adapter.get_market_data("UNKNOWN")
    assert "no configured price" in str(exc_info.value).lower() or "unknown" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_get_market_data_empty_prices_raises():
    """paper.prices 为空或缺少 symbol 时抛 MarketDataError。"""
    adapter = MarketDataAdapter(exchange_config={"paper": {"prices": {}}}, exchange_adapter=None, timeout_seconds=5.0)
    with pytest.raises(MarketDataError):
        await adapter.get_market_data("BTCUSDT")


@pytest.mark.asyncio
async def test_get_market_data_timeout_raises():
    """超时时抛 MarketDataError。"""
    async def slow_impl(_symbol):
        await asyncio.sleep(10.0)
        raise RuntimeError("unreachable")

    class SlowAdapter(MarketDataAdapter):
        async def _get_market_data_impl(self, symbol: str):
            return await slow_impl(symbol)

    # 用极短超时触发 TimeoutError
    adapter = SlowAdapter(exchange_config={}, exchange_adapter=None, timeout_seconds=0.01)
    with pytest.raises(MarketDataError) as exc_info:
        await adapter.get_market_data("BTCUSDT")
    assert "timeout" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_get_market_data_exception_wrapped():
    """内部异常被封装为 MarketDataError。"""
    class FailingAdapter(MarketDataAdapter):
        async def _get_market_data_impl(self, symbol: str):
            raise ValueError("network error")

    adapter = FailingAdapter(exchange_config={}, exchange_adapter=None, timeout_seconds=5.0)
    with pytest.raises(MarketDataError) as exc_info:
        await adapter.get_market_data("BTCUSDT")
    assert "failed" in str(exc_info.value).lower() or "network" in str(exc_info.value).lower()
