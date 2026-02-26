"""
PR14b：OKX Exchange Adapter（仅 Demo/Sandbox）；
PR15b：开放 create_order 真实 HTTP（仅 demo），与 get_order/cancel_order 形成闭环。
"""
from decimal import Decimal
from typing import Any, Dict, Optional

from src.adapters.models import AccountInfo, AccountInfoError
from src.execution.exchange_adapter import (
    ExchangeAdapter,
    CreateOrderResult,
    GetOrderResult,
    CancelOrderResult,
)
from src.execution.okx_client import OkxHttpClient
from src.execution.exceptions import TransientOrderError, PermanentOrderError
from src.common.order_status import (
    ORDER_STATUS_FILLED,
    ORDER_STATUS_SUBMITTED,
    ORDER_STATUS_REJECTED,
    ORDER_STATUS_CANCELLED,
)

# PR15b：最小订单类型（仅市价单，与 Phase1 一致）
_OKX_ORD_TYPE_MARKET = "market"

# OKX API v5 订单状态 -> 统一 OrderStatus
_OKX_STATE_TO_STATUS = {
    "live": ORDER_STATUS_SUBMITTED,
    "partially_filled": ORDER_STATUS_SUBMITTED,
    "filled": ORDER_STATUS_FILLED,
    "canceled": ORDER_STATUS_CANCELLED,
    "cancelled": ORDER_STATUS_CANCELLED,
    "rejected": ORDER_STATUS_REJECTED,
}


def _okx_status_to_unified(okx_state: str) -> str:
    s = (okx_state or "").strip().lower()
    return _OKX_STATE_TO_STATUS.get(s, ORDER_STATUS_SUBMITTED)


