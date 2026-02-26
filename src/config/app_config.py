"""
统一配置结构（PR10）：AppConfig + 强校验，WorkerConfig/RiskConfig 来源统一。
"""
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from src.utils.config import load_config as _load_config_dict
from src.common.config_errors import ConfigValidationError
from src.common.reason_codes import (
    INVALID_DATABASE_CONFIGURATION,
    INVALID_EXECUTION_CONFIGURATION,
    INVALID_RISK_CONFIGURATION,
    MULTI_STRATEGY_POSITION_DOWNGRADE_FORBIDDEN,
    INVALID_ACCOUNT_CONFIGURATION,
    MISSING_EXCHANGE_PROFILE,
    MISSING_ACCOUNT,
    ACCOUNT_EXCHANGE_MISMATCH,
    LIVE_GATE_MISSING_ACCOUNT_ID,
    LIVE_GATE_MISSING_EXCHANGE_PROFILE_ID,
    LIVE_GATE_ACCOUNT_NOT_FOUND,
    LIVE_GATE_EXCHANGE_PROFILE_NOT_FOUND,
    LIVE_GATE_ACCOUNT_EXCHANGE_MISMATCH,
    LIVE_GATE_SYMBOL_PRECISION_MISSING,
    LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED,
    LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED,
    OKX_SECRET_MISSING,
    OKX_LIVE_FORBIDDEN,
)


@dataclass
class DatabaseConfig:
    url: str = ""


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: Optional[str] = None
    database: bool = False


@dataclass
class WebhookConfig:
    tradingview_secret: Optional[str] = None


# PR16：执行模式（演练/灰度）
EXECUTION_MODE_DRY_RUN = "DRY_RUN"
EXECUTION_MODE_DEMO_LIVE_REHEARSAL = "DEMO_LIVE_REHEARSAL"


@dataclass
class ExecutionConfig:
    poll_interval_seconds: float = 1.0
    batch_size: int = 10
    max_concurrency: int = 5
    max_attempts: int = 3
    backoff_seconds: List[int] = field(default_factory=lambda: [1, 5, 30])
    # PR13：安全阀（默认关闭/不限）
    dry_run: bool = False
    max_orders_per_minute: int = 0  # 0 = 不限
    circuit_breaker_threshold: int = 0  # 0 = 关闭
    circuit_breaker_open_seconds: int = 60
    # PR14a：实盘门禁（true 时禁止默认回退，所有 enabled 策略须显式 account_id + exchange_profile_id）
    live_enabled: bool = False
    # PR16：多重 Live 门禁（上线前保险丝）
    allow_real_trading: bool = False  # 默认 false，必须显式开启才允许真实交易所请求（含 Demo）
    live_allowlist_accounts: List[str] = field(default_factory=list)  # 非空时仅允许列表内 account_id
    live_confirm_token: str = ""  # 须与环境变量 LIVE_CONFIRM_TOKEN 一致
    # PR16：执行模式（DRY_RUN | DEMO_LIVE_REHEARSAL）
    mode: str = EXECUTION_MODE_DRY_RUN
    # PR16：演练模式下的更严限制（DEMO_LIVE_REHEARSAL 时生效）
    rehearsal_max_orders_per_minute: int = 2
    rehearsal_circuit_breaker_threshold: int = 2
    rehearsal_circuit_breaker_open_seconds: int = 120
    # PR16：参数精度与数量校验（交易所级，本地拒绝）
    order_qty_precision: int = 8  # OKX sz 小数位上限，可配置
    order_market_max_notional: Optional[float] = None  # 市价单最大名义价值，None 不限制
    # PR16c：qty 精度按 symbol 覆盖（不接 instruments API）；is_live_endpoint 时 live_allowlist_symbols 中 symbol 须在此显式配置
    qty_precision_by_symbol: Dict[str, int] = field(default_factory=dict)  # symbol -> 小数位上限，空则全用 order_qty_precision
    live_allowlist_symbols: List[str] = field(default_factory=list)  # is_live_endpoint 时仅允许此列表内 symbol
    # PR17b：极小额 live 风险限制（仅 is_live_endpoint 时校验）
    live_max_order_notional: Optional[float] = None  # 单笔最大名义价值 USDT，如 5
    live_max_order_qty: Optional[float] = None  # 单笔最大 qty，可选
    live_max_orders_per_day: int = 0  # 0=不限
    live_max_orders_per_hour: int = 0  # 0=不限
    live_last_price_override: Optional[float] = None  # 测试用：覆盖 last_price 用于 notional 校验


