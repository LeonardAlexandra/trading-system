"""
OrderManager（PR12：查询、取消、状态同步 + 工程级整改：审计链）
不改变幂等/事务边界；显式依赖 ExchangeAdapter + OrdersRepository + ExecutionEventRepository。
所有对外可观察行为（cancel / sync）均写入 execution_events，可审计、可回放、可解释。
PR15a：get_order/cancel_order 真实 HTTP 时追加 OKX_HTTP_GET_ORDER/OKX_HTTP_CANCEL_ORDER 事件。
"""
from decimal import Decimal
from typing import Optional

from src.execution.exchange_adapter import ExchangeAdapter
from src.repositories.orders_repo import OrdersRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.models.order import Order
from src.common.order_status import ORDER_STATUS_CANCELLED
from src.common.event_types import (
    ORDER_CANCELLED as EV_ORDER_CANCELLED,
    ORDER_SYNCED as EV_ORDER_SYNCED,
    OKX_HTTP_GET_ORDER as EV_OKX_HTTP_GET_ORDER,
    OKX_HTTP_CANCEL_ORDER as EV_OKX_HTTP_CANCEL_ORDER,
)
from src.execution.exchange_adapter import CancelOrderResult


class OrderManager:
    """
    PR12：订单查询、取消、状态同步；关键行为写入 execution_events。
    order_id 为本地主键 Order.order_id；取消/同步通过 exchange_order_id 调用适配器。
    """

    def __init__(
        self,
        exchange_adapter: ExchangeAdapter,
        order_repo: OrdersRepository,
        event_repo: ExecutionEventRepository,
    ):
        self._exchange = exchange_adapter
        self._order_repo = order_repo
        self._event_repo = event_repo

    async def get_order(self, order_id: str) -> Order | None:
        """
        按本地订单号查询订单（仅读库，不请求交易所）。
        """
        return await self._order_repo.get_by_local_order_id(order_id)

    async def cancel_order(
        self,
        order_id: str,
        reason: str,
        *,
        source: str = "user",
        account_id: Optional[str] = None,
        exchange_profile_id: Optional[str] = None,
    ) -> bool:
        """
        取消未完全成交的订单：先查库，再调交易所取消，再更新本地状态，并追加 ORDER_CANCELLED 事件。
        PR15a：若适配器返回审计字段则追加 OKX_HTTP_CANCEL_ORDER 事件（不含 secret）。
        成功返回 True；订单不存在、已成交或交易所取消失败返回 False。
        不在此处 commit，由调用方管理 session。
        """
        order = await self._order_repo.get_by_local_order_id(order_id)
        if order is None:
            return False
        if not order.exchange_order_id:
            return False
        result = await self._exchange.cancel_order(order.exchange_order_id)
        if not isinstance(result, CancelOrderResult):
            ok = bool(result)
        else:
            ok = result.success
        if not ok:
            return False
        # PR15a：真实 HTTP 审计事件（不含 secret）
        if isinstance(result, CancelOrderResult) and result.http_status is not None:
            msg_parts = [f"action=CANCEL_ORDER http_status={result.http_status}"]
            if result.okx_code is not None:
                msg_parts.append(f"okx_code={result.okx_code}")
            if result.request_id:
                msg_parts.append(f"request_id={result.request_id[:64]}")
            await self._event_repo.append_event(
                order.decision_id,
                EV_OKX_HTTP_CANCEL_ORDER,
                reason_code=source,
                message=" ".join(msg_parts)[:500],
                exchange_order_id=order.exchange_order_id,
                account_id=account_id,
                exchange_profile=exchange_profile_id,
            )
        old_status = order.status
        order.status = ORDER_STATUS_CANCELLED
        await self._order_repo.update(order)
        message = (
            f"order_id={order.order_id} strategy_id={order.strategy_id or ''} "
            f"old_status={old_status} new_status={ORDER_STATUS_CANCELLED} reason={reason!r}"
        )
        await self._event_repo.append_event(
            order.decision_id,
            EV_ORDER_CANCELLED,
            status=ORDER_STATUS_CANCELLED,
            exchange_order_id=order.exchange_order_id,
            reason_code=source,
            message=message,
        )
        return True

    async def sync_order_status(
        self,
        order_id: str,
        *,
        source: str = "system",
        account_id: Optional[str] = None,
        exchange_profile_id: Optional[str] = None,
    ) -> Order:
        """
        从交易所拉取最新状态并更新本地订单，追加 ORDER_SYNCED 事件，返回更新后的 Order。
        PR15a：若 get_order 返回审计字段则追加 OKX_HTTP_GET_ORDER 事件（不含 secret）。
        订单不存在时抛出 ValueError。
        不在此处 commit，由调用方管理 session。
        """
        order = await self._order_repo.get_by_local_order_id(order_id)
        if order is None:
            raise ValueError(f"Order not found: order_id={order_id}")
        exchange_order_id = order.exchange_order_id or ""
        symbol = order.symbol or ""
        old_status = order.status
        result = await self._exchange.get_order(exchange_order_id, symbol)
        # PR15a：真实 HTTP 审计事件（不含 secret）
        if getattr(result, "http_status", None) is not None:
            msg_parts = [f"action=GET_ORDER http_status={result.http_status}"]
            if getattr(result, "okx_code", None) is not None:
                msg_parts.append(f"okx_code={result.okx_code}")
            if getattr(result, "request_id", None):
                msg_parts.append(f"request_id={(result.request_id or '')[:64]}")
            await self._event_repo.append_event(
                order.decision_id,
                EV_OKX_HTTP_GET_ORDER,
                reason_code=source,
                message=" ".join(msg_parts)[:500],
                exchange_order_id=order.exchange_order_id,
                account_id=account_id,
                exchange_profile=exchange_profile_id,
            )
        order.status = result.status
        if result.filled_qty is not None:
            order.filled_quantity = result.filled_qty
        await self._order_repo.update(order)
        message = (
            f"order_id={order.order_id} strategy_id={order.strategy_id or ''} "
            f"old_status={old_status} new_status={order.status}"
        )
        await self._event_repo.append_event(
            order.decision_id,
            EV_ORDER_SYNCED,
            status=order.status,
            exchange_order_id=order.exchange_order_id,
            reason_code=source,
            message=message,
        )
        return order
