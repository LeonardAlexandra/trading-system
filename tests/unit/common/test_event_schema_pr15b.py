"""
PR15b：事件体系统一（OKX_HTTP_* vs ORDER_*）schema 断言，防止混用与泄密。
- OKX_HTTP_*：仅允许 action/http_status/okx_code/request_id/attempt，禁止订单业务状态/secret。
- ORDER_*：禁止 secret/签名/原始 header/okx_code 等通信字段。
"""
import re
import pytest

from src.common import event_types


# PR15b：通信审计事件类型（只记录网络交互结果）
OKX_HTTP_EVENT_TYPES = [
    event_types.OKX_HTTP_CREATE_ORDER,
    event_types.OKX_HTTP_GET_ORDER,
    event_types.OKX_HTTP_CANCEL_ORDER,
    event_types.OKX_HTTP_RETRY,
]

# OKX_HTTP_* message 允许的 key 前缀（不含 secret/业务状态）
OKX_HTTP_ALLOWED_KEYS = {"action=", "http_status=", "okx_code=", "request_id=", "attempt="}

# ORDER_* 等业务事件 message 禁止包含的片段（防泄密）
FORBIDDEN_IN_ORDER_MESSAGE = [
    "secret",
    "passphrase",
    "OK-ACCESS",
    "api_key",
    "sign=",
    "signature",
]


def test_okx_http_create_order_message_only_allowed_keys():
    """OKX_HTTP_CREATE_ORDER 的 message 只含 action/http_status/okx_code/request_id/attempt。"""
    from src.execution.execution_engine import _okx_http_create_order_message

    allowed = {"action", "http_status", "okx_code", "request_id", "attempt"}
    msg = _okx_http_create_order_message(200, "0", "req-123", attempt=1)
    parts = msg.split()
    for part in parts:
        if "=" in part:
            key = part.split("=")[0]
            assert key in allowed, f"OKX_HTTP_* message must only contain allowed keys; got {key!r}"
    assert "action=CREATE_ORDER" in msg
    assert "http_status=200" in msg
    assert "okx_code=0" in msg
    assert "attempt=1" in msg
    for forbidden in ["secret", "passphrase", "OK-ACCESS", "api_key", "sign="]:
        assert forbidden not in msg.lower(), f"OKX_HTTP_* message must not contain {forbidden!r}"


def test_okx_http_message_no_secret():
    """_okx_http_create_order_message 不包含任何密钥相关字符串。"""
    from src.execution.execution_engine import _okx_http_create_order_message

    msg = _okx_http_create_order_message(401, "50111", "x-request-id-456", attempt=1)
    lower = msg.lower()
    assert "secret" not in lower
    assert "passphrase" not in lower
    assert "api_key" not in lower
    assert "ok-access" not in lower
    assert "sign=" not in lower


def test_order_event_types_exist():
    """ORDER_* 业务事件类型存在且与 OKX_HTTP_* 分离。"""
    assert event_types.ORDER_SUBMIT_OK is not None
    assert event_types.ORDER_SUBMIT_FAILED is not None
    assert event_types.ORDER_CANCELLED is not None
    assert event_types.ORDER_SYNCED is not None
    assert event_types.OKX_HTTP_CREATE_ORDER not in (event_types.ORDER_SUBMIT_OK, event_types.ORDER_SUBMIT_FAILED)


def test_okx_http_event_types_list():
    """OKX_HTTP_* 事件类型列表用于 schema 校验。"""
    assert event_types.OKX_HTTP_CREATE_ORDER == "OKX_HTTP_CREATE_ORDER"
    assert event_types.OKX_HTTP_GET_ORDER == "OKX_HTTP_GET_ORDER"
    assert event_types.OKX_HTTP_CANCEL_ORDER == "OKX_HTTP_CANCEL_ORDER"
    assert event_types.OKX_HTTP_RETRY == "OKX_HTTP_RETRY"
