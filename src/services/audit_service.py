"""
Phase1.2 C8：审计查询共享后端（list_traces + 日志查询）

- list_traces：按时间范围/strategy_id 分页，调用 TraceQueryService 单笔回放聚合为 TraceSummary，不修改 C2 语义。
- 日志查询：仅使用 LogRepository.query，不修改 C3 语义。
CLI 与 Web 共用本服务。
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.log_repository import LogRepository, QUERY_MAX_LIMIT
from src.schemas.trace import TraceSummary
from src.services.trace_query_service import TraceQueryService

# list_traces 硬上限（写死，与 TraceQueryService.LIST_TRACES_MAX_LIMIT 一致）
LIST_TRACES_MAX_LIMIT = 100


async def list_traces(
    session: AsyncSession,
    from_ts: datetime,
    to_ts: datetime,
    strategy_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[TraceSummary]:
    """
    多笔回放：仅调用 TraceQueryService.list_traces，不修改 C2 语义。
    """
    limit = min(limit, LIST_TRACES_MAX_LIMIT)
    svc = TraceQueryService(session)
    return await svc.list_traces(from_ts, to_ts, strategy_id=strategy_id, limit=limit, offset=offset)


async def recent_logs(
    session: AsyncSession,
    n: int,
    levels: Optional[List[str]] = None,
) -> List[dict]:
    """
    最近 N 条 ERROR/AUDIT 日志（levels 默认 ["ERROR", "AUDIT"]）。
    仅使用 LogRepository.query，不修改 C3；多 level 时分别查询后按 created_at 合并取前 n 条。
    """
    if levels is None:
        levels = ["ERROR", "AUDIT"]
    n = min(n, QUERY_MAX_LIMIT)
    repo = LogRepository(session)
    merged: List[tuple] = []
    for level in levels:
        entries = await repo.query(level=level, limit=n, offset=0)
        for e in entries:
            merged.append((e.created_at, _log_entry_to_dict(e)))
    merged.sort(key=lambda x: x[0], reverse=True)
    return [row[1] for row in merged[:n]]


async def query_logs(
    session: AsyncSession,
    created_at_from: Optional[datetime] = None,
    created_at_to: Optional[datetime] = None,
    component: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[dict]:
    """按时间范围/组件/level 分页查询日志。仅使用 LogRepository.query。"""
    limit = min(limit, QUERY_MAX_LIMIT)
    repo = LogRepository(session)
    entries = await repo.query(
        created_at_from=created_at_from,
        created_at_to=created_at_to,
        component=component,
        level=level,
        limit=limit,
        offset=offset,
    )
    return [_log_entry_to_dict(e) for e in entries]


def _log_entry_to_dict(e) -> dict:
    return {
        "id": e.id,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "component": e.component,
        "level": e.level,
        "message": e.message,
        "event_type": e.event_type,
        "payload": e.payload,
    }
