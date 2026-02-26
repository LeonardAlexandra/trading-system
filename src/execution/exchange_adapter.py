"""
交易所适配器（PR6 抽象接口 + Paper 实现；PR8 扩展 CreateOrderResult + Decimal qty；PR15c get_account_info）
"""
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from src.adapters.models import AccountInfo
from src.common.order_status import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_SUBMITTED,
    ORDER_STATUS_REJECTED,
)


@dataclass
class CreateOrderResult:
    """
    PR13 实盘级统一下单返回结构（place_order 语义）。
    必须返回：exchange_order_id、status、filled_qty（可选）、error（失败时）。
    status 仅从 order_status 常量取值；严禁存 raw payload/secret。
    PR15b：可选 http_status、okx_code、request_id 用于通信审计（OKX_HTTP_CREATE_ORDER）。
    """
    exchange_order_id: str
    client_order_id: str  # 必须回传，等于 decision_id
    status: str           # 仅取 order_status 常量
    filled_qty: Optional[Decimal] = None
    avg_price: Optional[Decimal] = None
    error: Optional[str] = None  # PR13：失败时人类可读原因，不含 secret
    raw: Optional[Dict[str, Any]] = None
    # PR15b：真实 HTTP 审计用，仅非敏感
    http_status: Optional[int] = None
    okx_code: Optional[str] = None
    request_id: Optional[str] = None


@dataclass
class GetOrderResult:
    """
    PR13 实盘级 get_order_status 返回结构。
    必须：exchange_order_id、status；可选 filled_qty、avg_price、error。
    PR15a：可选 http_status、okx_code、request_id 用于通信审计（不写 log/events 敏感信息）。
    """
    exchange_order_id: str
    status: str
    filled_qty: Optional[Decimal] = None
    avg_price: Optional[Decimal] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None
    # PR15a：真实 HTTP 审计用，仅非敏感
    http_status: Optional[int] = None
    okx_code: Optional[str] = None
    request_id: Optional[str] = None


@dataclass
class CancelOrderResult:
    """
    PR15a：cancel_order 统一返回结构，便于携带通信审计字段。
    """
    success: bool
    http_status: Optional[int] = None
    okx_code: Optional[str] = None
    request_id: Optional[str] = None


class ExchangeAdapter(ABC):
    """
    PR13 实盘级适配器接口边界。
    能力：place_order（即 create_order）、cancel_order、get_order_status（即 get_order）。
    必须返回字段：exchange_order_id、status、filled_qty、error（失败时）。
    异常：TransientOrderError = 可重试；PermanentOrderError = 不可重试。
    PaperExchangeAdapter 实现该接口作为 reference，不接真实交易所。
    """

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        client_order_id: str,
        **kwargs: Any,
    ) -> CreateOrderResult:
        """
        下单。client_order_id 必须为 decision_id，保证幂等。
        qty 使用 Decimal，禁止 raw payload/secret 写入返回。
        """
        pass

    @abstractmethod
    async def get_order(self, exchange_order_id: str, symbol: str) -> GetOrderResult:
        """
        PR12：按交易所订单号查询订单状态。
        symbol 用于真实交易所路由；Paper 可忽略。
        """
        pass

    @abstractmethod
    async def cancel_order(self, exchange_order_id: str, **kwargs: Any) -> "CancelOrderResult":
        """
        PR12：取消未完全成交的订单。PR15a：返回 CancelOrderResult 以携带审计字段。
        """
        pass

    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        """
        PR15c：获取账户信息（余额等），供风控使用。Paper 实现可返回 mock；无实现时由 AccountManager fallback 到 balance_repo。
        """
        pass

    def is_real_trading(self) -> bool:
        """
        PR16：是否真实交易所请求（OKX Demo/Live）。Paper/DryRun 返回 False，仅 OKX 返回 True。
        用于区分 Paper 与真实 HTTP，不用于门禁触发。
        """
        return False

    def is_live_endpoint(self) -> bool:
        """
        PR16：是否为 live 实盘 endpoint（非 Demo）。
        allow_real_trading / allowlist / confirm_token 仅当 is_live_endpoint=True 时校验；
        Demo rehearsal（OKX Demo HTTP）不触发上述门禁，不受 allow_real_trading 语义污染。
        PR16 仍不允许实盘，所有适配器返回 False。
        """
        return False


