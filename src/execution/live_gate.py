"""
PR16/PR17a/PR17b：多重 Live 门禁（仅针对 live 实盘 endpoint）。

- allow_real_trading / live_allowlist_accounts / live_confirm_token 仅针对「live endpoint 真实下单风险」；
  调用方仅在 is_live_endpoint=True 时调用本函数。
- Demo rehearsal（DEMO_LIVE_REHEARSAL）允许 OKX Demo HTTP，不触发上述门禁。
- PR17b：门禁全过且 live_enabled 时允许 live create_order（移除 PR17a 禁用逻辑）。
"""
import os
from dataclasses import dataclass
from typing import Any, List, Optional

from src.common.reason_codes import (
    LIVE_GATE_ACCOUNT_NOT_ALLOWED,
    LIVE_GATE_ALLOW_REAL_TRADING_OFF,
    LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED,
    LIVE_GATE_CONFIRM_TOKEN_MISSING,
    LIVE_GATE_CONFIRM_TOKEN_MISMATCH,
    LIVE_GATE_LIVE_ENABLED_REQUIRED,
)


@dataclass
class LiveGateResult:
    """门禁检查结果。allowed=False 时 reason_code 与 message 必填。"""
    allowed: bool
    reason_code: Optional[str] = None
    message: Optional[str] = None


def check_live_gates(
    *,
    dry_run: bool,
    live_enabled: bool,
    allow_real_trading: bool,
    live_allowlist_accounts: List[str],
    live_confirm_token_configured: str,
    account_id: Optional[str] = None,
    exchange_profile: Optional[str] = None,
    is_live_endpoint: bool = False,
) -> LiveGateResult:
    """
    多重 Live 门禁检查。仅当 is_live_endpoint=True 时由调用方调用；Demo 不调用。
    - dry_run=True：视为通过。
    - live_enabled=False：PR17b 要求 live_enabled 必须 true 才允许 live 下单。
    - allow_real_trading=False：禁止 live 真实交易，返回 LIVE_GATE_ALLOW_REAL_TRADING_OFF。
    - live_allowlist_accounts 为空：返回 LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED。
    - account_id 不在列表：返回 LIVE_GATE_ACCOUNT_NOT_ALLOWED。
    - live_confirm_token 或 LIVE_CONFIRM_TOKEN 缺失：返回 LIVE_GATE_CONFIRM_TOKEN_MISSING。
    - 两端均有值但不一致：返回 LIVE_GATE_CONFIRM_TOKEN_MISMATCH。
    - PR17b：门禁全过且 live_enabled 时允许 live create_order。
    """
    if dry_run:
        return LiveGateResult(allowed=True)
    if not is_live_endpoint:
        return LiveGateResult(allowed=True)

    if not live_enabled:
        return LiveGateResult(
            allowed=False,
            reason_code=LIVE_GATE_LIVE_ENABLED_REQUIRED,
            message="live_enabled must be true for live endpoint",
        )

    if not allow_real_trading:
        return LiveGateResult(
            allowed=False,
            reason_code=LIVE_GATE_ALLOW_REAL_TRADING_OFF,
            message="allow_real_trading is false",
        )

    if not live_allowlist_accounts:
        return LiveGateResult(
            allowed=False,
            reason_code=LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED,
            message="live_allowlist_accounts must be non-empty when live path is enabled",
        )

    if (account_id or "").strip() not in [a.strip() for a in live_allowlist_accounts if a]:
        return LiveGateResult(
            allowed=False,
            reason_code=LIVE_GATE_ACCOUNT_NOT_ALLOWED,
            message=f"account_id {account_id!r} not in live_allowlist_accounts",
        )

    env_token = (os.environ.get("LIVE_CONFIRM_TOKEN") or "").strip()
    if not live_confirm_token_configured or not env_token:
        return LiveGateResult(
            allowed=False,
            reason_code=LIVE_GATE_CONFIRM_TOKEN_MISSING,
            message="live_confirm_token or LIVE_CONFIRM_TOKEN is missing",
        )
    if live_confirm_token_configured != env_token:
        return LiveGateResult(
            allowed=False,
            reason_code=LIVE_GATE_CONFIRM_TOKEN_MISMATCH,
            message="live_confirm_token does not match LIVE_CONFIRM_TOKEN",
        )

    return LiveGateResult(allowed=True)


def get_execution_for_rehearsal(app_config: Any) -> Any:
    """
    PR16：DEMO_LIVE_REHEARSAL 模式下返回“演练用”执行参数（更严限频/断路器）。
    调用方可用此结果覆盖 resolved.execution 的限频/断路器字段。
    """
    if not app_config or getattr(app_config.execution, "mode", None) != "DEMO_LIVE_REHEARSAL":
        return None
    return app_config.execution
