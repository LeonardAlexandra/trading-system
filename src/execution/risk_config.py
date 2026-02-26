"""
风控配置（PR9：可配置规则参数）
"""
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional


@dataclass
class RiskConfig:
    """风控规则参数，默认宽松（0/无穷）。PR15c：资金/敞口检查开关默认关闭。"""
    cooldown_seconds: float = 0.0
    same_direction_dedupe_window_seconds: float = 0.0
    max_position_qty: Optional[Decimal] = None  # None 表示不限制
    max_order_qty: Optional[Decimal] = None  # None 表示不限制
    # PR15c：默认 false，仅开启时做余额/总敞口检查
    enable_balance_checks: bool = False
    enable_total_exposure_checks: bool = False
    max_exposure_ratio: Optional[float] = None
    quote_asset_for_balance: str = "USDT"

    @classmethod
    def from_env(cls) -> "RiskConfig":
        def _float(key: str, default: float) -> float:
            try:
                return float(os.environ.get(key, default))
            except (TypeError, ValueError):
                return default

        def _decimal(key: str, default: Optional[Decimal]) -> Optional[Decimal]:
            raw = os.environ.get(key, "")
            if not raw:
                return default
            try:
                return Decimal(raw)
            except Exception:
                return default

        return cls(
            cooldown_seconds=_float("RISK_COOLDOWN_SECONDS", 0.0),
            same_direction_dedupe_window_seconds=_float("RISK_SAME_DIRECTION_WINDOW_SECONDS", 0.0),
            max_position_qty=_decimal("RISK_MAX_POSITION_QTY", None),
            max_order_qty=_decimal("RISK_MAX_ORDER_QTY", None),
            enable_balance_checks=(os.environ.get("RISK_ENABLE_BALANCE_CHECKS", "false").lower() == "true"),
            enable_total_exposure_checks=(os.environ.get("RISK_ENABLE_TOTAL_EXPOSURE_CHECKS", "false").lower() == "true"),
            max_exposure_ratio=_float(os.environ.get("RISK_MAX_EXPOSURE_RATIO"), 0.0) or None,
            quote_asset_for_balance=(os.environ.get("RISK_QUOTE_ASSET_FOR_BALANCE") or "USDT").strip() or "USDT",
        )

    @classmethod
    def from_app_config(cls, app_config: Any) -> "RiskConfig":
        """从 PR10 统一 AppConfig.risk 构建（来源统一）。PR15c：enable_balance_checks 等。"""
        r = app_config.risk
        return cls(
            cooldown_seconds=r.cooldown_seconds,
            same_direction_dedupe_window_seconds=r.same_direction_dedupe_window_seconds,
            max_position_qty=r.max_position_qty,
            max_order_qty=r.max_order_qty,
            enable_balance_checks=getattr(r, "enable_balance_checks", False),
            enable_total_exposure_checks=getattr(r, "enable_total_exposure_checks", False),
            max_exposure_ratio=getattr(r, "max_exposure_ratio", None),
            quote_asset_for_balance=getattr(r, "quote_asset_for_balance", "USDT") or "USDT",
        )

    @classmethod
    def from_risk_section(cls, risk_section: Any) -> "RiskConfig":
        """PR11：从 RiskSectionConfig 构建（策略级风控覆盖）。PR15c：enable_balance_checks 等。"""
        return cls(
            cooldown_seconds=getattr(risk_section, "cooldown_seconds", 0.0),
            same_direction_dedupe_window_seconds=getattr(
                risk_section, "same_direction_dedupe_window_seconds", 0.0
            ),
            max_position_qty=getattr(risk_section, "max_position_qty", None),
            max_order_qty=getattr(risk_section, "max_order_qty", None),
            enable_balance_checks=getattr(risk_section, "enable_balance_checks", False),
            enable_total_exposure_checks=getattr(risk_section, "enable_total_exposure_checks", False),
            max_exposure_ratio=getattr(risk_section, "max_exposure_ratio", None),
            quote_asset_for_balance=getattr(risk_section, "quote_asset_for_balance", "USDT") or "USDT",
        )
