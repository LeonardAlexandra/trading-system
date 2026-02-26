"""
PR14b：OKX Adapter 单元测试（FakeOkxHttpClient，不访问网络）
- create_order OK → 返回 exchange_order_id/status/filled_qty
- create_order 错误分类 → Transient / Permanent
- cancel_order OK/Fail
- get_order 状态映射：OKX 状态 → 统一 OrderStatus
"""
from decimal import Decimal
import pytest

from src.execution.okx_adapter import OkxExchangeAdapter, _okx_status_to_unified
from src.execution.okx_client import FakeOkxHttpClient
from src.execution.exceptions import TransientOrderError, PermanentOrderError
from src.common.order_status import (
    ORDER_STATUS_FILLED,
    ORDER_STATUS_SUBMITTED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_REJECTED,
)


@pytest.fixture
def fake_client():
    return FakeOkxHttpClient()


@pytest.fixture
def okx_adapter(fake_client):
    return OkxExchangeAdapter(
        http_client=fake_client,
        api_key="test-key",
        secret="test-secret",
        passphrase="test-pass",
    )


# ----- PR15b：create_order 成功 / 错误分类（离线 Fake）-----
@pytest.mark.asyncio
async def test_okx_adapter_create_order_success(okx_adapter, fake_client):
    """PR15b：Fake 返回成功 JSON → CreateOrderResult 含 exchange_order_id、status、审计字段；无 secret。"""
    fake_client.set_post_response(
        "/api/v5/trade/order",
        {"code": "0", "data": [{"ordId": "okx-123", "state": "filled", "accFillSz": "0.01", "avgPx": "50000"}], "msg": ""},
    )
    result = await okx_adapter.create_order(
        symbol="BTC-USDT",
        side="buy",
        qty=Decimal("0.01"),
        client_order_id="dec-001",
    )
    assert result.exchange_order_id == "okx-123"
    assert result.client_order_id == "dec-001"
    assert result.status == ORDER_STATUS_FILLED
    assert result.filled_qty == Decimal("0.01")
    assert result.avg_price == Decimal("50000")
    assert result.error is None
    assert result.http_status == 200
    assert result.okx_code == "0"
    assert len(fake_client.post_calls) == 1
    assert fake_client.post_calls[0]["path"] == "/api/v5/trade/order"
    # 禁止 secret 进入 result
    assert not (hasattr(result, "raw") and result.raw and ("secret" in str(result.raw).lower() or "passphrase" in str(result.raw).lower()))


@pytest.mark.asyncio
async def test_okx_adapter_create_order_auth_failed_permanent(okx_adapter, fake_client):
    """PR15b：鉴权错误 → PermanentOrderError，携带 http_status/okx_code/request_id；不重试（Engine 层断言）。"""
    fake_client.set_post_response("/api/v5/trade/order", {"code": "50111", "msg": "Invalid API key", "data": []})
    with pytest.raises(PermanentOrderError) as exc_info:
        await okx_adapter.create_order("BTC-USDT", "buy", Decimal("0.01"), "dec-003")
    assert "auth" in (str(exc_info.value)).lower()
    e = exc_info.value
    assert e.http_status == 200
    assert e.okx_code == "50111"
    assert len(fake_client.post_calls) == 1


@pytest.mark.asyncio
async def test_okx_adapter_create_order_rate_limit_transient(okx_adapter, fake_client):
    """PR15b：限频 50011 → TransientOrderError，可重试。"""
    fake_client.set_post_response("/api/v5/trade/order", {"code": "50011", "msg": "Rate limit", "data": []})
    with pytest.raises(TransientOrderError) as exc_info:
        await okx_adapter.create_order("BTC-USDT", "buy", Decimal("0.01"), "dec-002")
    assert "rate limit" in (str(exc_info.value)).lower()
    e = exc_info.value
    assert e.okx_code == "50011"


@pytest.mark.asyncio
async def test_okx_adapter_create_order_rejected_permanent(okx_adapter, fake_client):
    """PR15b：订单拒绝 51xxx → PermanentOrderError。"""
    fake_client.set_post_response("/api/v5/trade/order", {"code": "51000", "msg": "Order rejected", "data": []})
    with pytest.raises(PermanentOrderError) as exc_info:
        await okx_adapter.create_order("BTC-USDT", "buy", Decimal("0.01"), "dec-005")
    assert exc_info.value.okx_code == "51000"


@pytest.mark.asyncio
async def test_okx_adapter_create_order_server_error_transient(okx_adapter, fake_client):
    """PR15b：5xx 服务器错误 → TransientOrderError。"""
    fake_client.set_post_response("/api/v5/trade/order", {"code": "50000", "msg": "Internal error", "data": []})
    with pytest.raises(TransientOrderError):
        await okx_adapter.create_order("BTC-USDT", "buy", Decimal("0.01"), "dec-004")


# ----- cancel_order OK/Fail（PR15a 返回 CancelOrderResult）-----
@pytest.mark.asyncio
async def test_okx_adapter_cancel_order_ok(okx_adapter, fake_client):
    fake_client.set_post_response("/api/v5/trade/cancel-order", {"code": "0", "data": [], "msg": ""})
    result = await okx_adapter.cancel_order("ord-456")
    assert result.success is True
    assert result.http_status == 200
    assert len(fake_client.post_calls) == 1
    assert fake_client.post_calls[0]["body"].get("ordId") == "ord-456"


@pytest.mark.asyncio
async def test_okx_adapter_cancel_order_fail(okx_adapter, fake_client):
    fake_client.set_post_response("/api/v5/trade/cancel-order", {"code": "51000", "msg": "Order not found", "data": []})
    result = await okx_adapter.cancel_order("ord-789")
    assert result.success is False
    assert result.okx_code == "51000"


# ----- get_order 状态映射 -----
def test_okx_status_to_unified():
    assert _okx_status_to_unified("live") == ORDER_STATUS_SUBMITTED
    assert _okx_status_to_unified("partially_filled") == ORDER_STATUS_SUBMITTED
    assert _okx_status_to_unified("filled") == ORDER_STATUS_FILLED
    assert _okx_status_to_unified("canceled") == ORDER_STATUS_CANCELLED
    assert _okx_status_to_unified("cancelled") == ORDER_STATUS_CANCELLED
    assert _okx_status_to_unified("rejected") == ORDER_STATUS_REJECTED
    assert _okx_status_to_unified("unknown") == ORDER_STATUS_SUBMITTED


@pytest.mark.asyncio
async def test_okx_adapter_get_order_state_mapping(okx_adapter, fake_client):
    fake_client.set_get_response(
        "/api/v5/trade/order",
        {"code": "0", "data": [{"ordId": "o1", "state": "filled", "accFillSz": "0.01", "avgPx": "50000"}], "msg": ""},
    )
    result = await okx_adapter.get_order("o1", "BTC-USDT")
    assert result.exchange_order_id == "o1"
    assert result.status == ORDER_STATUS_FILLED
    assert result.filled_qty == Decimal("0.01")

    fake_client.set_get_response(
        "/api/v5/trade/order",
        {"code": "0", "data": [{"ordId": "o2", "state": "canceled"}], "msg": ""},
    )
    result2 = await okx_adapter.get_order("o2", "BTC-USDT")
    assert result2.status == ORDER_STATUS_CANCELLED

    fake_client.set_get_response(
        "/api/v5/trade/order",
        {"code": "0", "data": [{"ordId": "o3", "state": "rejected"}], "msg": ""},
    )
    result3 = await okx_adapter.get_order("o3", "BTC-USDT")
    assert result3.status == ORDER_STATUS_REJECTED
