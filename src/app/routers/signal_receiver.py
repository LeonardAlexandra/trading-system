"""
SignalReceiver：FastAPI Webhook 接口（PR4 验签 + PR5 去重与决策占位）
C7：信号接收/解析入口打点 latency_ms。
"""
import logging
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from src.adapters.tradingview_adapter import (
    TradingViewAdapter,
    SIGNATURE_HEADER_NAME,
)
from src.app.dependencies import get_db_session
from src.common.reason_codes import (
    INVALID_SIGNATURE,
    MALFORMED_PAYLOAD,
    MISSING_STRATEGY_ID,
    INVALID_WEBHOOK_CONFIGURATION,
    INTERNAL_ERROR,
    STRATEGY_NOT_FOUND,
    STRATEGY_DISABLED,
)
from src.config.strategy_resolver import resolve as resolve_strategy_config
from src.config.strategy_resolver import StrategyConfigResolverError
from src.common.config_errors import ConfigValidationError
from src.config.app_config import app_config_to_legacy_dict
from src.repositories.dedup_signal_repo import DedupSignalRepository
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository
from src.repositories.signal_rejection_repo import SignalRejectionRepository
from src.repositories.log_repository import LogRepository
from src.repositories.perf_log_repository import PerfLogWriter
from src.models.strategy_runtime_state import STATUS_PAUSED
from src.models.signal_rejection import REASON_STRATEGY_PAUSED
from src.application.signal_service import SignalApplicationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["webhook"])


def _request_id(request: Request) -> str:
    """优先使用 header X-Request-ID，否则生成 uuid4"""
    rid = (request.headers.get("X-Request-ID") or "").strip()
    return rid or str(uuid.uuid4())


def _error_content(
    request_id: str,
    detail: str,
    reason_code: str,
    signal_id: str | None = None,
) -> dict:
    """4xx/5xx 统一监控字段：request_id、detail、reason_code，可选 signal_id"""
    content = {"request_id": request_id, "detail": detail, "reason_code": reason_code}
    if signal_id is not None:
        content["signal_id"] = signal_id
    return content


async def _write_signal_receiver_perf(t0: float, writer: PerfLogWriter) -> None:
    """C7：独立事务写入 signal_receiver 处理耗时到 perf_log（writer.write_once 内 commit）。"""
    await writer.write_once("signal_receiver", "latency_ms", (time.perf_counter() - t0) * 1000)


