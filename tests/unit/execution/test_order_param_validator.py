"""
PR16：参数精度与数量校验单元测试。
qty=0/负数/超精度/NaN → ORDER_REJECTED 系列 reason_code；不触发 HTTP。
"""
import math
from decimal import Decimal
import pytest

from src.execution.order_param_validator import validate_order_params
from src.common.reason_codes import (
    ORDER_QTY_ZERO_OR_NEGATIVE,
    ORDER_QTY_PRECISION_EXCEEDED,
    ORDER_QTY_NAN_INF,
    ORDER_PARAM_INVALID,
    ORDER_MARKET_NOTIONAL_EXCEEDED,
)


def test_validate_qty_positive_passes():
    """qty > 0 且精度合法时通过。"""
    allowed, code, msg = validate_order_params(Decimal("1.5"), qty_precision=8)
    assert allowed is True
    assert code is None


def test_validate_qty_zero_rejects():
    """qty=0 拒绝。"""
    allowed, code, msg = validate_order_params(Decimal("0"), qty_precision=8)
    assert allowed is False
    assert code == ORDER_QTY_ZERO_OR_NEGATIVE


def test_validate_qty_negative_rejects():
    """qty<0 拒绝。"""
    allowed, code, msg = validate_order_params(Decimal("-1"), qty_precision=8)
    assert allowed is False
    assert code == ORDER_QTY_ZERO_OR_NEGATIVE


def test_validate_qty_none_rejects():
    """qty=None 拒绝。"""
    allowed, code, msg = validate_order_params(None, qty_precision=8)
    assert allowed is False
    assert code == ORDER_QTY_NAN_INF


def test_validate_qty_nan_rejects():
    """qty 为 NaN 拒绝。"""
    allowed, code, msg = validate_order_params(Decimal("nan"), qty_precision=8)
    assert allowed is False
    assert code == ORDER_QTY_NAN_INF


def test_validate_qty_inf_rejects():
    """qty 为 inf 拒绝。"""
    allowed, code, msg = validate_order_params(Decimal("inf"), qty_precision=8)
    assert allowed is False
    assert code == ORDER_QTY_NAN_INF


def test_validate_qty_precision_exceeded_rejects():
    """小数位超过 qty_precision 拒绝。"""
    allowed, code, msg = validate_order_params(Decimal("1.123456789"), qty_precision=8)
    assert allowed is False
    assert code == ORDER_QTY_PRECISION_EXCEEDED


def test_validate_qty_precision_at_limit_passes():
    """小数位等于 qty_precision 通过。"""
    allowed, code, msg = validate_order_params(Decimal("1.12345678"), qty_precision=8)
    assert allowed is True


def test_validate_market_notional_exceeded_rejects():
    """市价单名义价值超过上限拒绝。"""
    allowed, code, msg = validate_order_params(
        Decimal("100"),
        qty_precision=8,
        market_max_notional=1000.0,
        last_price_for_notional=20.0,
        ord_type="market",
    )
    assert allowed is False
    assert code == ORDER_MARKET_NOTIONAL_EXCEEDED


def test_validate_market_notional_within_limit_passes():
    """市价单名义价值在限额内通过。"""
    allowed, code, msg = validate_order_params(
        Decimal("10"),
        qty_precision=8,
        market_max_notional=1000.0,
        last_price_for_notional=20.0,
        ord_type="market",
    )
    assert allowed is True


# PR16c：qty 精度按 symbol 覆盖 / 全局 fallback
def test_validate_qty_precision_symbol_override_effective():
    """PR16c：symbol 覆盖精度生效（如 qty_precision_by_symbol[BTC-USDT]=4）。"""
    allowed, code, msg = validate_order_params(Decimal("1.12345"), qty_precision=4)
    assert allowed is False
    assert code == ORDER_QTY_PRECISION_EXCEEDED
    allowed2, _, _ = validate_order_params(Decimal("1.1234"), qty_precision=4)
    assert allowed2 is True


def test_validate_qty_precision_fallback_global():
    """PR16c：symbol 不在 qty_precision_by_symbol 时使用全局 order_qty_precision。"""
    allowed, code, msg = validate_order_params(Decimal("1.12345678"), qty_precision=8)
    assert allowed is True
    assert code is None
