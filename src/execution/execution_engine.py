"""
执行引擎（PR6 两段式幂等 + PR7 可观测性 + PR8 事件落库 + Phase1.1 C2 两阶段互斥保护）
C7：执行提交入口打点 latency_ms（可选 perf_repo）。
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

if TYPE_CHECKING:
    from src.config.app_config import AppConfig
    from src.repositories.perf_log_repository import PerfLogWriter

from src.models.decision_order_map_status import RESERVED, FILLED, FAILED, SUBMITTING, PENDING_EXCHANGE, TIMEOUT, UNKNOWN
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.risk_state_repository import RiskStateRepository
from src.repositories.rate_limit_repository import RateLimitRepository
from src.repositories.circuit_breaker_repository import CircuitBreakerRepository
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
from src.repositories.log_repository import LogRepository
from src.repositories.trade_repo import TradeRepository
from src.models.decision_snapshot import DecisionSnapshot
from src.models.trade import Trade, SOURCE_TYPE_SIGNAL
from src.execution.exchange_adapter import ExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.exceptions import TransientOrderError, PermanentOrderError
from src.execution.worker_config import WorkerConfig
from src.app.dependencies import get_db_session
from src.common.reason_codes import (
    SKIPPED_ALREADY_CLAIMED,
    RISK_REJECTED,
    EXCHANGE_TRANSIENT_ERROR,
    RETRY_SCHEDULED,
    RETRY_EXHAUSTED,
    ORDER_REJECTED,
    SUCCESS_FILLED,
    CONFIG_UNAVAILABLE,
    RATE_LIMIT_EXCEEDED,
    CIRCUIT_OPEN,
    ORDER_PARAM_INVALID,
    RECONCILE_LOCK_NOT_ACQUIRED,
    PENDING_EXCHANGE_ACK_NOT_COMMITTED,
)
from sqlalchemy import text
from src.locks.reconcile_lock import ReconcileLock
from src.common.event_types import (
    CLAIMED,
    CONFIG_SNAPSHOT,
    RISK_CHECK_STARTED,
    RISK_PASSED,
    RISK_REJECTED as EV_RISK_REJECTED,
    ORDER_SUBMIT_STARTED,
    ORDER_SUBMIT_OK,
    ORDER_SUBMIT_FAILED,
    RETRY_SCHEDULED as EV_RETRY_SCHEDULED,
    FINAL_FAILED,
    FILLED as EV_FILLED,
    CIRCUIT_OPENED,
    CIRCUIT_CLOSED,
    RATE_LIMIT_EXCEEDED as EV_RATE_LIMIT_EXCEEDED,
    OKX_HTTP_CREATE_ORDER as EV_OKX_HTTP_CREATE_ORDER,
    ORDER_REJECTED as EV_ORDER_REJECTED,
    PENDING_EXCHANGE_ACK_NOT_COMMITTED as EV_PENDING_EXCHANGE_ACK_NOT_COMMITTED,
)

logger = logging.getLogger(__name__)

# 无 config 时的默认重试参数（兼容测试）
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BACKOFF_SECONDS = [1, 5, 30]

# PR15b：通信审计 message 最大长度（不含 secret/header）
_OKX_HTTP_MESSAGE_MAX_LEN = 500


def _okx_http_create_order_message(
    http_status: Optional[int],
    okx_code: Optional[str],
    request_id: Optional[str],
    attempt: Optional[int] = None,
) -> str:
    """仅含 action/http_status/okx_code/request_id/attempt，受控长度。"""
    parts = ["action=CREATE_ORDER"]
    if http_status is not None:
        parts.append(f"http_status={http_status}")
    if okx_code is not None:
        parts.append(f"okx_code={okx_code}")
    if request_id:
        parts.append(f"request_id={(request_id or '')[:64]}")
    if attempt is not None:
        parts.append(f"attempt={attempt}")
    return " ".join(parts)[:_OKX_HTTP_MESSAGE_MAX_LEN]


async def _persist_exception_status(
    decision_id: str,
    status: str,
    *,
    local_order_id: Optional[str] = None,
    exchange_order_id: Optional[str] = None,
    attempt_count: Optional[int] = None,
    last_error: Optional[str] = None,
    next_run_at: Optional[datetime] = None,
    updated_at: Optional[datetime] = None,
    _caller_session: Optional[Any] = None,
) -> None:
    """
    封版 PR11/PR14：异常状态必须落库。使用独立 Session 显式 commit，保证 TIMEOUT/FAILED/UNKNOWN
    不会被 request-level rollback 回滚。
    SQLite：先 commit 调用方 session 以释放锁并保留本请求内已写事件，再用独立 session 将状态更新为 FAILED/TIMEOUT/UNKNOWN。
    """
    if status not in (FAILED, TIMEOUT, UNKNOWN):
        raise ValueError(f"persist_exception_status only for FAILED/TIMEOUT/UNKNOWN, got {status!r}")
    if _caller_session is not None:
        await _caller_session.commit()
    async with get_db_session() as error_session:
        error_repo = DecisionOrderMapRepository(error_session)
        await error_repo.update_after_exchange(
            decision_id,
            status,
            local_order_id=local_order_id,
            exchange_order_id=exchange_order_id,
            attempt_count=attempt_count,
            last_error=last_error,
            next_run_at=next_run_at,
            updated_at=updated_at,
        )
        await error_session.commit()


logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    执行引擎：事务A 抢占 → 风控 → 交易所调用 → 事务B 落库。
    幂等主键：decision_id = client_order_id。
    返回 dict 必含 decision_id、status；失败/跳过含 reason_code。
    PR8：执行过程写入 execution_events，不把外部调用放进事务。
    """

    def __init__(
        self,
        dom_repo: DecisionOrderMapRepository,
        exchange_adapter: ExchangeAdapter,
        risk_manager: RiskManager,
        config: Optional[WorkerConfig] = None,
        *,
        position_repo: Optional[PositionRepository] = None,
        risk_state_repo: Optional[RiskStateRepository] = None,
        rate_limit_repo: Optional[RateLimitRepository] = None,
        circuit_breaker_repo: Optional[CircuitBreakerRepository] = None,
        app_config: Optional["AppConfig"] = None,
        market_data_adapter: Optional[Any] = None,
        snapshot_repo: Optional[DecisionSnapshotRepository] = None,
        alert_callback: Optional[Callable[[str, str, str], None]] = None,
        log_repo: Optional[LogRepository] = None,
        perf_writer: Optional["PerfLogWriter"] = None,
        trade_repo: Optional[TradeRepository] = None,
    ):
        self._dom_repo = dom_repo
        self._snapshot_repo = snapshot_repo
        self._trade_repo = trade_repo
        self._alert_callback = alert_callback
        self._log_repo = log_repo
        self._perf_writer = perf_writer
        self._exchange = exchange_adapter
        self._risk = risk_manager
        self._config = config
        self._position_repo = position_repo
        self._risk_state_repo = risk_state_repo
        self._rate_limit_repo = rate_limit_repo
        self._circuit_breaker_repo = circuit_breaker_repo
        self._app_config = app_config
        self._market_data_adapter = market_data_adapter
        self._max_attempts = (config.max_attempts if config else _DEFAULT_MAX_ATTEMPTS)
        self._backoff_seconds = (config.backoff_seconds if config else _DEFAULT_BACKOFF_SECONDS)
        # PR13：断路器状态（进程内，当未注入 repo 时使用）；PR14a 外置时由 repo 管理
        self._circuit_failures: int = 0
        self._circuit_opened_at: Optional[datetime] = None

    async def _maybe_audit(
        self,
        event_type: str,
        message: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        component: str = "execution_engine",
    ) -> None:
        """C3 必写路径：有 log_repo 时写 AUDIT。"""
        if self._log_repo is None:
            return
        await self._log_repo.write("AUDIT", component, message, event_type=event_type, payload=payload)

    async def _maybe_audit_failed(
        self,
        decision_id: str,
        strategy_id: str,
        reason_code: str,
        message: Optional[str] = None,
    ) -> None:
        """C3 必写路径：execution_failed 时写 AUDIT。"""
        if self._log_repo is None:
            return
        msg = message or f"execution_failed decision_id={decision_id} reason_code={reason_code}"
        await self._log_repo.write(
            "AUDIT",
            "execution_engine",
            msg,
            event_type="execution_failed",
            payload={"decision_id": decision_id, "strategy_id": strategy_id, "reason_code": reason_code},
        )

    async def _maybe_error(
        self,
        message: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        component: str = "execution_engine",
    ) -> None:
        """C3 必写路径：写 ERROR（如决策快照写入失败）。"""
        if self._log_repo is None:
            return
        await self._log_repo.write("ERROR", component, message, event_type="decision_snapshot_save_failed", payload=payload)

    async def _check_live_risk_limits(
        self,
        event_repo: ExecutionEventRepository,
        exec_cfg: Any,
        decision_id: str,
        symbol: str,
        qty_decimal: Decimal,
        attempt_before: int,
        dry_run: bool,
        live_enabled: bool,
        account_id: Optional[str],
        exchange_profile: Optional[str],
        rehearsal: bool,
        now: datetime,
    ) -> Optional[Dict[str, str]]:
        """
        PR17b：live 风险限制校验。返回 None 表示通过；否则返回 {reason_code, message} 并已写 ORDER_REJECTED 事件。
        """
        from src.common.reason_codes import (
            LIVE_RISK_NOTIONAL_EXCEEDED,
            LIVE_RISK_QTY_EXCEEDED,
            LIVE_RISK_HOURLY_LIMIT,
            LIVE_RISK_DAILY_LIMIT,
            LIVE_RISK_PRICE_UNAVAILABLE,
        )

        max_notional = getattr(exec_cfg, "live_max_order_notional", None)
        max_qty = getattr(exec_cfg, "live_max_order_qty", None)
        max_per_day = getattr(exec_cfg, "live_max_orders_per_day", 0)
        max_per_hour = getattr(exec_cfg, "live_max_orders_per_hour", 0)
        price_override = getattr(exec_cfg, "live_last_price_override", None)

        if max_qty is not None and max_qty > 0 and float(qty_decimal) > max_qty:
            await event_repo.append_event(
                decision_id,
                EV_ORDER_REJECTED,
                status=FAILED,
                reason_code=LIVE_RISK_QTY_EXCEEDED,
                message=f"live qty {qty_decimal} > live_max_order_qty {max_qty}",
                attempt_count=attempt_before,
                dry_run=dry_run,
                live_enabled=live_enabled,
                account_id=account_id,
                exchange_profile=exchange_profile,
                rehearsal=rehearsal,
            )
            return {"reason_code": LIVE_RISK_QTY_EXCEEDED, "message": f"qty {qty_decimal} > {max_qty}"}

        if max_per_hour > 0:
            since_h = now - timedelta(hours=1)
            count_h = await event_repo.count_order_submissions_since(since_h, account_id=account_id)
            if count_h >= max_per_hour:
                await event_repo.append_event(
                    decision_id,
                    EV_ORDER_REJECTED,
                    status=FAILED,
                    reason_code=LIVE_RISK_HOURLY_LIMIT,
                    message=f"live orders in last 1h {count_h} >= {max_per_hour}",
                    attempt_count=attempt_before,
                    dry_run=dry_run,
                    live_enabled=live_enabled,
                    account_id=account_id,
                    exchange_profile=exchange_profile,
                    rehearsal=rehearsal,
                )
                return {"reason_code": LIVE_RISK_HOURLY_LIMIT, "message": f"hourly limit {max_per_hour}"}

        if max_per_day > 0:
            since_d = now - timedelta(days=1)
            count_d = await event_repo.count_order_submissions_since(since_d, account_id=account_id)
            if count_d >= max_per_day:
                await event_repo.append_event(
                    decision_id,
                    EV_ORDER_REJECTED,
                    status=FAILED,
                    reason_code=LIVE_RISK_DAILY_LIMIT,
                    message=f"live orders in last 24h {count_d} >= {max_per_day}",
                    attempt_count=attempt_before,
                    dry_run=dry_run,
                    live_enabled=live_enabled,
                    account_id=account_id,
                    exchange_profile=exchange_profile,
                    rehearsal=rehearsal,
                )
                return {"reason_code": LIVE_RISK_DAILY_LIMIT, "message": f"daily limit {max_per_day}"}

        if max_notional is not None and max_notional > 0:
            last_price: Optional[float] = None
            if price_override is not None and price_override > 0:
                last_price = float(price_override)
            elif self._market_data_adapter is not None and symbol:
                try:
                    md = await self._market_data_adapter.get_market_data(symbol)
                    last_price = float(getattr(md, "last_price", 0) or 0)
                except Exception:
                    last_price = None
            if last_price is None or last_price <= 0:
                await event_repo.append_event(
                    decision_id,
                    EV_ORDER_REJECTED,
                    status=FAILED,
                    reason_code=LIVE_RISK_PRICE_UNAVAILABLE,
                    message="live notional check requires last_price (live_last_price_override or market_data)",
                    attempt_count=attempt_before,
                    dry_run=dry_run,
                    live_enabled=live_enabled,
                    account_id=account_id,
                    exchange_profile=exchange_profile,
                    rehearsal=rehearsal,
                )
                return {"reason_code": LIVE_RISK_PRICE_UNAVAILABLE, "message": "price unavailable"}
            notional = float(qty_decimal) * last_price
            if notional > max_notional:
                await event_repo.append_event(
                    decision_id,
                    EV_ORDER_REJECTED,
                    status=FAILED,
                    reason_code=LIVE_RISK_NOTIONAL_EXCEEDED,
                    message=f"live notional {notional} > {max_notional}",
                    attempt_count=attempt_before,
                    dry_run=dry_run,
                    live_enabled=live_enabled,
                    account_id=account_id,
                    exchange_profile=exchange_profile,
                    rehearsal=rehearsal,
                )
                return {"reason_code": LIVE_RISK_NOTIONAL_EXCEEDED, "message": f"notional {notional} > {max_notional}"}

        return None

    async def execute_one(self, decision_id: str) -> Dict[str, Any]:
        """
        执行单条决策：抢占 → 风控 → 下单 → 落库。
        C7：打点 latency_ms（有 _perf_writer 时，独立事务 commit）。
        Returns:
            dict 必含 decision_id, status；可选 reason_code, exchange_order_id, attempt_count。
        """
        t0 = time.perf_counter()
        perf_tags: Dict[str, str] = {"decision_id": decision_id}
        try:
            return await self._execute_one_impl(decision_id, perf_tags)
        finally:
            if getattr(self, "_perf_writer", None):
                await self._dom_repo.session.commit()
                await self._perf_writer.write_once(
                    "execution_engine",
                    "latency_ms",
                    (time.perf_counter() - t0) * 1000,
                    tags=perf_tags,
                )

    async def _execute_one_impl(self, decision_id: str, perf_tags: Dict[str, str]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        event_repo = ExecutionEventRepository(self._dom_repo.session)
        _dry_run = self._app_config.execution.dry_run if self._app_config else False
        _live_enabled = getattr(self._app_config.execution, "live_enabled", False) if self._app_config else False
        _rehearsal = (
            getattr(self._app_config.execution, "mode", None) == "DEMO_LIVE_REHEARSAL"
        ) if self._app_config else False
        _account_id = None
        _exchange_profile = None

        # 事务A：原子抢占 RESERVED → SUBMITTING
        decision = await self._dom_repo.try_claim_reserved(decision_id, now=now)
        if decision is None:
            logger.info(
                "claim_failed decision_id=%s reason_code=%s",
                decision_id,
                SKIPPED_ALREADY_CLAIMED,
            )
            return {
                "decision_id": decision_id,
                "status": "skipped",
                "reason_code": SKIPPED_ALREADY_CLAIMED,
            }

        strategy_id = decision.strategy_id or ""
        perf_tags["strategy_id"] = strategy_id
        symbol = decision.symbol or ""
        side = decision.side or ""

        await event_repo.append_event(
            decision_id,
            CLAIMED,
            status=SUBMITTING,
            attempt_count=decision.attempt_count or 0,
            dry_run=_dry_run,
            live_enabled=_live_enabled,
            account_id=_account_id,
            exchange_profile=_exchange_profile,
            rehearsal=_rehearsal,
        )

        # PR11 封版：按 strategy_id 解析策略配置；PR14a：先 resolve 以便按 account_id 做熔断/限频
        resolved = None
        if self._app_config is not None and strategy_id:
            from src.config.strategy_resolver import resolve as resolve_strategy_config
            from src.config.strategy_resolver import StrategyConfigResolverError
            try:
                resolved = resolve_strategy_config(self._app_config, strategy_id)
            except StrategyConfigResolverError as e:
                reason_code = getattr(e, "reason_code", CONFIG_UNAVAILABLE)
                msg = getattr(e, "message", str(e))
                await event_repo.append_event(
                    decision_id,
                    FINAL_FAILED,
                    status=FAILED,
                    reason_code=reason_code,
                    message=msg,
                    attempt_count=decision.attempt_count or 0,
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                )
                await _persist_exception_status(
                    decision_id,
                    FAILED,
                    last_error=reason_code,
                    updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                logger.warning(
                    "strategy_resolve_failed decision_id=%s strategy_id=%s reason_code=%s",
                    decision_id,
                    strategy_id,
                    reason_code,
                )
                return {
                    "decision_id": decision_id,
                    "status": "failed",
                    "reason_code": reason_code,
                }
            except Exception as e:
                reason_code = CONFIG_UNAVAILABLE
                msg = str(e)
                await event_repo.append_event(
                    decision_id,
                    FINAL_FAILED,
                    status=FAILED,
                    reason_code=reason_code,
                    message=msg,
                    attempt_count=decision.attempt_count or 0,
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                )
                await _persist_exception_status(
                    decision_id,
                    FAILED,
                    last_error=reason_code,
                    updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                logger.warning(
                    "strategy_resolve_failed decision_id=%s strategy_id=%s reason_code=%s",
                    decision_id,
                    strategy_id,
                    reason_code,
                    exc_info=True,
                )
                return {
                    "decision_id": decision_id,
                    "status": "failed",
                    "reason_code": reason_code,
                }

        if resolved is not None:
            _account_id = resolved.account_id
            _exchange_profile = resolved.exchange_profile_id
            from src.config.snapshot import make_config_snapshot_message_for_strategy
            await event_repo.append_event(
                decision_id,
                CONFIG_SNAPSHOT,
                message=make_config_snapshot_message_for_strategy(resolved),
                dry_run=_dry_run,
                live_enabled=_live_enabled,
                account_id=_account_id,
                exchange_profile=_exchange_profile,
            )

        # PR13/PR14a：断路器检查（熔断期间拒绝并审计）；PR16：DEMO_LIVE_REHEARSAL 时用更严阈值
        _account_key = _account_id if _account_id else "default"
        _exec = self._app_config.execution if self._app_config else None
        _cb_threshold = (
            _exec.rehearsal_circuit_breaker_threshold if _rehearsal and _exec else (_exec.circuit_breaker_threshold if _exec else 0)
        )
        _cb_open_sec = (
            _exec.rehearsal_circuit_breaker_open_seconds if _rehearsal and _exec else (_exec.circuit_breaker_open_seconds if _exec else 60)
        )
        if self._app_config and _cb_threshold > 0:
            open_sec = _cb_open_sec
            if self._circuit_breaker_repo is not None:
                is_open, opened_at, just_closed = await self._circuit_breaker_repo.is_open(
                    _account_key, open_sec
                )
                if just_closed:
                    await event_repo.append_event(
                        decision_id,
                        CIRCUIT_CLOSED,
                        dry_run=_dry_run,
                        live_enabled=_live_enabled,
                        account_id=_account_id,
                        exchange_profile=_exchange_profile,
                    )
                if is_open:
                    await event_repo.append_event(
                        decision_id,
                        FINAL_FAILED,
                        status=FAILED,
                        reason_code=CIRCUIT_OPEN,
                        message="circuit open",
                        dry_run=_dry_run,
                        live_enabled=_live_enabled,
                        account_id=_account_id,
                        exchange_profile=_exchange_profile,
                    )
                    await _persist_exception_status(
                        decision_id, FAILED, last_error=CIRCUIT_OPEN, updated_at=now,
                        _caller_session=self._dom_repo.session,
                    )
                    return {"decision_id": decision_id, "status": "failed", "reason_code": CIRCUIT_OPEN}
            else:
                if self._circuit_opened_at is not None:
                    if (now - self._circuit_opened_at).total_seconds() < open_sec:
                        await event_repo.append_event(
                            decision_id,
                            FINAL_FAILED,
                            status=FAILED,
                            reason_code=CIRCUIT_OPEN,
                            message="circuit open",
                            dry_run=_dry_run,
                            live_enabled=_live_enabled,
                            account_id=_account_id,
                            exchange_profile=_exchange_profile,
                        )
                        await _persist_exception_status(
                            decision_id, FAILED, last_error=CIRCUIT_OPEN, updated_at=now,
                            _caller_session=self._dom_repo.session,
                        )
                        return {"decision_id": decision_id, "status": "failed", "reason_code": CIRCUIT_OPEN}
                    self._circuit_opened_at = None
                    await event_repo.append_event(
                        decision_id,
                        CIRCUIT_CLOSED,
                        dry_run=_dry_run,
                        live_enabled=_live_enabled,
                        account_id=_account_id,
                        exchange_profile=_exchange_profile,
                    )

        logger.info(
            "processing decision_id=%s strategy_id=%s symbol=%s side=%s status_from=RESERVED",
            decision_id,
            strategy_id,
            symbol,
            side,
        )

        qty_decimal = decision.quantity if decision.quantity is not None else Decimal("1")
        client_order_id = decision_id
        attempt_before = decision.attempt_count or 0

        # 风控（PR9：RISK_CHECK_STARTED → check → RISK_PASSED / RISK_REJECTED；PR11：策略级 risk_config，使用已解析的 resolved）
        await event_repo.append_event(
            decision_id,
            RISK_CHECK_STARTED,
            status=SUBMITTING,
            attempt_count=attempt_before,
            dry_run=_dry_run,
            live_enabled=_live_enabled,
            account_id=_account_id,
            exchange_profile=_exchange_profile,
        )
        risk_config_override = None
        if resolved is not None:
            from src.execution.risk_config import RiskConfig
            risk_config_override = RiskConfig.from_risk_section(resolved.risk)
        risk_result = await self._risk.check(decision, risk_config_override=risk_config_override)
        if not risk_result.get("allowed", True):
            reason = risk_result.get("reason_code") or RISK_REJECTED
            msg = risk_result.get("message")
            await event_repo.append_event(
                decision_id,
                EV_RISK_REJECTED,
                status=FAILED,
                reason_code=reason,
                message=msg,
                attempt_count=attempt_before,
                dry_run=_dry_run,
                live_enabled=_live_enabled,
                account_id=_account_id,
                exchange_profile=_exchange_profile,
            )
            await _persist_exception_status(
                decision_id,
                FAILED,
                last_error=reason,
                updated_at=now,
                _caller_session=self._dom_repo.session,
            )
            logger.info(
                "risk_rejected decision_id=%s strategy_id=%s symbol=%s side=%s reason_code=%s",
                decision_id,
                strategy_id,
                symbol,
                side,
                reason,
            )
            await self._maybe_audit(
                "risk_check_reject",
                f"risk_check_reject decision_id={decision_id} reason_code={reason}",
                payload={"decision_id": decision_id, "strategy_id": strategy_id, "reason_code": reason},
            )
            return {
                "decision_id": decision_id,
                "status": "failed",
                "reason_code": reason,
            }
        await self._maybe_audit(
            "risk_check_pass",
            f"risk_check_pass decision_id={decision_id} strategy_id={strategy_id}",
            payload={"decision_id": decision_id, "strategy_id": strategy_id},
        )
        await event_repo.append_event(
            decision_id,
            RISK_PASSED,
            status=SUBMITTING,
            attempt_count=attempt_before,
            dry_run=_dry_run,
            live_enabled=_live_enabled,
            account_id=_account_id,
            exchange_profile=_exchange_profile,
            rehearsal=_rehearsal,
        )

        # Phase1.2 C1：同事务写入决策输入快照；写入失败则拒绝本次决策、告警、写日志，不向下游传递
        if self._snapshot_repo is not None:
            signal_state = {
                "signal_id": decision.signal_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "quantity": str(decision.quantity) if decision.quantity is not None else "1",
                "created_at": decision.created_at.isoformat() if getattr(decision.created_at, "isoformat", None) else str(decision.created_at) if decision.created_at else None,
            }
            position_state = {}
            risk_check_result = {
                "allowed": risk_result.get("allowed", True),
                "reason_code": risk_result.get("reason_code"),
                "message": risk_result.get("message"),
            }
            decision_result = {
                "decision_id": decision_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "quantity": str(decision.quantity) if decision.quantity is not None else "1",
                "reason": "risk_passed",
            }
            snapshot = DecisionSnapshot(
                decision_id=decision_id,
                strategy_id=strategy_id,
                signal_state=signal_state,
                position_state=position_state,
                risk_check_result=risk_check_result,
                decision_result=decision_result,
            )
            try:
                await self._snapshot_repo.save(snapshot)
            except Exception as e:
                err_msg = str(e)
                if self._alert_callback is not None:
                    self._alert_callback(decision_id, strategy_id, err_msg)
                await self._maybe_error(
                    f"decision_snapshot_save_failed decision_id={decision_id} strategy_id={strategy_id} reason={err_msg}",
                    payload={"decision_id": decision_id, "strategy_id": strategy_id, "reason": err_msg},
                )
                logger.error(
                    "decision_snapshot_save_failed decision_id=%s strategy_id=%s reason=%s",
                    decision_id,
                    strategy_id,
                    err_msg,
                    exc_info=True,
                )
                await event_repo.append_event(
                    decision_id,
                    FINAL_FAILED,
                    status=FAILED,
                    reason_code="DECISION_SNAPSHOT_SAVE_FAILED",
                    message=err_msg[:500] if err_msg else "snapshot save failed",
                    attempt_count=attempt_before,
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                    rehearsal=_rehearsal,
                )
                await _persist_exception_status(
                    decision_id,
                    FAILED,
                    last_error="DECISION_SNAPSHOT_SAVE_FAILED",
                    updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                await self._maybe_audit_failed(decision_id, strategy_id, "DECISION_SNAPSHOT_SAVE_FAILED", err_msg)
                return {
                    "decision_id": decision_id,
                    "status": "failed",
                    "reason_code": "DECISION_SNAPSHOT_SAVE_FAILED",
                }

        # PR16：参数精度与数量校验（本地拒绝，不触发 HTTP）；PR16c：精度优先取 qty_precision_by_symbol[symbol]，否则 order_qty_precision
        _exec_for_val = resolved.execution if resolved else (self._app_config.execution if self._app_config else None)
        if _exec_for_val is not None:
            from src.execution.order_param_validator import validate_order_params
            _qty_by_sym = getattr(_exec_for_val, "qty_precision_by_symbol", None) or {}
            _qty_precision = (
                _qty_by_sym.get(symbol.strip(), getattr(_exec_for_val, "order_qty_precision", 8))
                if symbol and isinstance(_qty_by_sym, dict)
                else getattr(_exec_for_val, "order_qty_precision", 8)
            )
            allowed_param, param_reason, param_msg = validate_order_params(
                qty_decimal,
                qty_precision=_qty_precision,
                market_max_notional=getattr(_exec_for_val, "order_market_max_notional", None),
                last_price_for_notional=None,
                ord_type="market",
            )
            if not allowed_param:
                await event_repo.append_event(
                    decision_id,
                    EV_ORDER_REJECTED,
                    status=FAILED,
                    reason_code=param_reason or ORDER_PARAM_INVALID,
                    message=param_msg,
                    attempt_count=attempt_before,
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                    rehearsal=_rehearsal,
                )
                await _persist_exception_status(
                    decision_id, FAILED, last_error=param_reason or ORDER_PARAM_INVALID, updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                return {
                    "decision_id": decision_id,
                    "status": "failed",
                    "reason_code": param_reason or ORDER_PARAM_INVALID,
                }
        # PR16/PR17a：多重 Live 门禁仅针对 live 实盘 endpoint；Demo rehearsal（OKX Demo HTTP）不校验 allow_real_trading/allowlist/token，可正常下单
        # PR16c/PR17a：is_live_endpoint 时 live_allowlist_symbols 必须非空，且 symbol 须在列表中
        if _exec_for_val is not None and getattr(self._exchange, "is_live_endpoint", lambda: False)():
            _allowlist_syms = getattr(_exec_for_val, "live_allowlist_symbols", None) or []
            if not _allowlist_syms:
                from src.common.reason_codes import LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED
                await event_repo.append_event(
                    decision_id,
                    EV_ORDER_REJECTED,
                    status=FAILED,
                    reason_code=LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED,
                    message="live_allowlist_symbols must be non-empty when live path is enabled",
                    attempt_count=attempt_before,
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                    rehearsal=_rehearsal,
                )
                await _persist_exception_status(
                    decision_id, FAILED, last_error=LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED, updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                return {
                    "decision_id": decision_id,
                    "status": "failed",
                    "reason_code": LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED,
                }
            if symbol and (symbol.strip() not in [s.strip() for s in _allowlist_syms if s]):
                from src.common.reason_codes import LIVE_GATE_SYMBOL_NOT_ALLOWED
                await event_repo.append_event(
                    decision_id,
                    EV_ORDER_REJECTED,
                    status=FAILED,
                    reason_code=LIVE_GATE_SYMBOL_NOT_ALLOWED,
                    message=f"symbol {symbol!r} not in live_allowlist_symbols",
                    attempt_count=attempt_before,
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                    rehearsal=_rehearsal,
                )
                await _persist_exception_status(
                    decision_id, FAILED, last_error=LIVE_GATE_SYMBOL_NOT_ALLOWED, updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                return {
                    "decision_id": decision_id,
                    "status": "failed",
                    "reason_code": LIVE_GATE_SYMBOL_NOT_ALLOWED,
                }
            from src.execution.live_gate import check_live_gates
            gate_result = check_live_gates(
                dry_run=_dry_run,
                live_enabled=_live_enabled,
                allow_real_trading=getattr(_exec_for_val, "allow_real_trading", False),
                live_allowlist_accounts=getattr(_exec_for_val, "live_allowlist_accounts", []) or [],
                live_confirm_token_configured=getattr(_exec_for_val, "live_confirm_token", "") or "",
                account_id=_account_id,
                exchange_profile=_exchange_profile,
                is_live_endpoint=True,
            )
            if not gate_result.allowed:
                await event_repo.append_event(
                    decision_id,
                    EV_ORDER_REJECTED,
                    status=FAILED,
                    reason_code=gate_result.reason_code,
                    message=gate_result.message,
                    attempt_count=attempt_before,
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                    rehearsal=_rehearsal,
                )
                await _persist_exception_status(
                    decision_id, FAILED, last_error=gate_result.reason_code, updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                return {
                    "decision_id": decision_id,
                    "status": "failed",
                    "reason_code": gate_result.reason_code,
                }
            # PR17b：门禁全过时，校验 live 风险限制（极小额）
            if gate_result.allowed:
                live_risk_err = await self._check_live_risk_limits(
                    event_repo,
                    _exec_for_val,
                    decision_id,
                    symbol,
                    qty_decimal,
                    attempt_before,
                    _dry_run,
                    _live_enabled,
                    _account_id,
                    _exchange_profile,
                    _rehearsal,
                    now,
                )
                if live_risk_err:
                    await _persist_exception_status(
                        decision_id, FAILED, last_error=live_risk_err["reason_code"], updated_at=now,
                        _caller_session=self._dom_repo.session,
                    )
                    return {
                        "decision_id": decision_id,
                        "status": "failed",
                        "reason_code": live_risk_err["reason_code"],
                    }
        # PR13/PR14a：全局限频（超限 → FAILED + 审计）；PR16：DEMO_LIVE_REHEARSAL 时用更严限频
        _effective_max_orders = (
            _exec.rehearsal_max_orders_per_minute if _rehearsal and _exec
            else (resolved.execution.max_orders_per_minute if resolved else (_exec.max_orders_per_minute if _exec else 0))
        )
        if resolved is not None and _effective_max_orders > 0:
            allowed = True
            if self._rate_limit_repo is not None:
                allowed = await self._rate_limit_repo.allow_and_increment(
                    _account_key,
                    _effective_max_orders,
                    window_seconds=60,
                )
            else:
                since = now - timedelta(seconds=60)
                count = await event_repo.count_order_submissions_since(
                    since, account_id=_account_id if _account_id else None
                )
                if count >= _effective_max_orders:
                    allowed = False
            if not allowed:
                await event_repo.append_event(
                    decision_id,
                    EV_RATE_LIMIT_EXCEEDED,
                    status=FAILED,
                    reason_code=RATE_LIMIT_EXCEEDED,
                    message=f"max_orders_per_minute={_effective_max_orders}",
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                    rehearsal=_rehearsal,
                )
                await _persist_exception_status(
                    decision_id, FAILED, last_error=RATE_LIMIT_EXCEEDED, updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                return {"decision_id": decision_id, "status": "failed", "reason_code": RATE_LIMIT_EXCEEDED}

        # ---------- Phase1.1 C2 阶段1（短锁、纯 DB）：下单意图 PENDING_EXCHANGE，create_order 仍在锁外 ----------
        await self._dom_repo.session.execute(
            text("INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, lock_ttl_seconds) VALUES (:sid, 30)"),
            {"sid": strategy_id},
        )
        await self._dom_repo.session.flush()
        holder_id = os.environ.get("RECONCILE_LOCK_HOLDER_ID", "").strip() or f"exec-{os.getpid()}"
        lock = ReconcileLock(self._dom_repo.session, holder_id=holder_id, max_acquire_retries=0)
        async with lock.use_lock(strategy_id) as phase1_ok:
            if not phase1_ok:
                logger.warning(
                    "c2_phase1_lock_not_acquired decision_id=%s strategy_id=%s holder=%s",
                    decision_id, strategy_id, holder_id,
                )
                await event_repo.append_event(
                    decision_id, FINAL_FAILED, status=FAILED, reason_code=RECONCILE_LOCK_NOT_ACQUIRED,
                    attempt_count=attempt_before, dry_run=_dry_run, live_enabled=_live_enabled,
                    account_id=_account_id, exchange_profile=_exchange_profile,
                )
                return {"decision_id": decision_id, "status": "failed", "reason_code": RECONCILE_LOCK_NOT_ACQUIRED}
            n = await self._dom_repo.update_submitting_to_pending_exchange(decision_id, now)
            if n != 1:
                await event_repo.append_event(
                    decision_id, FINAL_FAILED, status=FAILED, reason_code=RECONCILE_LOCK_NOT_ACQUIRED,
                    attempt_count=attempt_before, dry_run=_dry_run, live_enabled=_live_enabled,
                    account_id=_account_id, exchange_profile=_exchange_profile,
                )
                return {"decision_id": decision_id, "status": "failed", "reason_code": RECONCILE_LOCK_NOT_ACQUIRED}
        await self._dom_repo.session.commit()
        # 阶段1 已提交，PENDING_EXCHANGE 持久化；create_order 在锁外执行

        await event_repo.append_event(
            decision_id,
            ORDER_SUBMIT_STARTED,
            status=SUBMITTING,
            attempt_count=attempt_before,
            dry_run=_dry_run,
            live_enabled=_live_enabled,
            account_id=_account_id,
            exchange_profile=_exchange_profile,
            rehearsal=_rehearsal,
        )
        await self._maybe_audit(
            "execution_submit",
            f"execution_submit decision_id={decision_id} strategy_id={strategy_id} symbol={symbol} side={side}",
            payload={"decision_id": decision_id, "strategy_id": strategy_id, "symbol": symbol, "side": side},
        )

        try:
            logger.info(
                "order_start decision_id=%s strategy_id=%s symbol=%s side=%s",
                decision_id,
                strategy_id,
                symbol,
                side,
            )
            result = await self._exchange.create_order(
                symbol=symbol,
                side=side,
                qty=qty_decimal,
                client_order_id=client_order_id,
            )
            exchange_order_id = result.exchange_order_id or ""
            # PR15b：通信审计 OKX_HTTP_CREATE_ORDER（仅 action/http_status/okx_code/request_id/attempt）
            if getattr(result, "http_status", None) is not None:
                await event_repo.append_event(
                    decision_id,
                    EV_OKX_HTTP_CREATE_ORDER,
                    reason_code="create_order",
                    message=_okx_http_create_order_message(
                        getattr(result, "http_status", None),
                        getattr(result, "okx_code", None),
                        getattr(result, "request_id", None),
                        attempt=attempt_before,
                    ),
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                )
            await event_repo.append_event(
                decision_id,
                ORDER_SUBMIT_OK,
                status=result.status,
                exchange_order_id=exchange_order_id,
                attempt_count=attempt_before,
                dry_run=_dry_run,
                live_enabled=_live_enabled,
                account_id=_account_id,
                exchange_profile=_exchange_profile,
            )
            logger.info(
                "order_end decision_id=%s strategy_id=%s symbol=%s side=%s status=filled exchange_order_id=%s reason_code=%s",
                decision_id,
                strategy_id,
                symbol,
                side,
                exchange_order_id,
                SUCCESS_FILLED,
            )
        except TransientOrderError as e:
            attempt = attempt_before + 1
            # PR15b：通信审计 OKX_HTTP_CREATE_ORDER（本次尝试失败，含 attempt）
            if getattr(e, "http_status", None) is not None:
                await event_repo.append_event(
                    decision_id,
                    EV_OKX_HTTP_CREATE_ORDER,
                    reason_code="create_order",
                    message=_okx_http_create_order_message(
                        getattr(e, "http_status", None),
                        getattr(e, "okx_code", None),
                        getattr(e, "request_id", None),
                        attempt=attempt,
                    ),
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                )
            await event_repo.append_event(
                decision_id,
                ORDER_SUBMIT_FAILED,
                status=RESERVED,
                reason_code=EXCHANGE_TRANSIENT_ERROR,
                attempt_count=attempt,
                dry_run=_dry_run,
                live_enabled=_live_enabled,
                account_id=_account_id,
                exchange_profile=_exchange_profile,
            )
            if attempt < self._max_attempts:
                idx = min(attempt - 1, len(self._backoff_seconds) - 1)
                backoff = self._backoff_seconds[idx]
                next_run = now + timedelta(seconds=backoff)
                async with lock.use_lock(strategy_id) as phase3_fail_ok:
                    if phase3_fail_ok:
                        await self._dom_repo.update_after_exchange(
                            decision_id,
                            RESERVED,
                            attempt_count=attempt,
                            last_error=RETRY_SCHEDULED,
                            next_run_at=next_run,
                            updated_at=now,
                        )
                await self._dom_repo.session.commit()
                await event_repo.append_event(
                    decision_id,
                    EV_RETRY_SCHEDULED,
                    status=RESERVED,
                    reason_code=RETRY_SCHEDULED,
                    attempt_count=attempt,
                    message=f"next_run_at={next_run.isoformat()}",
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                )
                logger.info(
                    "transient_retry decision_id=%s strategy_id=%s symbol=%s side=%s attempt_count=%s next_run_at=%s reason_code=%s",
                    decision_id,
                    strategy_id,
                    symbol,
                    side,
                    attempt,
                    next_run.isoformat(),
                    RETRY_SCHEDULED,
                )
                return {
                    "decision_id": decision_id,
                    "status": "retry_scheduled",
                    "reason_code": RETRY_SCHEDULED,
                    "attempt_count": attempt,
                }
            else:
                async with lock.use_lock(strategy_id) as phase3_fail_ok:
                    if phase3_fail_ok:
                        await self._dom_repo.update_after_exchange(
                            decision_id,
                            FAILED,
                            attempt_count=attempt,
                            last_error=RETRY_EXHAUSTED,
                            next_run_at=None,
                            updated_at=now,
                        )
                await self._dom_repo.session.commit()
                await _persist_exception_status(
                    decision_id,
                    FAILED,
                    attempt_count=attempt,
                    last_error=RETRY_EXHAUSTED,
                    next_run_at=None,
                    updated_at=now,
                    _caller_session=self._dom_repo.session,
                )
                await event_repo.append_event(
                    decision_id,
                    FINAL_FAILED,
                    status=FAILED,
                    reason_code=RETRY_EXHAUSTED,
                    attempt_count=attempt,
                    dry_run=_dry_run,
                    live_enabled=_live_enabled,
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                )
                logger.info(
                    "final_failure decision_id=%s strategy_id=%s symbol=%s side=%s reason_code=%s attempt_count=%s",
                    decision_id,
                    strategy_id,
                    symbol,
                    side,
                    RETRY_EXHAUSTED,
                    attempt,
                )
                # PR13/PR14a：断路器：连续失败则熔断（外置时写 repo）
                if self._circuit_breaker_repo is not None and self._app_config and _cb_threshold > 0:
                    failures, triggered = await self._circuit_breaker_repo.record_failure(
                        _account_key,
                        _cb_threshold,
                        _cb_open_sec,
                    )
                    if triggered:
                        await event_repo.append_event(
                            decision_id,
                            CIRCUIT_OPENED,
                            status=FAILED,
                            reason_code=RETRY_EXHAUSTED,
                            message=f"circuit opened after {failures} failures",
                            dry_run=_dry_run,
                            live_enabled=_live_enabled,
                            account_id=_account_id,
                            exchange_profile=_exchange_profile,
                        )
                else:
                    self._circuit_failures += 1
                    if self._app_config and _cb_threshold > 0:
                        if self._circuit_failures >= _cb_threshold:
                            self._circuit_opened_at = now
                            await event_repo.append_event(
                                decision_id,
                                CIRCUIT_OPENED,
                                status=FAILED,
                                reason_code=RETRY_EXHAUSTED,
                                message=f"circuit opened after {self._circuit_failures} failures",
                                dry_run=_dry_run,
                                live_enabled=_live_enabled,
                                account_id=_account_id,
                                exchange_profile=_exchange_profile,
                            )
                await self._maybe_audit_failed(decision_id, strategy_id, RETRY_EXHAUSTED)
                return {
                    "decision_id": decision_id,
                    "status": "failed",
                    "reason_code": RETRY_EXHAUSTED,
                    "attempt_count": attempt,
                }
        except PermanentOrderError as e:
            # PR15b：Permanent 不重试；先写通信审计，再写业务失败
            attempt = attempt_before + 1
            if getattr(e, "http_status", None) is not None:
                await event_repo.append_event(
                    decision_id,
                    EV_OKX_HTTP_CREATE_ORDER,
                    reason_code="create_order",
                    message=_okx_http_create_order_message(
                        getattr(e, "http_status", None),
                        getattr(e, "okx_code", None),
                        getattr(e, "request_id", None),
                        attempt=attempt,
                    ),
                    account_id=_account_id,
                    exchange_profile=_exchange_profile,
                )
            err_code = ORDER_REJECTED
            await event_repo.append_event(
                decision_id,
                FINAL_FAILED,
                status=FAILED,
                reason_code=err_code,
                attempt_count=attempt,
                dry_run=_dry_run,
                live_enabled=_live_enabled,
                account_id=_account_id,
                exchange_profile=_exchange_profile,
            )
            async with lock.use_lock(strategy_id) as phase3_fail_ok:
                if phase3_fail_ok:
                    await self._dom_repo.update_after_exchange(
                        decision_id, FAILED, last_error=err_code, updated_at=now,
                    )
            await self._dom_repo.session.commit()
            await _persist_exception_status(
                decision_id,
                FAILED,
                last_error=err_code,
                updated_at=now,
                _caller_session=self._dom_repo.session,
            )
            if self._circuit_breaker_repo is not None and self._app_config and _cb_threshold > 0:
                failures, triggered = await self._circuit_breaker_repo.record_failure(
                    _account_key,
                    _cb_threshold,
                    _cb_open_sec,
                )
                if triggered:
                    await event_repo.append_event(
                        decision_id,
                        CIRCUIT_OPENED,
                        status=FAILED,
                        reason_code=err_code,
                        message=f"circuit opened after {failures} failures",
                        dry_run=_dry_run,
                        live_enabled=_live_enabled,
                        account_id=_account_id,
                        exchange_profile=_exchange_profile,
                    )
            else:
                self._circuit_failures += 1
                if self._app_config and _cb_threshold > 0:
                    if self._circuit_failures >= _cb_threshold:
                        self._circuit_opened_at = now
                        await event_repo.append_event(
                            decision_id,
                            CIRCUIT_OPENED,
                            status=FAILED,
                            reason_code=err_code,
                            message=f"circuit opened after {self._circuit_failures} failures",
                            dry_run=_dry_run,
                            live_enabled=_live_enabled,
                            account_id=_account_id,
                            exchange_profile=_exchange_profile,
                            rehearsal=_rehearsal,
                        )
            logger.warning(
                "order_rejected decision_id=%s strategy_id=%s symbol=%s side=%s reason_code=%s",
                decision_id,
                strategy_id,
                symbol,
                side,
                err_code,
            )
            await self._maybe_audit_failed(decision_id, strategy_id, err_code)
            return {
                "decision_id": decision_id,
                "status": "failed",
                "reason_code": err_code,
                "attempt_count": attempt,
            }
        except Exception:
            err_code = ORDER_REJECTED
            attempt = attempt_before + 1
            await event_repo.append_event(
                decision_id,
                FINAL_FAILED,
                status=FAILED,
                reason_code=err_code,
                attempt_count=attempt,
                dry_run=_dry_run,
                live_enabled=_live_enabled,
                account_id=_account_id,
                exchange_profile=_exchange_profile,
            )
            async with lock.use_lock(strategy_id) as phase3_fail_ok:
                if phase3_fail_ok:
                    await self._dom_repo.update_after_exchange(
                        decision_id, FAILED, last_error=err_code, updated_at=now,
                    )
            await self._dom_repo.session.commit()
            # PR13/PR14a：断路器（外置时写 repo）
            if self._circuit_breaker_repo is not None and self._app_config and _cb_threshold > 0:
                failures, triggered = await self._circuit_breaker_repo.record_failure(
                    _account_key,
                    _cb_threshold,
                    _cb_open_sec,
                )
                if triggered:
                    await event_repo.append_event(
                        decision_id,
                        CIRCUIT_OPENED,
                        status=FAILED,
                        reason_code=err_code,
                        message=f"circuit opened after {failures} failures",
                        dry_run=_dry_run,
                        live_enabled=_live_enabled,
                        account_id=_account_id,
                        exchange_profile=_exchange_profile,
                    )
            else:
                self._circuit_failures += 1
                if self._app_config and _cb_threshold > 0:
                    if self._circuit_failures >= _cb_threshold:
                        self._circuit_opened_at = now
                        await event_repo.append_event(
                            decision_id,
                            CIRCUIT_OPENED,
                            status=FAILED,
                            reason_code=err_code,
                            message=f"circuit opened after {self._circuit_failures} failures",
                            dry_run=_dry_run,
                            live_enabled=_live_enabled,
                            account_id=_account_id,
                            exchange_profile=_exchange_profile,
                            rehearsal=_rehearsal,
                        )
            await _persist_exception_status(
                decision_id,
                FAILED,
                last_error=err_code,
                updated_at=now,
                _caller_session=self._dom_repo.session,
            )
            logger.exception(
                "order_failed decision_id=%s strategy_id=%s symbol=%s side=%s reason_code=%s",
                decision_id,
                strategy_id,
                symbol,
                side,
                err_code,
            )
            await self._maybe_audit_failed(decision_id, strategy_id, err_code)
            return {
                "decision_id": decision_id,
                "status": "failed",
                "reason_code": err_code,
            }

        # ---------- Phase1.1 C2 阶段3（短锁、纯 DB）：PENDING_EXCHANGE -> FILLED，绝不丢单 ----------
        exchange_order_id = result.exchange_order_id or ""
        phase3_max_retries = 3
        phase3_interval_sec = 0.1
        for phase3_attempt in range(phase3_max_retries):
            async with lock.use_lock(strategy_id) as phase3_ok:
                if phase3_ok:
                    local_order_id = getattr(result, "order_id", None) or decision_id
                    await self._dom_repo.update_after_exchange(
                        decision_id,
                        FILLED,
                        local_order_id=local_order_id,
                        exchange_order_id=exchange_order_id,
                        last_error=None,
                        next_run_at=None,
                        updated_at=now,
                    )
                    if self._position_repo:
                        await self._position_repo.increase(
                            strategy_id, symbol, qty_decimal, avg_price=None, side=side or "LONG",
                        )
                    if self._risk_state_repo:
                        await self._risk_state_repo.set_last_allowed_at(
                            strategy_id, symbol, side, datetime.now(timezone.utc)
                        )
                    if self._circuit_breaker_repo is not None:
                        await self._circuit_breaker_repo.record_success(_account_key)
                    else:
                        self._circuit_failures = 0
                    # D1：信号驱动成交时写入 trade 表，使 trace 可达 COMPLETE
                    if self._trade_repo is not None:
                        avg_price = getattr(result, "avg_price", None)
                        price = avg_price if avg_price is not None else Decimal("0")
                        filled_qty = getattr(result, "filled_qty", None) or qty_decimal
                        trade_id = f"{decision_id}-fill"
                        trade = Trade(
                            trade_id=trade_id,
                            strategy_id=strategy_id,
                            source_type=SOURCE_TYPE_SIGNAL,
                            external_trade_id=None,
                            signal_id=decision.signal_id,
                            decision_id=decision_id,
                            execution_id=decision_id,
                            symbol=symbol,
                            side=side or "BUY",
                            quantity=filled_qty,
                            price=price,
                            slippage=Decimal("0"),
                            realized_pnl=Decimal("0"),
                            executed_at=now,
                            is_simulated=False,
                        )
                        await self._trade_repo.create(trade)
                    await event_repo.append_event(
                        decision_id, EV_FILLED, status=FILLED, exchange_order_id=exchange_order_id,
                        attempt_count=attempt_before, dry_run=_dry_run, live_enabled=_live_enabled,
                        account_id=_account_id, exchange_profile=_exchange_profile,
                    )
                    await self._maybe_audit(
                        "trade_filled",
                        f"trade_filled decision_id={decision_id} strategy_id={strategy_id} exchange_order_id={exchange_order_id}",
                        payload={"decision_id": decision_id, "strategy_id": strategy_id, "exchange_order_id": exchange_order_id},
                    )
                    return {
                        "decision_id": decision_id,
                        "status": "filled",
                        "exchange_order_id": exchange_order_id,
                    }
            if phase3_attempt < phase3_max_retries - 1:
                await asyncio.sleep(phase3_interval_sec)
        # 阶段3 拿不到锁：已有阶段1 PENDING_EXCHANGE，写入可观测状态，不丢单
        logger.warning(
            "c2_phase3_lock_not_acquired decision_id=%s strategy_id=%s exchange_order_id=%s",
            decision_id, strategy_id, exchange_order_id,
        )
        await event_repo.append_event(
            decision_id,
            EV_PENDING_EXCHANGE_ACK_NOT_COMMITTED,
            status=PENDING_EXCHANGE,
            reason_code=PENDING_EXCHANGE_ACK_NOT_COMMITTED,
            message=f"exchange_order_id={exchange_order_id}",
            exchange_order_id=exchange_order_id,
            attempt_count=attempt_before,
            dry_run=_dry_run,
            live_enabled=_live_enabled,
            account_id=_account_id,
            exchange_profile=_exchange_profile,
        )
        return {
            "decision_id": decision_id,
            "status": "filled_pending_commit",
            "exchange_order_id": exchange_order_id,
            "reason_code": PENDING_EXCHANGE_ACK_NOT_COMMITTED,
        }
