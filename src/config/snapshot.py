"""
配置快照白名单（PR10）：仅允许字段写入 execution_events.CONFIG_SNAPSHOT.message，禁止 secret/raw/signature。
PR11：CONFIG_SNAPSHOT 必须包含 strategy_id、strategy_config_fingerprint。
P3：体积护栏，超过 MAX_SNAPSHOT_BYTES 返回截断版 JSON。
"""
import json
from typing import Any, Dict, TYPE_CHECKING

from src.config.app_config import AppConfig

if TYPE_CHECKING:
    from src.config.strategy_resolver import ResolvedStrategyConfig

# P3：防止 message 膨胀，严禁加入 secret
MAX_SNAPSHOT_BYTES = 4096


def make_config_snapshot(app_config: AppConfig) -> Dict[str, Any]:
    """
    生成可写入 CONFIG_SNAPSHOT 事件的配置快照（白名单字段）。
    禁止包含：webhook.tradingview_secret、raw payload、signature。
    白名单：
      - execution: poll_interval_seconds, batch_size, max_concurrency, max_attempts, backoff_seconds
      - risk: cooldown_seconds, same_direction_dedupe_window_seconds, max_position_qty, max_order_qty, cooldown_mode
      - exchange: mode, paper_filled
    """
    ex = app_config.execution
    risk = app_config.risk
    exch = app_config.exchange
    snapshot = {
        "execution": {
            "poll_interval_seconds": ex.poll_interval_seconds,
            "batch_size": ex.batch_size,
            "max_concurrency": ex.max_concurrency,
            "max_attempts": ex.max_attempts,
            "backoff_seconds": ex.backoff_seconds,
        },
        "risk": {
            "cooldown_seconds": risk.cooldown_seconds,
            "same_direction_dedupe_window_seconds": risk.same_direction_dedupe_window_seconds,
            "max_position_qty": str(risk.max_position_qty) if risk.max_position_qty is not None else None,
            "max_order_qty": str(risk.max_order_qty) if risk.max_order_qty is not None else None,
            "cooldown_mode": risk.cooldown_mode,
        },
        "exchange": {
            "mode": exch.mode,
            "paper_filled": exch.paper_filled,
        },
    }
    return snapshot


def make_config_snapshot_from_resolved(resolved: "ResolvedStrategyConfig") -> Dict[str, Any]:
    """
    PR11：从 ResolvedStrategyConfig 生成快照，必须包含 strategy_id、strategy_config_fingerprint。
    白名单同上，严禁 secret。
    """
    ex = resolved.execution
    risk = resolved.risk
    exch = resolved.exchange
    snapshot = {
        "strategy_id": resolved.strategy_id,
        "strategy_config_fingerprint": resolved.strategy_config_fingerprint,
        "execution": {
            "poll_interval_seconds": ex.poll_interval_seconds,
            "batch_size": ex.batch_size,
            "max_concurrency": ex.max_concurrency,
            "max_attempts": ex.max_attempts,
            "backoff_seconds": ex.backoff_seconds,
        },
        "risk": {
            "cooldown_seconds": risk.cooldown_seconds,
            "same_direction_dedupe_window_seconds": risk.same_direction_dedupe_window_seconds,
            "max_position_qty": str(risk.max_position_qty) if risk.max_position_qty is not None else None,
            "max_order_qty": str(risk.max_order_qty) if risk.max_order_qty is not None else None,
            "cooldown_mode": risk.cooldown_mode,
        },
        "exchange": {
            "mode": exch.mode,
            "paper_filled": exch.paper_filled,
        },
    }
    return snapshot


def _trim_snapshot_for_size(snapshot: Dict[str, Any], original_byte_size: int) -> Dict[str, Any]:
    """构建体积受控的截断版：保留 strategy_id/fingerprint 及 execution/risk/exchange 核心字段，大数组截断，严禁 secret。"""
    ex = (snapshot.get("execution") or {}).copy()
    backoff = ex.get("backoff_seconds") or []
    if len(backoff) > 32:
        ex["backoff_seconds"] = list(backoff[:32])
        ex["backoff_truncated"] = True
        ex["backoff_original_length"] = len(backoff)
    out = {
        "snapshot_truncated": True,
        "size": original_byte_size,
        "execution": ex,
        "risk": snapshot.get("risk") or {},
        "exchange": snapshot.get("exchange") or {},
    }
    if "strategy_id" in snapshot:
        out["strategy_id"] = snapshot["strategy_id"]
    if "strategy_config_fingerprint" in snapshot:
        out["strategy_config_fingerprint"] = snapshot["strategy_config_fingerprint"]
    return out


def make_config_snapshot_message(app_config: AppConfig) -> str:
    """
    返回 JSON 字符串，用于 CONFIG_SNAPSHOT 事件的 message 字段（无 strategy 时兼容）。
    若超过 MAX_SNAPSHOT_BYTES，返回截断版，严禁 secret。
    """
    full = make_config_snapshot(app_config)
    msg = json.dumps(full, separators=(",", ":"))
    raw_len = len(msg.encode("utf-8"))
    if raw_len <= MAX_SNAPSHOT_BYTES:
        return msg
    truncated = _trim_snapshot_for_size(full, raw_len)
    return json.dumps(truncated, separators=(",", ":"))


def make_config_snapshot_message_for_strategy(resolved: "ResolvedStrategyConfig") -> str:
    """
    PR11：从 ResolvedStrategyConfig 生成 CONFIG_SNAPSHOT message，必须包含 strategy_id、strategy_config_fingerprint。
    若超过 MAX_SNAPSHOT_BYTES，返回截断版，严禁 secret。
    """
    full = make_config_snapshot_from_resolved(resolved)
    msg = json.dumps(full, separators=(",", ":"))
    raw_len = len(msg.encode("utf-8"))
    if raw_len <= MAX_SNAPSHOT_BYTES:
        return msg
    truncated = _trim_snapshot_for_size(full, raw_len)
    return json.dumps(truncated, separators=(",", ":"))
