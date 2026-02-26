"""
PR11：策略级配置解析器（运行期只读 app_config，按 strategy_id 合并并生成 fingerprint）
"""
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict

from src.common.reason_codes import STRATEGY_DISABLED, STRATEGY_NOT_FOUND

if TYPE_CHECKING:
    from src.config.app_config import AppConfig

from src.config.app_config import (
    AppConfig,
    ExecutionConfig,
    RiskSectionConfig,
    ExchangeConfig,
    StrategyEntryConfig,
)


@dataclass
class ResolvedStrategyConfig:
    """PR11：按 strategy_id 合并后的策略配置；PR13：account_id / exchange_profile_id 显式归属。"""
    strategy_id: str
    execution: ExecutionConfig
    risk: RiskSectionConfig
    exchange: ExchangeConfig
    strategy_config_fingerprint: str
    account_id: str = "default"  # PR13：未配置时默认，可追溯审计
    exchange_profile_id: str = "paper"  # PR13：未配置时默认


def _canonical_config_dict(
    execution: ExecutionConfig,
    risk: RiskSectionConfig,
    exchange: ExchangeConfig,
    account_id: str = "default",
    exchange_profile_id: str = "paper",
) -> Dict[str, Any]:
    """生成可序列化的配置 dict（白名单，无 secret），用于 fingerprint。PR13：含 account/exchange_profile。"""
    return {
        "account_id": account_id,
        "exchange_profile_id": exchange_profile_id,
        "execution": {
            "poll_interval_seconds": execution.poll_interval_seconds,
            "batch_size": execution.batch_size,
            "max_concurrency": execution.max_concurrency,
            "max_attempts": execution.max_attempts,
            "backoff_seconds": execution.backoff_seconds,
        },
        "risk": {
            "cooldown_seconds": risk.cooldown_seconds,
            "same_direction_dedupe_window_seconds": risk.same_direction_dedupe_window_seconds,
            "max_position_qty": str(risk.max_position_qty) if risk.max_position_qty is not None else None,
            "max_order_qty": str(risk.max_order_qty) if risk.max_order_qty is not None else None,
            "cooldown_mode": risk.cooldown_mode,
        },
        "exchange": {
            "mode": exchange.mode,
            "paper_filled": exchange.paper_filled,
        },
    }


def _compute_fingerprint(canonical: Dict[str, Any]) -> str:
    """规范化 JSON 后 SHA256 前 16 字符。"""
    raw = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class StrategyConfigResolverError(Exception):
    """策略解析失败（不存在 / 禁用）。"""
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        self.message = message
        super().__init__(message)


def resolve(app_config: "AppConfig", strategy_id: str) -> ResolvedStrategyConfig:
    """
    根据 strategy_id 从 AppConfig 解析并合并配置，生成 ResolvedStrategyConfig。
    运行期强假设：只读 app_config，不修改。

    Raises:
        StrategyConfigResolverError: 策略不存在（STRATEGY_NOT_FOUND）或被禁用（STRATEGY_DISABLED）
    """
    sid = (strategy_id or "").strip()
    if not sid:
        raise StrategyConfigResolverError(STRATEGY_NOT_FOUND, "strategy_id is empty")

    entry = app_config.strategies.get(sid)
    if entry is None:
        raise StrategyConfigResolverError(STRATEGY_NOT_FOUND, f"strategy_id not found: {sid}")
    if not getattr(entry, "enabled", True):
        raise StrategyConfigResolverError(STRATEGY_DISABLED, f"strategy disabled: {sid}")

    execution = entry.execution_override if entry.execution_override is not None else app_config.execution
    risk = entry.risk_override if entry.risk_override is not None else app_config.risk
    exchange = entry.exchange_override if entry.exchange_override is not None else app_config.exchange
    ep_id = (entry.exchange_profile_id or "").strip() or "paper"
    acc_id = (entry.account_id or "").strip() or "default"

    canonical = _canonical_config_dict(execution, risk, exchange, acc_id, ep_id)
    fingerprint = _compute_fingerprint(canonical)

    return ResolvedStrategyConfig(
        strategy_id=sid,
        execution=execution,
        risk=risk,
        exchange=exchange,
        strategy_config_fingerprint=fingerprint,
        account_id=acc_id,
        exchange_profile_id=ep_id,
    )