@dataclass
class RiskSectionConfig:
    """PR10 统一配置中的 risk 区段，与 execution.risk_config.RiskConfig 区分。PR15c：资金/敞口开关。"""
    cooldown_seconds: float = 0.0
    same_direction_dedupe_window_seconds: float = 0.0
    max_position_qty: Optional[Decimal] = None
    max_order_qty: Optional[Decimal] = None
    cooldown_mode: str = "after_fill"
    # PR15c：默认关闭，仅开启时做余额/总敞口检查
    enable_balance_checks: bool = False
    enable_total_exposure_checks: bool = False
    max_exposure_ratio: Optional[float] = None  # 总敞口 <= equity * max_exposure_ratio
    quote_asset_for_balance: str = "USDT"  # BUY 时校验该 quote 资产可用余额


@dataclass
class ExchangeConfig:
    mode: str = "paper"
    paper_filled: bool = True


@dataclass
class ExchangeProfileConfig:
    """PR13：交易所 profile，显式 id/name/mode。"""
    id: str = ""
    name: str = "paper"
    mode: str = "paper"


@dataclass
class AccountProfileConfig:
    """PR13：账户 profile，显式绑定 exchange_profile。"""
    account_id: str = ""
    exchange_profile_id: str = ""


@dataclass
class OkxConfig:
    """PR14b：OKX Demo/Sandbox 配置。密钥仅从 AppConfig 读取，禁止写入 log/events/snapshot。"""
    env: str = "demo"  # PR14b 唯一允许值，确保不打实盘
    api_key: str = ""
    secret: str = ""
    passphrase: str = ""


@dataclass
class StrategyEntryConfig:
    """PR11：单策略配置项；PR13：可选 exchange_profile_id / account_id 显式绑定。"""
    enabled: bool = True
    execution_override: Optional["ExecutionConfig"] = None
    risk_override: Optional["RiskSectionConfig"] = None
    exchange_override: Optional["ExchangeConfig"] = None
    exchange_profile_id: Optional[str] = None  # PR13：显式绑定
    account_id: Optional[str] = None  # PR13：显式绑定


