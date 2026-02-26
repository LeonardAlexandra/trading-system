"""
PR16：交易所级参数校验（qty/sz、精度、NaN/inf、市价单名义价值）。
校验失败在本地拒绝，不发起 HTTP，写 ORDER_REJECTED（reason_code 明确）。
"""
from decimal import Decimal
from typing import Any, Optional, Tuple

from src.common.reason_codes import (
    ORDER_PARAM_INVALID,
    ORDER_QTY_ZERO_OR_NEGATIVE,
    ORDER_QTY_PRECISION_EXCEEDED,
    ORDER_QTY_NAN_INF,
    ORDER_MARKET_NOTIONAL_EXCEEDED,
)


def validate_order_params(
    qty: Any,
    *,
    qty_precision: int = 8,
    market_max_notional: Optional[float] = None,
    last_price_for_notional: Optional[float] = None,
    ord_type: str = "market",
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    校验下单参数。在 adapter 或执行引擎调用 create_order 前执行。
    Returns:
        (allowed, reason_code, message)
    """
    # 禁止 None
    if qty is None:
        return False, ORDER_QTY_NAN_INF, "qty is None"

    # 转 Decimal 并禁止 NaN / inf
    try:
        qty_decimal = Decimal(str(qty))
    except Exception:
        return False, ORDER_PARAM_INVALID, "qty invalid type"
    if not qty_decimal.is_finite():
        return False, ORDER_QTY_NAN_INF, "qty is NaN or inf"

    # 必须 > 0
    if qty_decimal <= 0:
        return False, ORDER_QTY_ZERO_OR_NEGATIVE, "qty must be > 0"

    # 精度：OKX sz 小数位不超过 qty_precision（可配置）
    exp = qty_decimal.as_tuple().exponent
    if exp < 0 and -exp > qty_precision:
        return False, ORDER_QTY_PRECISION_EXCEEDED, f"qty decimal places exceed {qty_precision}"

    # 市价单名义价值上限（可选）
    if ord_type and (ord_type or "").lower() == "market" and market_max_notional is not None and market_max_notional > 0:
        if last_price_for_notional is not None and last_price_for_notional > 0:
            notional = float(qty_decimal) * last_price_for_notional
            if notional > market_max_notional:
                return (
                    False,
                    ORDER_MARKET_NOTIONAL_EXCEEDED,
                    f"market notional {notional} > max {market_max_notional}",
                )

    return True, None, None
