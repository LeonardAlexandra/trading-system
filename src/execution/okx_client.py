"""
PR14b：OKX HTTP 客户端抽象（可注入 Fake 用于离线测试）；
PR15a：真实 OkxHttpClient（仅 demo endpoint）+ 可注入 transport。
"""
import base64
import hashlib
import hmac
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# PR15a：可选 httpx，用于真实 HTTP；可注入 transport 做离线测试
try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


@dataclass
class OkxResponse:
    """
    PR15a：统一 HTTP 响应，便于审计（status_code/request_id 不入 log/events 敏感信息）。
    """
    body: Dict[str, Any]
    status_code: int
    request_id: Optional[str] = None


class OkxHttpClient(ABC):
    """
    OKX API v5 HTTP 客户端接口。
    测试时注入 FakeOkxHttpClient，不访问真实 OKX 网络。
    PR15a：post/get 返回 OkxResponse 以携带 status_code/request_id 用于审计。
    """

    @abstractmethod
    async def post(self, path: str, json_body: Dict[str, Any]) -> OkxResponse:
        """POST 请求，返回 OkxResponse（body 为 JSON）。"""
        pass

    @abstractmethod
    async def get(self, path: str, params: Optional[Dict[str, str]] = None) -> OkxResponse:
        """GET 请求，返回 OkxResponse。"""
        pass


def _okx_sign(timestamp: str, method: str, request_path: str, body: str, secret: str) -> str:
    """OKX API v5 签名：prehash = timestamp + method + requestPath + body，HMAC-SHA256 + Base64。"""
    prehash = timestamp + method.upper() + request_path + body
    sig = hmac.new(
        secret.encode("utf-8"),
        prehash.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(sig).decode("utf-8")


def _okx_timestamp() -> str:
    """UTC 时间戳，毫秒 ISO 格式，如 2020-12-08T09:08:57.715Z。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class RealOkxHttpClient(OkxHttpClient):
    """
    PR15a/PR17b：真实 OKX HTTP 客户端。支持 demo 与 live 环境。
    - env=demo：使用 x-simulated-trading 头，不产生真实成交。
    - env=live：PR17b 支持真实 live endpoint，不使用 simulated 头。
    密钥仅从构造参数传入，禁止写入 log/events/response。
    """

    DEMO_BASE_URL = "https://www.okx.com"
    LIVE_BASE_URL = "https://www.okx.com"  # OKX 主站，live 与 demo 同 host
    DEMO_HEADER_SIMULATED = "x-simulated-trading"
    DEMO_HEADER_VALUE = "1"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        secret: str,
        passphrase: str,
        env: str,
        *,
        timeout_seconds: float = 30.0,
        transport: Optional[Any] = None,
    ):
        env_lower = (env or "demo").strip().lower()
        if env_lower not in ("demo", "live"):
            from src.common.reason_codes import OKX_LIVE_FORBIDDEN
            from src.common.config_errors import ConfigValidationError
            raise ConfigValidationError(
                OKX_LIVE_FORBIDDEN,
                "okx.env must be 'demo' or 'live'",
            )
        self._env = env_lower
        self._base_url = (base_url or (self.LIVE_BASE_URL if env_lower == "live" else self.DEMO_BASE_URL)).rstrip("/")
        self._api_key = api_key
        self._secret = secret
        self._passphrase = passphrase
        self._timeout = timeout_seconds
        self._transport = transport

    def _request_path(self, path: str, query: Optional[Dict[str, str]] = None) -> str:
        p = path if path.startswith("/") else "/" + path
        if not query:
            return p
        parts = [f"{k}={v}" for k, v in sorted(query.items())]
        return p + "?" + "&".join(parts)

    async def _do_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> OkxResponse:
        request_path = self._request_path(path, params)
        body_str = ""
        if json_body is not None:
            import json
            body_str = json.dumps(json_body, separators=(",", ":"))
        timestamp = _okx_timestamp()
        sign = _okx_sign(timestamp, method, request_path, body_str, self._secret)
        headers = {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }
        if self._env == "demo":
            headers[self.DEMO_HEADER_SIMULATED] = self.DEMO_HEADER_VALUE
        url = self._base_url + request_path
        if httpx is None:
            raise RuntimeError("httpx is required for RealOkxHttpClient")
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers)
            else:
                resp = await client.post(url, headers=headers, content=body_str)
        request_id = resp.headers.get("x-request-id") or resp.headers.get("OK-REQUEST-ID")
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {"code": "-1", "msg": "invalid json", "data": []}
        return OkxResponse(body=body, status_code=resp.status_code, request_id=request_id)

    async def post(self, path: str, json_body: Dict[str, Any]) -> OkxResponse:
        return await self._do_request("POST", path, json_body=json_body)

    async def get(self, path: str, params: Optional[Dict[str, str]] = None) -> OkxResponse:
        return await self._do_request("GET", path, params=params)


class FakeOkxHttpClient(OkxHttpClient):
    """
    用于单元/集成测试的假客户端：记录调用、返回可配置的 JSON，不访问网络。
    """

    def __init__(self):
        self._post_calls: list = []
        self._get_calls: list = []
        self._post_responses: Dict[str, Dict[str, Any]] = {}  # path -> response
        self._get_responses: Dict[str, Dict[str, Any]] = {}  # path -> response
        self._default_post: Optional[Dict[str, Any]] = None
        self._default_get: Optional[Dict[str, Any]] = None

    def set_post_response(self, path: str, response: Dict[str, Any]) -> None:
        self._post_responses[path] = response

    def set_get_response(self, path: str, response: Dict[str, Any]) -> None:
        self._get_responses[path] = response

    def set_default_post(self, response: Dict[str, Any]) -> None:
        self._default_post = response

    def set_default_get(self, response: Dict[str, Any]) -> None:
        self._default_get = response

    async def post(self, path: str, json_body: Dict[str, Any]) -> OkxResponse:
        self._post_calls.append({"path": path, "body": json_body})
        if path in self._post_responses:
            return OkxResponse(body=self._post_responses[path].copy(), status_code=200)
        if self._default_post is not None:
            return OkxResponse(body=self._default_post.copy(), status_code=200)
        return OkxResponse(body={"code": "0", "data": [], "msg": ""}, status_code=200)

    async def get(self, path: str, params: Optional[Dict[str, str]] = None) -> OkxResponse:
        self._get_calls.append({"path": path, "params": params or {}})
        if path in self._get_responses:
            return OkxResponse(body=self._get_responses[path].copy(), status_code=200)
        if self._default_get is not None:
            return OkxResponse(body=self._default_get.copy(), status_code=200)
        return OkxResponse(body={"code": "0", "data": [], "msg": ""}, status_code=200)

    @property
    def post_calls(self) -> list:
        return list(self._post_calls)

    @property
    def get_calls(self) -> list:
        return list(self._get_calls)

    def reset_calls(self) -> None:
        self._post_calls.clear()
        self._get_calls.clear()