@dataclass
class AppConfig:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    risk: RiskSectionConfig = field(default_factory=RiskSectionConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    strategy_id: Optional[str] = None  # 兼容：单策略时从 config.strategy.strategy_id 来
    strategies: Dict[str, StrategyEntryConfig] = field(default_factory=dict)  # PR11：strategy_id -> 策略项
    # PR13：账户/交易所显式建模；strategy → exchange_profile → account 须显式配置
    exchange_profiles: Dict[str, ExchangeProfileConfig] = field(default_factory=dict)  # id -> profile
    accounts: Dict[str, AccountProfileConfig] = field(default_factory=dict)  # account_id -> profile
    # PR14b：OKX Demo 配置（可选）；使用 okx_demo profile 时必填且 fail-fast
    okx: Optional["OkxConfig"] = None

    def validate(self) -> None:
        """强校验：不通过则抛 ConfigValidationError(reason_code 按 database/execution/risk 分类)。"""
        if not (self.database.url or "").strip():
            raise ConfigValidationError(
                INVALID_DATABASE_CONFIGURATION,
                "database.url is required",
            )
        ex = self.execution
        if not (1 <= ex.batch_size <= 1000):
            raise ConfigValidationError(
                INVALID_EXECUTION_CONFIGURATION,
                f"execution.batch_size must be 1..1000, got {ex.batch_size}",
            )
        if not (1 <= ex.max_concurrency <= 100):
            raise ConfigValidationError(
                INVALID_EXECUTION_CONFIGURATION,
                f"execution.max_concurrency must be 1..100, got {ex.max_concurrency}",
            )
        if not (1 <= ex.max_attempts <= 10):
            raise ConfigValidationError(
                INVALID_EXECUTION_CONFIGURATION,
                f"execution.max_attempts must be 1..10, got {ex.max_attempts}",
            )
        if len(ex.backoff_seconds) < ex.max_attempts:
            raise ConfigValidationError(
                INVALID_EXECUTION_CONFIGURATION,
                f"execution.backoff_seconds length must be >= max_attempts ({ex.max_attempts})",
            )
        if ex.max_orders_per_minute < 0:
            raise ConfigValidationError(
                INVALID_EXECUTION_CONFIGURATION,
                "execution.max_orders_per_minute must be >= 0",
            )
        if ex.circuit_breaker_threshold < 0:
            raise ConfigValidationError(
                INVALID_EXECUTION_CONFIGURATION,
                "execution.circuit_breaker_threshold must be >= 0",
            )
        if ex.circuit_breaker_open_seconds < 0:
            raise ConfigValidationError(
                INVALID_EXECUTION_CONFIGURATION,
                "execution.circuit_breaker_open_seconds must be >= 0",
            )
        # PR16c：live_allowlist_symbols 非空时，每个 symbol 须在 qty_precision_by_symbol 中显式配置（启动 fail-fast）
        allowlist_syms = getattr(ex, "live_allowlist_symbols", None) or []
        if allowlist_syms:
            qty_by_sym = getattr(ex, "qty_precision_by_symbol", None) or {}
            for sym in allowlist_syms:
                if sym not in qty_by_sym:
                    raise ConfigValidationError(
                        LIVE_GATE_SYMBOL_PRECISION_MISSING,
                        f"live_allowlist_symbols contains {sym!r} but qty_precision_by_symbol has no entry for it",
                    )
        # PR17a：live_enabled 或 allow_real_trading 时，allowlist_accounts 与 allowlist_symbols 必须非空
        if getattr(ex, "live_enabled", False) or getattr(ex, "allow_real_trading", False):
            if not (getattr(ex, "live_allowlist_accounts", None) or []):
                raise ConfigValidationError(
                    LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED,
                    "live_enabled or allow_real_trading=true requires non-empty live_allowlist_accounts",
                )
            if not allowlist_syms:
                raise ConfigValidationError(
                    LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED,
                    "live_enabled or allow_real_trading=true requires non-empty live_allowlist_symbols",
                )
        # PR14a：实盘门禁（live_enabled=true 时禁止默认回退，所有 enabled 策略须显式配置）
        if getattr(ex, "live_enabled", False):
            for sid, entry in self.strategies.items():
                if not getattr(entry, "enabled", True):
                    continue
                acc_id = (getattr(entry, "account_id", None) or "").strip()
                ep_id = (getattr(entry, "exchange_profile_id", None) or "").strip()
                if not acc_id:
                    raise ConfigValidationError(
                        LIVE_GATE_MISSING_ACCOUNT_ID,
                        f"live_enabled=true: strategies[{sid}].account_id is required for all enabled strategies",
                    )
                if not ep_id:
                    raise ConfigValidationError(
                        LIVE_GATE_MISSING_EXCHANGE_PROFILE_ID,
                        f"live_enabled=true: strategies[{sid}].exchange_profile_id is required for all enabled strategies",
                    )
                if ep_id not in self.exchange_profiles:
                    raise ConfigValidationError(
                        LIVE_GATE_EXCHANGE_PROFILE_NOT_FOUND,
                        f"live_enabled=true: strategies[{sid}].exchange_profile_id={ep_id!r} not found in exchange_profiles",
                    )
                if acc_id not in self.accounts:
                    raise ConfigValidationError(
                        LIVE_GATE_ACCOUNT_NOT_FOUND,
                        f"live_enabled=true: strategies[{sid}].account_id={acc_id!r} not found in accounts",
                    )
                acc_profile = self.accounts.get(acc_id)
                if acc_profile and (acc_profile.exchange_profile_id or "").strip() != ep_id:
                    raise ConfigValidationError(
                        LIVE_GATE_ACCOUNT_EXCHANGE_MISMATCH,
                        f"live_enabled=true: strategies[{sid}] account_id={acc_id!r} exchange_profile_id does not match strategy exchange_profile_id={ep_id!r}",
                    )
        if self.risk.cooldown_mode not in ("after_fill", "after_pass"):
            raise ConfigValidationError(
                INVALID_RISK_CONFIGURATION,
                f"risk.cooldown_mode must be 'after_fill' or 'after_pass', got {self.risk.cooldown_mode!r}",
            )
        if self.risk.max_position_qty is not None and self.risk.max_position_qty <= 0:
            raise ConfigValidationError(
                INVALID_RISK_CONFIGURATION,
                "risk.max_position_qty must be > 0 when set",
            )
        if self.risk.max_order_qty is not None and self.risk.max_order_qty <= 0:
            raise ConfigValidationError(
                INVALID_RISK_CONFIGURATION,
                "risk.max_order_qty must be > 0 when set",
            )
        # PR11：校验每个 strategy 的合并配置
        for sid, entry in self.strategies.items():
            if not (sid or "").strip():
                raise ConfigValidationError(
                    INVALID_RISK_CONFIGURATION,
                    "strategies key strategy_id cannot be empty",
                )
            ex = entry.execution_override if entry.execution_override is not None else self.execution
            risk = entry.risk_override if entry.risk_override is not None else self.risk
            if not (1 <= ex.batch_size <= 1000):
                raise ConfigValidationError(
                    INVALID_EXECUTION_CONFIGURATION,
                    f"strategies[{sid}].execution.batch_size must be 1..1000, got {ex.batch_size}",
                )
            if len(ex.backoff_seconds) < ex.max_attempts:
                raise ConfigValidationError(
                    INVALID_EXECUTION_CONFIGURATION,
                    f"strategies[{sid}].execution.backoff_seconds length must be >= max_attempts",
                )
            if risk.cooldown_mode not in ("after_fill", "after_pass"):
                raise ConfigValidationError(
                    INVALID_RISK_CONFIGURATION,
                    f"strategies[{sid}].risk.cooldown_mode must be after_fill or after_pass",
                )
            # PR13：strategy → exchange_profile → account 显式绑定 fail-fast
            ep_id = getattr(entry, "exchange_profile_id", None) or ""
            acc_id = getattr(entry, "account_id", None) or ""
            if (ep_id or acc_id) and (ep_id or acc_id):
                ep_id = (ep_id or "").strip()
                acc_id = (acc_id or "").strip()
                if ep_id and ep_id not in self.exchange_profiles:
                    raise ConfigValidationError(
                        INVALID_ACCOUNT_CONFIGURATION,
                        f"strategies[{sid}].exchange_profile_id={ep_id!r} not found in exchange_profiles",
                    )
                if acc_id and acc_id not in self.accounts:
                    raise ConfigValidationError(
                        INVALID_ACCOUNT_CONFIGURATION,
                        f"strategies[{sid}].account_id={acc_id!r} not found in accounts",
                    )
                if acc_id and ep_id:
                    acc_profile = self.accounts.get(acc_id)
                    if acc_profile and (acc_profile.exchange_profile_id or "").strip() != ep_id:
                        raise ConfigValidationError(
                            INVALID_ACCOUNT_CONFIGURATION,
                            f"strategies[{sid}] account_id={acc_id!r} exchange_profile_id does not match strategy exchange_profile_id={ep_id!r}",
                        )
        # PR14b：使用 okx_demo 或 okx 的 profile 时，okx 配置必填且 demo 下 key/secret/passphrase 非空
        uses_okx = any(
            (epid == "okx_demo" or (getattr(p, "mode", "") or "").lower() in ("okx_demo", "okx") or (getattr(p, "name", "") or "").lower() in ("okx_demo", "okx"))
            for epid, p in self.exchange_profiles.items()
        )
        if uses_okx:
            if self.okx is None:
                raise ConfigValidationError(
                    OKX_SECRET_MISSING,
                    "exchange_profiles use okx_demo/okx but okx config section is missing",
                )
            env_okx = (self.okx.env or "").strip().lower()
            if env_okx not in ("demo", "live"):
                raise ConfigValidationError(
                    OKX_LIVE_FORBIDDEN,
                    "okx.env must be 'demo' or 'live'",
                )
            if not (self.okx.api_key or "").strip():
                raise ConfigValidationError(
                    OKX_SECRET_MISSING,
                    "okx.api_key is required when using okx_demo profile",
                )
            if not (self.okx.secret or "").strip():
                raise ConfigValidationError(
                    OKX_SECRET_MISSING,
                    "okx.secret is required when using okx_demo profile",
                )
            if not (self.okx.passphrase or "").strip():
                raise ConfigValidationError(
                    OKX_SECRET_MISSING,
                    "okx.passphrase is required when using okx_demo profile",
                )
        # 封版：多策略 position_snapshot 不可逆性显式约束；多策略时禁止允许降级（降级会丢非 default 数据）
        if len(self.strategies) > 1 and (os.environ.get("ALLOW_POSITION_SCHEMA_DOWNGRADE") or "").strip().lower() == "true":
            raise ConfigValidationError(
                MULTI_STRATEGY_POSITION_DOWNGRADE_FORBIDDEN,
                "multi-strategy mode does not allow position schema downgrade; "
                "ALLOW_POSITION_SCHEMA_DOWNGRADE must not be set when strategies > 1 (downgrade would lose non-default strategy position data)",
            )


def _int(v: Any, default: int) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _float(v: Any, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _decimal(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _parse_execution_cfg(exec_cfg: Dict[str, Any], env_prefix: str = "") -> ExecutionConfig:
    """从 dict 解析 ExecutionConfig；env_prefix 用于策略级不读 env。PR16：mode/allow_real_trading/allowlist/token/rehearsal/order 精度。"""
    backoff_raw = exec_cfg.get("backoff_seconds")
    if backoff_raw is None and not env_prefix:
        backoff_raw = os.environ.get("EXEC_BACKOFF_SECONDS", "")
    if isinstance(backoff_raw, str):
        backoff_raw = [int(x.strip()) for x in backoff_raw.split(",") if x.strip()] if backoff_raw else [1, 5, 30]
    if not isinstance(backoff_raw, list) or not backoff_raw:
        backoff_raw = [1, 5, 30]
    allowlist_raw = exec_cfg.get("live_allowlist_accounts")
    if isinstance(allowlist_raw, list):
        allowlist = [str(x).strip() for x in allowlist_raw if str(x).strip()]
    else:
        allowlist = []
    # PR16c：qty_precision_by_symbol（dict symbol->int）、live_allowlist_symbols（list）
    qty_precision_by_symbol: Dict[str, int] = {}
    raw_qty = exec_cfg.get("qty_precision_by_symbol")
    if isinstance(raw_qty, dict):
        for k, v in raw_qty.items():
            if k and isinstance(k, str) and isinstance(v, (int, float)):
                qty_precision_by_symbol[str(k).strip()] = int(v)
    live_allowlist_symbols: List[str] = []
    raw_syms = exec_cfg.get("live_allowlist_symbols")
    if isinstance(raw_syms, list):
        live_allowlist_symbols = [str(x).strip() for x in raw_syms if str(x).strip()]
    if not env_prefix and os.environ.get("LIVE_CONFIRM_TOKEN"):
        confirm_token = (exec_cfg.get("live_confirm_token") or os.environ.get("LIVE_CONFIRM_TOKEN", "")).strip()
    else:
        confirm_token = (exec_cfg.get("live_confirm_token") or "").strip()
    mode = (exec_cfg.get("mode") or EXECUTION_MODE_DRY_RUN).strip().upper()
    if mode not in (EXECUTION_MODE_DRY_RUN, EXECUTION_MODE_DEMO_LIVE_REHEARSAL):
        mode = EXECUTION_MODE_DRY_RUN
    return ExecutionConfig(
        poll_interval_seconds=_float(exec_cfg.get("poll_interval_seconds"), 1.0),
        batch_size=_int(exec_cfg.get("batch_size"), 10),
        max_concurrency=_int(exec_cfg.get("max_concurrency"), 5),
        max_attempts=_int(exec_cfg.get("max_attempts"), 3),
        backoff_seconds=backoff_raw,
        dry_run=bool(exec_cfg.get("dry_run", False)),
        max_orders_per_minute=_int(exec_cfg.get("max_orders_per_minute"), 0),
        circuit_breaker_threshold=_int(exec_cfg.get("circuit_breaker_threshold"), 0),
        circuit_breaker_open_seconds=_int(exec_cfg.get("circuit_breaker_open_seconds"), 60),
        live_enabled=bool(exec_cfg.get("live_enabled", False)),
        allow_real_trading=bool(exec_cfg.get("allow_real_trading", False)),
        live_allowlist_accounts=allowlist,
        live_confirm_token=confirm_token,
        mode=mode,
        rehearsal_max_orders_per_minute=_int(exec_cfg.get("rehearsal_max_orders_per_minute"), 2),
        rehearsal_circuit_breaker_threshold=_int(exec_cfg.get("rehearsal_circuit_breaker_threshold"), 2),
        rehearsal_circuit_breaker_open_seconds=_int(exec_cfg.get("rehearsal_circuit_breaker_open_seconds"), 120),
        order_qty_precision=_int(exec_cfg.get("order_qty_precision"), 8),
        order_market_max_notional=_float(exec_cfg.get("order_market_max_notional"), 0.0) or None,
        qty_precision_by_symbol=qty_precision_by_symbol,
        live_allowlist_symbols=live_allowlist_symbols,
        live_max_order_notional=_float(exec_cfg.get("live_max_order_notional"), 0.0) or None,
        live_max_order_qty=_float(exec_cfg.get("live_max_order_qty"), 0.0) or None,
        live_max_orders_per_day=_int(exec_cfg.get("live_max_orders_per_day"), 0),
        live_max_orders_per_hour=_int(exec_cfg.get("live_max_orders_per_hour"), 0),
        live_last_price_override=_float(exec_cfg.get("live_last_price_override"), 0.0) or None,
    )


def _parse_risk_section_cfg(risk_cfg: Dict[str, Any]) -> RiskSectionConfig:
    """从 dict 解析 RiskSectionConfig。PR15c：enable_balance_checks / enable_total_exposure_checks / max_exposure_ratio。"""
    return RiskSectionConfig(
        cooldown_seconds=_float(risk_cfg.get("cooldown_seconds"), 0.0),
        same_direction_dedupe_window_seconds=_float(risk_cfg.get("same_direction_dedupe_window_seconds"), 0.0),
        max_position_qty=_decimal(risk_cfg.get("max_position_qty")),
        max_order_qty=_decimal(risk_cfg.get("max_order_qty")),
        cooldown_mode=(risk_cfg.get("cooldown_mode") or "after_fill"),
        enable_balance_checks=bool(risk_cfg.get("enable_balance_checks", False)),
        enable_total_exposure_checks=bool(risk_cfg.get("enable_total_exposure_checks", False)),
        max_exposure_ratio=_float(risk_cfg.get("max_exposure_ratio"), 0.0) or None,
        quote_asset_for_balance=(risk_cfg.get("quote_asset_for_balance") or "USDT").strip() or "USDT",
    )


def _parse_exchange_cfg(ex_cfg: Dict[str, Any]) -> ExchangeConfig:
    """从 dict 解析 ExchangeConfig。"""
    return ExchangeConfig(
        mode=ex_cfg.get("name") or "paper",
        paper_filled=ex_cfg.get("paper_filled", True),
    )


def _parse_strategy_entry(entry: Dict[str, Any], default_exec: ExecutionConfig, default_risk: RiskSectionConfig, default_exchange: ExchangeConfig) -> StrategyEntryConfig:
    """从单条 strategy 条目 dict 解析 StrategyEntryConfig，未给字段用默认。PR13：exchange_profile_id / account_id。"""
    enabled = entry.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("true", "1", "yes")
    exec_over = None
    if entry.get("execution_override"):
        exec_over = _parse_execution_cfg(entry.get("execution_override") or {}, env_prefix="strategy")
    risk_over = None
    if entry.get("risk_override"):
        risk_over = _parse_risk_section_cfg(entry.get("risk_override") or {})
    ex_over = None
    if entry.get("exchange_override"):
        ex_over = _parse_exchange_cfg(entry.get("exchange_override") or {})
    ep_id = entry.get("exchange_profile_id") or entry.get("exchange_profile")
    acc_id = entry.get("account_id")
    if isinstance(ep_id, str):
        ep_id = ep_id.strip() or None
    if isinstance(acc_id, str):
        acc_id = acc_id.strip() or None
    return StrategyEntryConfig(
        enabled=enabled,
        execution_override=exec_over,
        risk_override=risk_over,
        exchange_override=ex_over,
        exchange_profile_id=ep_id,
        account_id=acc_id,
    )


def _from_dict(d: Dict[str, Any]) -> AppConfig:
    """从 load_config() 返回的 dict 构建 AppConfig，并应用环境变量覆盖。PR11：解析 strategies，向后兼容单 strategy_id。"""
    db = d.get("database") or {}
    url = (db.get("url") or "").strip()
    if not url and os.environ.get("DATABASE_URL"):
        url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        url = "sqlite+aiosqlite:///./trading_system.db"
    log = d.get("logging") or {}
    tv = d.get("tradingview") or d.get("webhook") or {}
    secret = tv.get("webhook_secret") or os.environ.get("TV_WEBHOOK_SECRET")
    exec_cfg = d.get("execution") or {}
    backoff_raw = exec_cfg.get("backoff_seconds")
    if backoff_raw is None:
        backoff_raw = os.environ.get("EXEC_BACKOFF_SECONDS", "")
    if isinstance(backoff_raw, str):
        backoff_raw = [int(x.strip()) for x in backoff_raw.split(",") if x.strip()] if backoff_raw else [1, 5, 30]
    risk_cfg = d.get("risk") or {}
    strat = d.get("strategy") or {}
    strategy_id = strat.get("strategy_id") or os.environ.get("STRATEGY_ID")

    execution = _parse_execution_cfg(exec_cfg)
    # 环境变量覆盖（与原有 _from_dict 一致）
    execution = ExecutionConfig(
        poll_interval_seconds=_float(exec_cfg.get("poll_interval_seconds"), _float(os.environ.get("EXEC_POLL_INTERVAL"), 1.0)),
        batch_size=_int(exec_cfg.get("batch_size"), _int(os.environ.get("EXEC_BATCH_SIZE"), 10)),
        max_concurrency=_int(exec_cfg.get("max_concurrency"), _int(os.environ.get("EXEC_MAX_CONCURRENCY"), 5)),
        max_attempts=_int(exec_cfg.get("max_attempts"), _int(os.environ.get("EXEC_MAX_ATTEMPTS"), 3)),
        backoff_seconds=execution.backoff_seconds,
        dry_run=execution.dry_run,
        max_orders_per_minute=execution.max_orders_per_minute,
        circuit_breaker_threshold=execution.circuit_breaker_threshold,
        circuit_breaker_open_seconds=execution.circuit_breaker_open_seconds,
        live_enabled=execution.live_enabled,
        allow_real_trading=execution.allow_real_trading,
        live_allowlist_accounts=execution.live_allowlist_accounts,
        live_confirm_token=execution.live_confirm_token,
        mode=execution.mode,
        rehearsal_max_orders_per_minute=execution.rehearsal_max_orders_per_minute,
        rehearsal_circuit_breaker_threshold=execution.rehearsal_circuit_breaker_threshold,
        rehearsal_circuit_breaker_open_seconds=execution.rehearsal_circuit_breaker_open_seconds,
        order_qty_precision=execution.order_qty_precision,
        order_market_max_notional=execution.order_market_max_notional,
        qty_precision_by_symbol=getattr(execution, "qty_precision_by_symbol", None) or {},
        live_allowlist_symbols=getattr(execution, "live_allowlist_symbols", None) or [],
        live_max_order_notional=getattr(execution, "live_max_order_notional", None),
        live_max_order_qty=getattr(execution, "live_max_order_qty", None),
        live_max_orders_per_day=getattr(execution, "live_max_orders_per_day", 0),
        live_max_orders_per_hour=getattr(execution, "live_max_orders_per_hour", 0),
        live_last_price_override=getattr(execution, "live_last_price_override", None),
    )
    risk = RiskSectionConfig(
        cooldown_seconds=_float(risk_cfg.get("cooldown_seconds"), _float(os.environ.get("RISK_COOLDOWN_SECONDS"), 0.0)),
        same_direction_dedupe_window_seconds=_float(risk_cfg.get("same_direction_dedupe_window_seconds"), _float(os.environ.get("RISK_SAME_DIRECTION_WINDOW_SECONDS"), 0.0)),
        max_position_qty=_decimal(risk_cfg.get("max_position_qty") or os.environ.get("RISK_MAX_POSITION_QTY")),
        max_order_qty=_decimal(risk_cfg.get("max_order_qty") or os.environ.get("RISK_MAX_ORDER_QTY")),
        cooldown_mode=(risk_cfg.get("cooldown_mode") or "after_fill"),
        enable_balance_checks=bool(risk_cfg.get("enable_balance_checks", False) or os.environ.get("RISK_ENABLE_BALANCE_CHECKS", "false").lower() == "true"),
        enable_total_exposure_checks=bool(risk_cfg.get("enable_total_exposure_checks", False) or os.environ.get("RISK_ENABLE_TOTAL_EXPOSURE_CHECKS", "false").lower() == "true"),
        max_exposure_ratio=_float(risk_cfg.get("max_exposure_ratio") or os.environ.get("RISK_MAX_EXPOSURE_RATIO"), 0.0) or None,
        quote_asset_for_balance=(risk_cfg.get("quote_asset_for_balance") or os.environ.get("RISK_QUOTE_ASSET_FOR_BALANCE") or "USDT").strip() or "USDT",
    )
    exchange = ExchangeConfig(
        mode=(d.get("exchange") or {}).get("name") or "paper",
        paper_filled=True,
    )

    # PR11：解析 strategies；向后兼容：strategies 为空但存在顶层 strategy_id 时视为默认策略
    strategies_raw = d.get("strategies")
    strategies: Dict[str, StrategyEntryConfig] = {}
    if strategies_raw and isinstance(strategies_raw, dict):
        for sid, entry in strategies_raw.items():
            if not sid or not isinstance(sid, str) or not sid.strip():
                continue
            sid = str(sid).strip()
            entry_dict = entry if isinstance(entry, dict) else {}
            strategies[sid] = _parse_strategy_entry(entry_dict, execution, risk, exchange)
    if not strategies and strategy_id and str(strategy_id).strip():
        strategies[str(strategy_id).strip()] = StrategyEntryConfig(enabled=True)

    # PR13：exchange_profiles / accounts
    exchange_profiles: Dict[str, ExchangeProfileConfig] = {}
    for epid, ep in (d.get("exchange_profiles") or {}).items():
        if not epid or not isinstance(ep, dict):
            continue
        exchange_profiles[str(epid).strip()] = ExchangeProfileConfig(
            id=str(epid).strip(),
            name=(ep.get("name") or "paper"),
            mode=(ep.get("mode") or "paper"),
        )
    # PR14b：OKX 配置；有 okx 时默认提供 okx_demo profile 以便“默认交易所=OKX”
    okx_cfg = d.get("okx")
    okx_config: Optional[OkxConfig] = None
    if okx_cfg and isinstance(okx_cfg, dict):
        okx_config = OkxConfig(
            env=(okx_cfg.get("env") or "demo").strip().lower() or "demo",
            api_key=(okx_cfg.get("api_key") or os.environ.get("OKX_API_KEY") or "").strip(),
            secret=(okx_cfg.get("secret") or os.environ.get("OKX_SECRET") or "").strip(),
            passphrase=(okx_cfg.get("passphrase") or os.environ.get("OKX_PASSPHRASE") or "").strip(),
        )
        if "okx_demo" not in exchange_profiles:
            exchange_profiles["okx_demo"] = ExchangeProfileConfig(
                id="okx_demo",
                name="okx",
                mode="okx_demo",
            )
    accounts: Dict[str, AccountProfileConfig] = {}
    for accid, acc in (d.get("accounts") or {}).items():
        if not accid or not isinstance(acc, dict):
            continue
        accounts[str(accid).strip()] = AccountProfileConfig(
            account_id=str(accid).strip(),
            exchange_profile_id=(acc.get("exchange_profile_id") or acc.get("exchange_profile") or "").strip(),
        )

    return AppConfig(
        database=DatabaseConfig(url=url),
        logging=LoggingConfig(
            level=log.get("level") or os.environ.get("LOG_LEVEL", "INFO"),
            file=log.get("file") or os.environ.get("LOG_FILE"),
            database=(log.get("database") or os.environ.get("LOG_DATABASE", "false").lower() == "true"),
        ),
        webhook=WebhookConfig(tradingview_secret=secret),
        execution=execution,
        risk=risk,
        exchange=exchange,
        strategy_id=strategy_id,
        strategies=strategies,
        exchange_profiles=exchange_profiles,
        accounts=accounts,
        okx=okx_config,
    )


def load_app_config(config_path: Optional[str] = None) -> AppConfig:
    """加载配置并转为 AppConfig，校验通过后返回。校验失败抛 ConfigValidationError。PR15c：保留原始 dict 供 worker 的 MarketDataAdapter 读取 paper.prices。"""
    d = _load_config_dict(config_path)
    app_config = _from_dict(d)
    app_config.validate()
    setattr(app_config, "_raw_config", d)
    return app_config


def app_config_to_legacy_dict(app_config: AppConfig) -> Dict[str, Any]:
    """转为 PR5/PR4 兼容的 config 字典（signal_service 等仍用 config.get）。"""
    return {
        "database": {"url": app_config.database.url},
        "logging": {
            "level": app_config.logging.level,
            "file": app_config.logging.file,
            "database": app_config.logging.database,
        },
        "tradingview": {"webhook_secret": app_config.webhook.tradingview_secret},
        "strategy": {"strategy_id": app_config.strategy_id},
    }