def _parse_decimal(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


class OkxExchangeAdapter(ExchangeAdapter):
    """
    OKX API v5 适配器（Demo 与 Live）。
    通过注入 OkxHttpClient 实现，测试时使用 FakeOkxHttpClient 不访问网络。
    PR17b：live_endpoint=True 时 is_live_endpoint 返回 True，走 live 门禁与风险限制。
    """

    def __init__(
        self,
        http_client: OkxHttpClient,
        api_key: str,
        secret: str,
        passphrase: str,
        *,
        live_endpoint: bool = False,
    ):
        self._client = http_client
        self._api_key = api_key
        self._secret = secret
        self._passphrase = passphrase
        self._live_endpoint = live_endpoint

    def is_real_trading(self) -> bool:
        """PR16：OKX 适配器会发起真实 HTTP（Demo/Live）。"""
        return True

    def is_live_endpoint(self) -> bool:
        """PR16/PR17b：仅当连接 live 实盘 endpoint 时为 True；Demo rehearsal 不触发 allow_real_trading 等门禁。"""
        return self._live_endpoint

    def _request_path(self, path: str) -> str:
        if path.startswith("/"):
            return path
        return "/" + path

    async def create_order(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        client_order_id: str,
        **kwargs: Any,
    ) -> CreateOrderResult:
        # PR15b：允许真实 HTTP 下单（仅 demo；client 由注入决定，RealOkxHttpClient 已门禁 live）
        path = "/api/v5/trade/order"
        body = {
            "instId": symbol,
            "tdMode": "cash",
            "side": side.lower(),
            "ordType": _OKX_ORD_TYPE_MARKET,
            "sz": str(qty),
            "clOrdId": client_order_id,
        }
        resp = await self._client.post(self._request_path(path), body)
        raw = resp.body
        code = str(raw.get("code", ""))
        msg = (raw.get("msg") or "").strip()
        data = raw.get("data") or []
        http_status = resp.status_code
        request_id = resp.request_id

        if code != "0":
            # 50011 限频 -> Transient；50111-50116 鉴权 -> Permanent；51xxx 订单拒绝 -> Permanent；其他 5xx -> Transient
            if code == "50011":
                raise TransientOrderError(
                    f"OKX rate limit: {msg}",
                    http_status=http_status,
                    okx_code=code,
                    request_id=request_id,
                )
            if code in ("50111", "50112", "50113", "50114", "50115", "50116"):
                raise PermanentOrderError(
                    f"OKX auth failed: {msg}",
                    http_status=http_status,
                    okx_code=code,
                    request_id=request_id,
                )
            if code.startswith("51"):
                raise PermanentOrderError(
                    f"OKX order rejected {code}: {msg}",
                    http_status=http_status,
                    okx_code=code,
                    request_id=request_id,
                )
            if code.startswith("5"):
                raise TransientOrderError(
                    f"OKX server error {code}: {msg}",
                    http_status=http_status,
                    okx_code=code,
                    request_id=request_id,
                )
            raise PermanentOrderError(
                f"OKX order rejected {code}: {msg}",
                http_status=http_status,
                okx_code=code,
                request_id=request_id,
            )

        if not data:
            return CreateOrderResult(
                exchange_order_id="",
                client_order_id=client_order_id,
                status=ORDER_STATUS_REJECTED,
                filled_qty=None,
                avg_price=None,
                error=msg or "OKX returned no order id",
                raw=raw,
                http_status=http_status,
                okx_code=code,
                request_id=request_id,
            )
        first = data[0] if isinstance(data[0], dict) else {}
        ord_id = first.get("ordId") or first.get("orderId") or ""
        state = (first.get("state") or first.get("sCode") or "").strip() or "live"
        status = _okx_status_to_unified(state)
        filled_qty = _parse_decimal(first.get("accFillSz") or first.get("fillSz"))
        avg_price = _parse_decimal(first.get("avgPx") or first.get("fillPx"))
        return CreateOrderResult(
            exchange_order_id=str(ord_id),
            client_order_id=client_order_id,
            status=status,
            filled_qty=filled_qty,
            avg_price=avg_price,
            error=None,
            raw=raw,
            http_status=http_status,
            okx_code=code,
            request_id=request_id,
        )

    async def get_order(self, exchange_order_id: str, symbol: str) -> GetOrderResult:
        path = "/api/v5/trade/order"
        params = {"instId": symbol, "ordId": exchange_order_id}
        resp = await self._client.get(self._request_path(path), params)
        raw = resp.body
        code = str(raw.get("code", ""))
        msg = (raw.get("msg") or "").strip()
        data = raw.get("data") or []
        http_status = resp.status_code
        request_id = resp.request_id
        if code != "0":
            if code in ("50111", "50112", "50113", "50114", "50115", "50116"):
                return GetOrderResult(
                    exchange_order_id=exchange_order_id,
                    status=ORDER_STATUS_REJECTED,
                    filled_qty=None,
                    avg_price=None,
                    error=f"OKX auth: {msg}",
                    raw=raw,
                    http_status=http_status,
                    okx_code=code,
                    request_id=request_id,
                )
            return GetOrderResult(
                exchange_order_id=exchange_order_id,
                status=ORDER_STATUS_SUBMITTED,
                filled_qty=None,
                avg_price=None,
                error=msg or f"code {code}",
                raw=raw,
                http_status=http_status,
                okx_code=code,
                request_id=request_id,
            )
        if not data:
            return GetOrderResult(
                exchange_order_id=exchange_order_id,
                status=ORDER_STATUS_SUBMITTED,
                filled_qty=None,
                avg_price=None,
                error="order not found",
                raw=raw,
                http_status=http_status,
                okx_code=code,
                request_id=request_id,
            )
        first = data[0] if isinstance(data[0], dict) else {}
        state = (first.get("state") or first.get("sCode") or "").strip() or "live"
        status = _okx_status_to_unified(state)
        filled_qty = _parse_decimal(first.get("accFillSz") or first.get("fillSz"))
        avg_price = _parse_decimal(first.get("avgPx") or first.get("fillPx"))
        return GetOrderResult(
            exchange_order_id=exchange_order_id,
            status=status,
            filled_qty=filled_qty,
            avg_price=avg_price,
            error=None,
            raw=raw,
            http_status=http_status,
            okx_code=code,
            request_id=request_id,
        )

    async def cancel_order(self, exchange_order_id: str, **kwargs: Any) -> CancelOrderResult:
        path = "/api/v5/trade/cancel-order"
        body = {"ordId": exchange_order_id, "instId": kwargs.get("instId") or "BTC-USDT"}
        resp = await self._client.post(self._request_path(path), body)
        raw = resp.body
        code = str(raw.get("code", ""))
        return CancelOrderResult(
            success=(code == "0"),
            http_status=resp.status_code,
            okx_code=code or None,
            request_id=resp.request_id,
        )

    async def get_account_info(self) -> AccountInfo:
        """PR15c：OKX 账户接口暂不实现，由 AccountManager 使用 balance_repo fallback。"""
        raise AccountInfoError("OKX get_account_info not implemented in PR15c")
