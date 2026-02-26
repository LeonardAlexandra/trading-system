"""
执行层异常（PR6：可重试 vs 不可重试；PR13：实盘接口边界）
PR15b：可选携带通信审计字段（http_status/okx_code/request_id），仅用于写 OKX_HTTP_* 事件，不泄密。
"""
from typing import Optional


class TransientOrderError(Exception):
    """可重试异常（网络超时、临时错误等）。ExecutionEngine 会回退到 RESERVED 并设置 next_run_at。"""
    def __init__(
        self,
        message: str,
        *args: object,
        http_status: Optional[int] = None,
        okx_code: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message, *args)
        self.http_status = http_status
        self.okx_code = okx_code
        self.request_id = request_id


class PermanentOrderError(Exception):
    """不可重试异常（余额不足、订单被拒等）。ExecutionEngine 直接标记 FAILED，不重试。"""
    def __init__(
        self,
        message: str,
        *args: object,
        http_status: Optional[int] = None,
        okx_code: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message, *args)
        self.http_status = http_status
        self.okx_code = okx_code
        self.request_id = request_id
