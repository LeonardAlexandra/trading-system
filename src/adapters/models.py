"""
PR8/PR9/PR15c：市场数据与账户信息模型（Phase1.0 遗漏接口补齐）
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


class MarketDataError(Exception):
    """行情获取失败（超时、网络、无配置价格等）。"""
    pass


class AccountInfoError(Exception):
    """账户信息获取失败（交易所/余额库不可用等）。"""
    pass


@dataclass
class MarketData:
    """PR8：市场数据（价格、订单簿）。"""
    symbol: str
    last_price: float
    orderbook: Optional[Dict[str, List[Any]]] = None  # bids / asks，结构可简化


@dataclass
class AccountInfo:
    """PR9：账户信息（余额、权益）。"""
    balances: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # asset -> {available, total}
    equity: Optional[Decimal] = None
