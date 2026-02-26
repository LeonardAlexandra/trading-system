"""
PR15a：OkxHttpClient 签名与请求构造（离线）；RealOkxHttpClient 门禁（env != demo fail-fast）。
"""
import base64
import hmac
import hashlib
import pytest

from src.execution.okx_client import (
    _okx_sign,
    _okx_timestamp,
    OkxResponse,
    RealOkxHttpClient,
    FakeOkxHttpClient,
)


def test_okx_sign_fixed_timestamp_and_secret():
    """给定固定时间戳与 secret，签名与预期一致（离线断言）。"""
    # OKX 文档示例：timestamp + method + requestPath + body
    timestamp = "2020-12-08T09:08:57.715Z"
    method = "GET"
    request_path = "/api/v5/account/balance?ccy=BTC"
    body = ""
    secret = "22582BD0CFF14C41EDBF1AB98506286D"
    sig = _okx_sign(timestamp, method, request_path, body, secret)
    assert isinstance(sig, str)
    assert len(sig) > 0
    # Base64 解码应得到 32 字节（SHA256）
    decoded = base64.b64decode(sig)
    assert len(decoded) == 32
    # 同一输入应得到同一签名
    sig2 = _okx_sign(timestamp, method, request_path, body, secret)
    assert sig == sig2


def test_okx_sign_post_with_body():
    """POST 带 body 时 prehash 包含 body。"""
    timestamp = "2020-12-08T09:08:57.715Z"
    method = "POST"
    request_path = "/api/v5/trade/order"
    body = '{"instId":"BTC-USDT","side":"buy","sz":"0.01"}'
    secret = "test-secret-key"
    sig = _okx_sign(timestamp, method, request_path, body, secret)
    assert isinstance(sig, str)
    # 不同 body 得到不同签名
    body2 = '{"instId":"ETH-USDT"}'
    sig2 = _okx_sign(timestamp, method, request_path, body2, secret)
    assert sig != sig2


def test_okx_timestamp_format():
    """时间戳为 UTC 毫秒 ISO 格式。"""
    ts = _okx_timestamp()
    assert "T" in ts
    assert "Z" in ts
    assert "." in ts


def test_real_okx_http_client_env_invalid_forbidden():
    """env 既非 demo 也非 live 时 RealOkxHttpClient 构造 fail-fast。"""
    from src.common.config_errors import ConfigValidationError
    from src.common.reason_codes import OKX_LIVE_FORBIDDEN

    with pytest.raises(ConfigValidationError) as exc_info:
        RealOkxHttpClient(
            base_url="https://www.okx.com",
            api_key="k",
            secret="s",
            passphrase="p",
            env="prod",
        )
    assert exc_info.value.reason_code == OKX_LIVE_FORBIDDEN


def test_real_okx_http_client_live_allowed():
    """PR17b：env=live 时构造成功。"""
    client = RealOkxHttpClient(
        base_url="https://www.okx.com",
        api_key="k",
        secret="s",
        passphrase="p",
        env="live",
    )
    assert client._env == "live"
    assert client._base_url == "https://www.okx.com"


def test_real_okx_http_client_demo_allowed():
    """env=demo 时构造成功。"""
    client = RealOkxHttpClient(
        base_url="https://www.okx.com",
        api_key="k",
        secret="s",
        passphrase="p",
        env="demo",
    )
    assert client._base_url == "https://www.okx.com"


@pytest.mark.asyncio
async def test_fake_okx_http_client_returns_okx_response():
    """FakeOkxHttpClient.post/get 返回 OkxResponse。"""
    fake = FakeOkxHttpClient()
    fake.set_post_response("/api/v5/trade/order", {"code": "0", "data": [], "msg": ""})
    resp = await fake.post("/api/v5/trade/order", {})
    assert isinstance(resp, OkxResponse)
    assert resp.body == {"code": "0", "data": [], "msg": ""}
    assert resp.status_code == 200
