"""
TradingViewAdapter：验签 + payload 解析（PR4，不落库、不调用 Repository）
"""
import hmac
import hashlib
import base64
import json
from datetime import datetime, timezone
from typing import Optional

from src.schemas.signals import TradingViewSignal

# 验签使用的 HTTP 头（与文档一致）
SIGNATURE_HEADER_NAME = "X-TradingView-Signature"


class TradingViewAdapter:
    """
    TradingView Webhook 适配器：仅负责验签与 JSON 解析、字段校验。
    不关心策略、重复信号、下游执行。
    """

    @staticmethod
    def validate_signature(
        raw_body: bytes,
        signature_header: str,
        secret: str,
    ) -> None:
        """
        使用 HMAC-SHA256 验证请求体签名。
        验签必须基于原始 body bytes，禁止使用 request.json() 后再序列化。

        Args:
            raw_body: 原始请求体（await request.body()）
            signature_header: 请求头中的签名值（X-TradingView-Signature）
            secret: Webhook Secret（与 TradingView 配置一致）

        Raises:
            ValueError: 签名缺失或验签失败
        """
        if not signature_header or not signature_header.strip():
            raise ValueError("Missing signature header")
        if not secret:
            raise ValueError("Webhook secret is required")
        expected = base64.b64encode(
            hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        ).decode("utf-8")
        if not hmac.compare_digest(signature_header.strip(), expected):
            raise ValueError("Invalid signature")

    @staticmethod
    def parse_signal(raw_body: bytes) -> TradingViewSignal:
        """
        解析 JSON 请求体为 TradingViewSignal。
        做基本字段校验与类型转换；解析失败抛出 ValueError。

        Args:
            raw_body: 原始请求体（验签通过后的同一份 bytes）

        Returns:
            TradingViewSignal

        Raises:
            ValueError: JSON 无效或必填字段缺失/类型错误
        """
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid JSON or encoding: {e}") from e

        if not isinstance(data, dict):
            raise ValueError("Payload must be a JSON object")

        # 必填字段（TradingView 常见字段名）
        symbol = data.get("symbol") or data.get("ticker")
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Missing or invalid 'symbol' / 'ticker'")
        symbol = str(symbol).strip().upper()

        # side / action：BUY | SELL 等
        side = data.get("side") or data.get("action")
        if not side or not isinstance(side, str):
            raise ValueError("Missing or invalid 'side' / 'action'")
        side = str(side).strip().upper()

        # 时间戳：支持 ISO 字符串或数字
        ts_raw = data.get("timestamp") or data.get("bar_time") or data.get("time")
        if ts_raw is None:
            raise ValueError("Missing 'timestamp' / 'bar_time' / 'time'")
        timestamp = _parse_timestamp(ts_raw)

        # PR11：payload 应包含 strategy_id；未提供或空则置空串，由 Webhook 层返回 422
        strategy_id_raw = data.get("strategy_id") or data.get("strategy")
        if strategy_id_raw is not None and isinstance(strategy_id_raw, str):
            strategy_id = str(strategy_id_raw).strip()
        else:
            strategy_id = ""

        # 语义字段（用于 timeframe / indicator，不纳入必填校验）
        timeframe = str(data.get("timeframe") or data.get("interval") or "").strip()
        indicator = str(
            data.get("indicator_name") or data.get("indicator") or data.get("strategy") or ""
        ).strip()

        # signal_id：仅由“交易决策语义字段”决定，不含 comment/metadata/debug 等，保证同一交易语义去重稳定
        signal_identity = {
            "action": side,
            "indicator": indicator,
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": timestamp.isoformat(),
        }
        canonical_str = json.dumps(signal_identity, sort_keys=True, separators=(",", ":"))
        signal_id = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

        return TradingViewSignal(
            signal_id=signal_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            timestamp=timestamp,
            raw_payload=data,
            source="tradingview",
        )


def _parse_timestamp(ts_raw: object) -> datetime:
    """将 payload 中的时间戳解析为 timezone-aware datetime"""
    if isinstance(ts_raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
        except (ValueError, OSError):
            pass
    if isinstance(ts_raw, str):
        try:
            # ISO 格式
            dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    raise ValueError(f"Unsupported timestamp format: {type(ts_raw)}")
