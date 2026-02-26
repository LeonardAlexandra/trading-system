"""
Phase1.2 C8：审计查询 API（list_traces + 日志）

- GET /api/audit/logs/recent：最近 N 条 ERROR/AUDIT
- GET /api/audit/logs：按时间/组件/level 分页
- GET /api/audit/traces：list_traces 分页（from/to, strategy_id, limit/offset）

错误码（C8-R1 蓝本）：400 参数错误、404 未找到、500 服务错误；body 含 error_code 与 message。
列表单次上限 100 条（traces 保持 le=100）。
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from src.app.dependencies import get_db_session
from src.repositories.log_repository import LogRepository
from src.services import audit_service

router = APIRouter(prefix="/api/audit", tags=["audit"])

# C8-R1 错误码与 body 约定
ERROR_CODE_INVALID_PARAMS = "INVALID_PARAMS"
ERROR_CODE_NOT_FOUND = "NOT_FOUND"
ERROR_CODE_INTERNAL_ERROR = "INTERNAL_ERROR"
AUDIT_API_COMPONENT = "audit_api"


def _parse_optional_datetime(s: Optional[str]) -> Optional[datetime]:
    if s is None or (isinstance(s, str) and s.strip() == ""):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_required_datetime(s: Optional[str]) -> Optional[datetime]:
    if s is None or (isinstance(s, str) and s.strip() == ""):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def _log_error_and_return_500(message: str, event_type: str = "internal_error") -> JSONResponse:
    """写入 ERROR 日志（不泄露敏感信息）并返回 500。"""
    try:
        async with get_db_session() as session:
            repo = LogRepository(session)
            await repo.write("ERROR", AUDIT_API_COMPONENT, message, event_type=event_type)
            await session.commit()
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={"error_code": ERROR_CODE_INTERNAL_ERROR, "message": "Internal server error"},
    )


@router.get("/logs/recent")
async def get_recent_logs(
    n: int = Query(20, ge=1, le=100),
    level: Optional[str] = Query(None, description="ERROR | AUDIT | ERROR,AUDIT"),
):
    """最近 N 条 ERROR/AUDIT 日志。level 不传则默认 ERROR+AUDIT。"""
    try:
        levels = None
        if level is not None:
            levels = [s.strip() for s in level.split(",") if s.strip()]
        if not levels:
            levels = ["ERROR", "AUDIT"]
        async with get_db_session() as session:
            items = await audit_service.recent_logs(session, n=n, levels=levels)
        return {"items": items, "count": len(items)}
    except Exception:
        return await _log_error_and_return_500("recent_logs failed", event_type="recent_logs_500")


@router.get("/logs")
async def get_logs(
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    component: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """按时间范围/组件/level 分页查询日志。参数错误返回 400（error_code=INVALID_PARAMS）。"""
    try:
        from_dt = _parse_optional_datetime(from_ts)
        to_dt = _parse_optional_datetime(to_ts)
        if from_ts is not None and from_dt is None:
            return JSONResponse(
                status_code=400,
                content={"error_code": ERROR_CODE_INVALID_PARAMS, "message": "Invalid parameter: from"},
            )
        if to_ts is not None and to_dt is None:
            return JSONResponse(
                status_code=400,
                content={"error_code": ERROR_CODE_INVALID_PARAMS, "message": "Invalid parameter: to"},
            )
        if from_dt is not None and to_dt is not None and from_dt > to_dt:
            return JSONResponse(
                status_code=400,
                content={"error_code": ERROR_CODE_INVALID_PARAMS, "message": "from must be <= to"},
            )
        async with get_db_session() as session:
            items = await audit_service.query_logs(
                session,
                created_at_from=from_dt,
                created_at_to=to_dt,
                component=component,
                level=level,
                limit=limit,
                offset=offset,
            )
        return {"items": items, "count": len(items)}
    except Exception:
        return await _log_error_and_return_500("query_logs failed", event_type="query_logs_500")


@router.get("/traces")
async def get_traces(
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    strategy_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """list_traces：按时间范围、可选 strategy_id、分页。参数错误 400；服务异常 500。列表上限 100。"""
    try:
        if from_ts is None or (isinstance(from_ts, str) and from_ts.strip() == ""):
            return JSONResponse(
                status_code=400,
                content={"error_code": ERROR_CODE_INVALID_PARAMS, "message": "Missing or invalid parameter: from"},
            )
        if to_ts is None or (isinstance(to_ts, str) and to_ts.strip() == ""):
            return JSONResponse(
                status_code=400,
                content={"error_code": ERROR_CODE_INVALID_PARAMS, "message": "Missing or invalid parameter: to"},
            )
        from_dt = _parse_required_datetime(from_ts)
        to_dt = _parse_required_datetime(to_ts)
        if from_dt is None:
            return JSONResponse(
                status_code=400,
                content={"error_code": ERROR_CODE_INVALID_PARAMS, "message": "Invalid parameter: from"},
            )
        if to_dt is None:
            return JSONResponse(
                status_code=400,
                content={"error_code": ERROR_CODE_INVALID_PARAMS, "message": "Invalid parameter: to"},
            )
        if from_dt > to_dt:
            return JSONResponse(
                status_code=400,
                content={"error_code": ERROR_CODE_INVALID_PARAMS, "message": "from must be <= to"},
            )
        async with get_db_session() as session:
            items = await audit_service.list_traces(
                session,
                from_ts=from_dt,
                to_ts=to_dt,
                strategy_id=strategy_id,
                limit=limit,
                offset=offset,
            )
        return {"items": [t.to_dict() for t in items], "count": len(items)}
    except Exception:
        return await _log_error_and_return_500("list_traces failed", event_type="list_traces_500")
