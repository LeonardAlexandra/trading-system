"""
PR8/PR15c：行情适配器（Phase1.0 遗漏接口补齐）
Paper 模式下从配置价格或 exchange_adapter 获取行情；超时与异常统一封装为 MarketDataError。
"""
import asyncio
from typing import Any, Dict, Optional

from src.adapters.models import MarketData, MarketDataError


class MarketDataAdapter:
    """
    PR8：获取市场数据（价格、订单簿）。
    Phase1.0 paper 模式：若 exchange_adapter 无 ticker/orderbook 能力，则从 exchange_config["paper"]["prices"][symbol] 读取；
    若无则抛 MarketDataError。超时与网络异常统一封装为 MarketDataError。
    """

    def __init__(
        self,
        exchange_config: Dict[str, Any],
        exchange_adapter: Optional[Any] = None,
        timeout_seconds: float = 3.0,
    ):
        self._config = exchange_config or {}
        self._adapter = exchange_adapter
        self._timeout = timeout_seconds

    async def get_market_data(self, symbol: str) -> MarketData:
        """
        获取行情。超时或异常时抛 MarketDataError。
        Paper 模式：优先从 config["paper"]["prices"][symbol] 取 last_price；若无则抛 MarketDataError。
        """
        try:
            return await asyncio.wait_for(
                self._get_market_data_impl(symbol),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise MarketDataError(f"get_market_data timeout for {symbol}")
        except MarketDataError:
            raise
        except Exception as e:
            raise MarketDataError(f"get_market_data failed: {e}") from e

    async def _get_market_data_impl(self, symbol: str) -> MarketData:
        # 若 adapter 提供 get_ticker/get_market_data 则调用（Phase1.0 多数 adapter 无）
        if self._adapter is not None and hasattr(self._adapter, "get_market_data"):
            return await self._adapter.get_market_data(symbol)
        # Paper 模式：从配置读取价格
        paper = self._config.get("paper") or self._config.get("exchange") or {}
        if isinstance(paper, dict):
            prices = paper.get("prices") or {}
        else:
            prices = {}
        price_val = prices.get(symbol)
        if price_val is None:
            raise MarketDataError(f"no configured price for symbol {symbol}")
        try:
            last_price = float(price_val)
        except (TypeError, ValueError):
            raise MarketDataError(f"invalid price for symbol {symbol}: {price_val}")
        return MarketData(symbol=symbol, last_price=last_price, orderbook=None)