class PaperExchangeAdapter(ExchangeAdapter):
    """
    Phase1.0 纸面交易所：生成模拟 exchange_order_id，可配置是否必定成交。
    不连接真实交易所。PR12：内存存储订单状态，支持 get_order / cancel_order。
    """

    def __init__(self, *, filled: bool = True):
        self._filled = filled
        # PR12: 内存订单状态，key=exchange_order_id
        self._orders: Dict[str, Dict[str, Any]] = {}

    async def create_order(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        client_order_id: str,
        **kwargs: Any,
    ) -> CreateOrderResult:
        exchange_order_id = str(uuid.uuid4())
        status = ORDER_STATUS_FILLED if self._filled else ORDER_STATUS_SUBMITTED
        filled_qty = qty if self._filled else None
        self._orders[exchange_order_id] = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "status": status,
            "filled_qty": filled_qty,
            "avg_price": None,
        }
        return CreateOrderResult(
            exchange_order_id=exchange_order_id,
            client_order_id=client_order_id,
            status=status,
            filled_qty=filled_qty,
            avg_price=None,
            raw=None,
        )

    async def get_order(self, exchange_order_id: str, symbol: str) -> GetOrderResult:
        info = self._orders.get(exchange_order_id)
        if info is None:
            return GetOrderResult(
                exchange_order_id=exchange_order_id,
                status=ORDER_STATUS_FILLED,
                filled_qty=None,
                avg_price=None,
                raw=None,
            )
        return GetOrderResult(
            exchange_order_id=exchange_order_id,
            status=info["status"],
            filled_qty=info.get("filled_qty"),
            avg_price=info.get("avg_price"),
            raw=None,
        )

    async def cancel_order(self, exchange_order_id: str, **kwargs: Any) -> CancelOrderResult:
        info = self._orders.get(exchange_order_id)
        if info is None:
            return CancelOrderResult(success=True)
        if info["status"] == ORDER_STATUS_FILLED:
            return CancelOrderResult(success=False)
        info["status"] = ORDER_STATUS_CANCELLED
        info["filled_qty"] = None
        return CancelOrderResult(success=True)

    async def get_account_info(self) -> AccountInfo:
        """PR15c：Paper 模式 mock，默认 USDT 10000 可用。"""
        return AccountInfo(
            balances={
                "USDT": {"available": "10000", "total": "10000"},
            },
            equity=None,
        )


class DryRunExchangeAdapter(ExchangeAdapter):
    """
    PR13：Dry-run 包装器。全链路走 execution/风控/审计，但不下真实单。
    create_order 返回模拟成功，不调用内层；get_order/cancel_order 不调用内层（返回模拟）。
    """
    def __init__(self, inner: ExchangeAdapter):
        self._inner = inner

    async def create_order(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        client_order_id: str,
        **kwargs: Any,
    ) -> CreateOrderResult:
        exchange_order_id = f"dry_run_{uuid.uuid4().hex[:12]}"
        return CreateOrderResult(
            exchange_order_id=exchange_order_id,
            client_order_id=client_order_id,
            status=ORDER_STATUS_FILLED,
            filled_qty=qty,
            avg_price=None,
            error=None,
            raw=None,
        )

    async def get_order(self, exchange_order_id: str, symbol: str) -> GetOrderResult:
        return GetOrderResult(
            exchange_order_id=exchange_order_id,
            status=ORDER_STATUS_FILLED,
            filled_qty=None,
            avg_price=None,
            error=None,
            raw=None,
        )

    async def cancel_order(self, exchange_order_id: str, **kwargs: Any) -> CancelOrderResult:
        return CancelOrderResult(success=True)

    async def get_account_info(self) -> AccountInfo:
        """PR15c：透传内层账户信息。"""
        return await self._inner.get_account_info()
