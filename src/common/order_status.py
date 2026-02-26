"""
订单状态常量（PR8：CreateOrderResult.status 统一取值，防拼写漂移）
用于 ExchangeAdapter 返回与事件落库中的订单级 status。
"""
ORDER_STATUS_FILLED = "FILLED"
ORDER_STATUS_SUBMITTED = "SUBMITTED"
ORDER_STATUS_REJECTED = "REJECTED"
ORDER_STATUS_CANCELLED = "CANCELLED"  # PR12: 取消订单
