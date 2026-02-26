"""
Phase1.2 C2：全链路追溯 HTTP 路由（蓝本 D.2 写死）
C7：Trace 查询打点 latency_ms。
"""
import time

from fastapi import APIRouter, Response

from src.app.dependencies import get_db_session
from src.repositories.perf_log_repository import PerfLogWriter
from src.schemas.trace import TRACE_STATUS_NOT_FOUND, TRACE_STATUS_FAILED
from src.services.trace_query_service import TraceQueryService

router = APIRouter(prefix="/api/trace", tags=["trace"])


@router.get("/signal/{signal_id}")
async def get_trace_by_signal(signal_id: str):
    """
    按 signal_id 查询全链路追溯结果。
    查不到任何节点返回 404；查到部分或全部返回 200，body 为 TraceResult。
    """
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_signal_id(signal_id)
    
    if result.trace_status == TRACE_STATUS_NOT_FOUND:
        return Response(content="", status_code=404)
    # AC-D2-TRACE-404-01: FAILED decision 必须返回 200 而非 404
    return result.to_dict()


@router.get("/decision/{decision_id}")
async def get_trace_by_decision(decision_id: str):
    """
    按 decision_id 查询全链路追溯结果。
    查不到任何节点返回 404；查到部分或全部返回 200，body 为 TraceResult。
    """
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_decision_id(decision_id)
    
    if result.trace_status == TRACE_STATUS_NOT_FOUND:
        return Response(content="", status_code=404)
    # AC-D2-TRACE-404-01: FAILED decision 必须返回 200 而非 404
    return result.to_dict()