@router.post("/webhook/tradingview")
async def receive_tradingview_webhook(request: Request):
    """
    TradingView Webhook：配置校验 -> 验签 -> 解析 -> 去重 -> 决策占位(RESERVED) -> 返回确定性响应。
    PR10 P2-1：仅从 AppConfig 读取 webhook secret，缺失 -> 422 + reason_code=INVALID_WEBHOOK_CONFIGURATION。
    C7：打点 latency_ms（信号接收/解析入口）。
    """
    raw_body = await request.body()
    signature_header = request.headers.get(SIGNATURE_HEADER_NAME) or ""
    request_id = _request_id(request)
    t0 = time.perf_counter()
    writer = PerfLogWriter(get_db_session)
    try:
        # Fail-fast：按设计 lifespan 已注入 app_config，缺失属于启动流程错误
        app_config = getattr(request.app.state, "app_config", None)
        if not app_config:
            raise RuntimeError(
                "app_config missing: startup did not inject config; "
                "this should never happen if lifespan runs correctly."
            )
        try:
            if not (app_config.webhook.tradingview_secret or "").strip():
                raise ConfigValidationError(
                    INVALID_WEBHOOK_CONFIGURATION,
                    "Webhook secret not configured",
                )
        except ConfigValidationError as e:
            logger.warning("Webhook config validation failed: %s", e.message)
            return JSONResponse(
                status_code=422,
                content={
                    "request_id": request_id,
                    "detail": e.message,
                    "reason_code": e.reason_code,
                },
            )
        secret = app_config.webhook.tradingview_secret
        config = app_config_to_legacy_dict(app_config)

        try:
            TradingViewAdapter.validate_signature(raw_body, signature_header, secret)
        except ValueError:
            return JSONResponse(
                status_code=401,
                content=_error_content(
                    request_id,
                    "Invalid or missing signature",
                    INVALID_SIGNATURE,
                ),
            )

        try:
            signal = TradingViewAdapter.parse_signal(raw_body)
        except ValueError as e:
            logger.warning("Parse signal failed: %s", str(e))
            return JSONResponse(
                status_code=400,
                content=_error_content(
                    request_id,
                    "invalid_payload",
                    MALFORMED_PAYLOAD,
                ),
            )

        # PR11：未提供 strategy_id → 422
        if not (signal.strategy_id or "").strip():
            return JSONResponse(
                status_code=422,
                content={
                    "request_id": request_id,
                    "detail": "strategy_id is required",
                    "reason_code": MISSING_STRATEGY_ID,
                },
            )

        # PR11：校验 strategy_id 存在且启用
        try:
            resolve_strategy_config(app_config, signal.strategy_id)
        except StrategyConfigResolverError as e:
            logger.warning("Strategy validation failed: %s", e.message)
            return JSONResponse(
                status_code=422,
                content={
                    "request_id": request_id,
                    "detail": e.message,
                    "reason_code": e.reason_code,
                    "strategy_id": signal.strategy_id,
                },
            )

        try:
            async with get_db_session() as session:
                # C5：策略 PAUSED 时拒绝新信号，返回 HTTP 200 + 业务字段拒绝原因，并写入可审计记录
                state_repo = StrategyRuntimeStateRepository(session)
                state = await state_repo.get_by_strategy_id(signal.strategy_id)
                if state and getattr(state, "status", None) == STATUS_PAUSED:
                    rej_repo = SignalRejectionRepository(session)
                    await rej_repo.create_rejection(
                        signal.strategy_id,
                        REASON_STRATEGY_PAUSED,
                        signal_id=signal.signal_id,
                    )
                    return JSONResponse(
                        status_code=200,
                        content={"status": "rejected", "reason": "STRATEGY_PAUSED"},
                    )
                dedup_repo = DedupSignalRepository(session)
                dom_repo = DecisionOrderMapRepository(session)
                service = SignalApplicationService(dedup_repo, dom_repo, perf_writer=writer)
                result = await service.handle_tradingview_signal(signal, config)
                log_repo = LogRepository(session)
                try:
                    await log_repo.write(
                        "AUDIT",
                        "signal_receiver",
                        f"signal_received signal_id={signal.signal_id} strategy_id={signal.strategy_id}",
                        event_type="signal_received",
                        payload={"signal_id": signal.signal_id, "strategy_id": signal.strategy_id},
                    )
                    if result.get("status") == "accepted":
                        await log_repo.write(
                            "AUDIT",
                            "signal_receiver",
                            f"decision_created decision_id={result.get('decision_id')} signal_id={signal.signal_id}",
                            event_type="decision_created",
                            payload={"decision_id": result.get("decision_id"), "signal_id": signal.signal_id, "strategy_id": signal.strategy_id},
                        )
                except SQLAlchemyError:
                    await session.rollback()
                    logger.warning("Skip audit log write due to transient DB issue", exc_info=True)
            return JSONResponse(status_code=200, content=result)
        except ConfigValidationError as e:
            logger.warning("Webhook config validation failed: %s", e.message)
            return JSONResponse(
                status_code=422,
                content={
                    "request_id": request_id,
                    "detail": e.message,
                    "reason_code": e.reason_code,
                },
            )
        except ValueError as e:
            logger.warning("Service validation failed: %s", str(e))
            return JSONResponse(
                status_code=422,
                content=_error_content(
                    request_id,
                    "invalid_configuration",
                    MISSING_STRATEGY_ID,
                    signal_id=signal.signal_id,
                ),
            )
        except Exception:
            logger.exception("Unhandled exception in TradingView webhook")
            return JSONResponse(
                status_code=500,
                content=_error_content(
                    request_id,
                    "Internal server error",
                    INTERNAL_ERROR,
                    signal_id=signal.signal_id,
                ),
            )
    finally:
        await _write_signal_receiver_perf(t0, writer)
