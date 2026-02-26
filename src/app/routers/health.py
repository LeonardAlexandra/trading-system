"""
Phase2.0 D8：健康检查可观测性升级

提供结构化健康状态判定与 Prometheus 兼容指标：
- GET /api/health/summary
- GET /metrics
"""
from time import perf_counter
from typing import Any, Dict, List

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db_session
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.models.log_entry import LogEntry
from src.monitoring.health_checker import HealthChecker
from src.repositories.log_repository import LogRepository

DEFAULT_ERROR_RATE_THRESHOLD = 0.1
DEFAULT_RECENT_ERRORS_THRESHOLD = 20
DEFAULT_RECENT_ALERTS_LIMIT = 20
DEFAULT_RECENT_ERRORS_LIMIT = 20

HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_UNHEALTHY = "unhealthy"

router = APIRouter(prefix="/api/health", tags=["health"])
metrics_router = APIRouter(tags=["health"])


def _status_from_signals(
    *,
    db_ok: bool,
    exchange_ok: bool,
    queue_ok: bool,
    execution_worker_ok: bool,
    error_rate: float,
    recent_errors: int,
    max_error_rate: float,
    max_recent_errors: int,
) -> str:
    """
    D8 判定规则：
    - DB 失败 => unhealthy
    - 指标超过阈值 => degraded / unhealthy
    - 非核心组件失败（exchange/queue/worker）=> degraded
    """
    if not db_ok:
        return HEALTH_UNHEALTHY

    if (error_rate > (max_error_rate * 2.0)) or (recent_errors > (max_recent_errors * 2)):
        return HEALTH_UNHEALTHY

    if (
        error_rate > max_error_rate
        or recent_errors > max_recent_errors
        or (not exchange_ok)
        or (not queue_ok)
        or (not execution_worker_ok)
    ):
        return HEALTH_DEGRADED

    return HEALTH_HEALTHY


def _build_prometheus_metrics(summary: Dict[str, Any]) -> str:
    metrics = summary.get("metrics", {})
    components = summary.get("components", {})
    status = str(summary.get("status", HEALTH_UNHEALTHY))

    lines = [
        "# HELP error_rate Health error rate in the configured observation window.",
        "# TYPE error_rate gauge",
        f'error_rate{{source="health"}} {float(metrics.get("error_rate", 0.0))}',
        "# HELP recent_errors Number of recent error events observed by health check.",
        "# TYPE recent_errors gauge",
        f'recent_errors{{source="health"}} {int(metrics.get("recent_errors", 0))}',
        "# HELP component_status Component health status (1=ok, 0=not ok).",
        "# TYPE component_status gauge",
    ]

    for component_name, component_data in components.items():
        ok = bool((component_data or {}).get("ok", False))
        lines.append(f'component_status{{component="{component_name}"}} {1 if ok else 0}')

    lines.extend(
        [
            "# HELP health_status Overall health status as one-hot labels.",
            "# TYPE health_status gauge",
            f'health_status{{status="{HEALTH_HEALTHY}"}} {1 if status == HEALTH_HEALTHY else 0}',
            f'health_status{{status="{HEALTH_DEGRADED}"}} {1 if status == HEALTH_DEGRADED else 0}',
            f'health_status{{status="{HEALTH_UNHEALTHY}"}} {1 if status == HEALTH_UNHEALTHY else 0}',
        ]
    )
    return "\n".join(lines) + "\n"


async def _fetch_recent_alerts(session: AsyncSession, limit: int) -> List[Dict[str, Any]]:
    stmt = (
        select(LogEntry)
        .where(LogEntry.event_type == "alert_triggered")
        .order_by(LogEntry.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "level": r.level or "WARNING",
                "component": r.component or "",
                "title": r.message[:200] if r.message else "",
                "message": r.message or "",
                "timestamp": r.created_at.isoformat() if r.created_at else "",
            }
        )
    return out


async def _probe_database_latency_ms(session: AsyncSession) -> tuple[bool, float]:
    started = perf_counter()
    try:
        await session.execute(text("SELECT 1"))
        latency_ms = (perf_counter() - started) * 1000.0
        return True, round(latency_ms, 3)
    except Exception:
        latency_ms = (perf_counter() - started) * 1000.0
        return False, round(latency_ms, 3)


def _worker_ok_from_strategy_status(strategy_status: Dict[str, Any]) -> bool:
    summary = str((strategy_status or {}).get("summary", ""))
    return summary in {"ok", "no_strategies"}


