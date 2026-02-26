"""
Signal DTO / Schema（PR4：仅接收与解析，不落库）
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Union


@dataclass(frozen=True)
class TradingViewSignal:
    """标准化 TradingView Webhook 信号（仅解析结果，PR4 不落库）。PR11：payload 必须含 strategy_id。"""

    signal_id: str
    strategy_id: str  # PR11：来自 payload，必填
    symbol: str
    side: str
    timestamp: datetime
    raw_payload: Union[dict, bytes]
    source: Literal["tradingview"] = "tradingview"