async def _build_summary(
    session: AsyncSession,
    error_rate_threshold: float = DEFAULT_ERROR_RATE_THRESHOLD,
    recent_errors_threshold: int = DEFAULT_RECENT_ERRORS_THRESHOLD,
    recent_alerts_limit: int = DEFAULT_RECENT_ALERTS_LIMIT,
    recent_errors_limit: int = DEFAULT_RECENT_ERRORS_LIMIT,
) -> Dict[str, Any]:
    started = perf_counter()
    exchange_adapter = PaperExchangeAdapter(filled=True)
    checker = HealthChecker()
    health = await checker.check_all(session, exchange_adapter)
    db_ping_ok, db_latency_ms = await _probe_database_latency_ms(session)

    status_probe_limit = max(recent_errors_limit, (recent_errors_threshold * 2) + 1)
    log_repo = LogRepository(session)
    error_entries = await log_repo.query(level="ERROR", limit=status_probe_limit, offset=0)

    recent_errors_count = len(error_entries)
    recent_errors_items = [
        {
            "created_at": e.created_at.isoformat() if e.created_at else "",
            "component": e.component or "",
            "message": (e.message or "")[:500],
            "event_type": e.event_type or "",
        }
        for e in error_entries[:recent_errors_limit]
    ]
    recent_alerts = await _fetch_recent_alerts(session, recent_alerts_limit)

    db_ok = bool(health.db_ok and db_ping_ok)
    exchange_ok = bool(health.exchange_ok)
    execution_worker_ok = _worker_ok_from_strategy_status(health.strategy_status)
    queue_ok = bool(db_ok and execution_worker_ok)
    # 轻量可判定口径：基于 recent error 样本计算窗口内 error_rate（避免重型 COUNT 查询）。
    error_rate = round(recent_errors_count / 3600.0, 6)

    status = _status_from_signals(
        db_ok=db_ok,
        exchange_ok=exchange_ok,
        queue_ok=queue_ok,
        execution_worker_ok=execution_worker_ok,
        error_rate=error_rate,
        recent_errors=recent_errors_count,
        max_error_rate=error_rate_threshold,
        max_recent_errors=recent_errors_threshold,
    )

    duration_ms = round((perf_counter() - started) * 1000.0, 3)

    payload = {
        "status": status,
        "components": {
            "database": {"ok": db_ok, "latency_ms": db_latency_ms},
            "queue": {"ok": queue_ok},
            "execution_worker": {"ok": execution_worker_ok},
            "exchange": {"ok": exchange_ok},
        },
        "metrics": {
            "error_rate": error_rate,
            "recent_errors": recent_errors_count,
            "thresholds": {
                "max_error_rate": float(error_rate_threshold),
                "max_recent_errors": int(recent_errors_threshold),
            },
            "duration_ms": duration_ms,
            "window_seconds": 3600,
            "since": None,
            "until": None,
        },
        "recent_errors": recent_errors_items,
        "recent_alerts": recent_alerts,
        # 兼容旧消费方字段（双栈）
        "overall_ok": status == HEALTH_HEALTHY,
    }
    return payload


@router.get("/summary")
async def get_health_summary(request: Request):
    app_config = getattr(request.app.state, "app_config", None)
    error_rate_threshold = DEFAULT_ERROR_RATE_THRESHOLD
    recent_errors_threshold = DEFAULT_RECENT_ERRORS_THRESHOLD
    recent_alerts_limit = DEFAULT_RECENT_ALERTS_LIMIT
    recent_errors_limit = DEFAULT_RECENT_ERRORS_LIMIT
    if app_config and hasattr(app_config, "health_summary"):
        hs = getattr(app_config, "health_summary", None)
        if hs:
            error_rate_threshold = getattr(hs, "error_rate_threshold", error_rate_threshold)
            recent_errors_threshold = getattr(hs, "recent_errors_threshold", recent_errors_threshold)
            recent_alerts_limit = getattr(hs, "recent_alerts_limit", recent_alerts_limit)
            recent_errors_limit = getattr(hs, "recent_errors_limit", recent_errors_limit)

    async with get_db_session() as session:
        summary = await _build_summary(
            session,
            error_rate_threshold=error_rate_threshold,
            recent_errors_threshold=recent_errors_threshold,
            recent_alerts_limit=recent_alerts_limit,
            recent_errors_limit=recent_errors_limit,
        )
    return summary


@metrics_router.get("/metrics")
async def get_prometheus_metrics(request: Request):
    app_config = getattr(request.app.state, "app_config", None)
    error_rate_threshold = DEFAULT_ERROR_RATE_THRESHOLD
    recent_errors_threshold = DEFAULT_RECENT_ERRORS_THRESHOLD
    recent_errors_limit = DEFAULT_RECENT_ERRORS_LIMIT
    if app_config and hasattr(app_config, "health_summary"):
        hs = getattr(app_config, "health_summary", None)
        if hs:
            error_rate_threshold = getattr(hs, "error_rate_threshold", error_rate_threshold)
            recent_errors_threshold = getattr(hs, "recent_errors_threshold", recent_errors_threshold)
            recent_errors_limit = getattr(hs, "recent_errors_limit", recent_errors_limit)

    async with get_db_session() as session:
        summary = await _build_summary(
            session,
            error_rate_threshold=error_rate_threshold,
            recent_errors_threshold=recent_errors_threshold,
            recent_errors_limit=recent_errors_limit,
            recent_alerts_limit=DEFAULT_RECENT_ALERTS_LIMIT,
        )
    body = _build_prometheus_metrics(summary)
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
