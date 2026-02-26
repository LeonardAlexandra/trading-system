"""
Phase1.2 C7：性能日志 Repository（仅写入与分页查询）+ 独立事务写入器

- PerfLogRepository：write/query，依赖调用方 session（query 仍用外部 session）。
- PerfLogWriter：write_once 使用 session_factory 自建 session 并显式 commit，强落库，不依赖调用方事务。
- 仅使用 A3 既有 perf_log 表；与 log 表语义分离。
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from src.models.perf_log_entry import PerfLogEntry

# 单次查询上限（写死）
QUERY_MAX_LIMIT = 1000
DEFAULT_QUERY_LIMIT = 1000


@dataclass
class PerfLogRecord:
    """单条性能日志查询结果（与 perf_log 表字段对应）。"""
    id: int
    created_at: datetime
    component: str
    metric: str
    value: float
    tags: Optional[Dict[str, Any]]


class PerfLogRepository:
    """性能日志：仅写入与分页查询，使用 A3 perf_log 表。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(
        self,
        component: str,
        metric: str,
        value: float,
        *,
        tags: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
    ) -> None:
        """写入一条性能记录。不写 log 表。"""
        entry = PerfLogEntry(
            component=component[:64],
            metric=metric[:64],
            value=Decimal(str(value)),
            tags=tags,
        )
        if created_at is not None:
            entry.created_at = created_at
        self.session.add(entry)

    async def query(
        self,
        *,
        created_at_from: Optional[datetime] = None,
        created_at_to: Optional[datetime] = None,
        component: Optional[str] = None,
        metric: Optional[str] = None,
        limit: int = DEFAULT_QUERY_LIMIT,
        offset: int = 0,
    ) -> List[PerfLogRecord]:
        """分页查询；limit 不得超过 QUERY_MAX_LIMIT。"""
        limit = min(max(1, limit), QUERY_MAX_LIMIT)
        stmt = (
            select(PerfLogEntry)
            .order_by(PerfLogEntry.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if created_at_from is not None:
            stmt = stmt.where(PerfLogEntry.created_at >= created_at_from)
        if created_at_to is not None:
            stmt = stmt.where(PerfLogEntry.created_at <= created_at_to)
        if component is not None:
            stmt = stmt.where(PerfLogEntry.component == component)
        if metric is not None:
            stmt = stmt.where(PerfLogEntry.metric == metric)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            PerfLogRecord(
                id=r.id,
                created_at=r.created_at,
                component=r.component or "",
                metric=r.metric or "",
                value=float(r.value) if r.value is not None else 0.0,
                tags=r.tags,
            )
            for r in rows
        ]


class PerfLogWriter:
    """
    性能日志独立事务写入器：每次 write_once 自建 session 并显式 commit，不依赖调用方事务。
    session_factory: 可调用且返回 async context manager  yielding AsyncSession，例如 get_db_session。
    """

    def __init__(
        self,
        session_factory: Callable[..., Any],
    ) -> None:
        self._session_factory = session_factory

    async def write_once(
        self,
        component: str,
        metric: str,
        value: float,
        *,
        tags: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
    ) -> bool:
        """独立事务写入一条性能记录并 commit，不写 log 表。"""
        async with self._session_factory() as session:
            try:
                entry = PerfLogEntry(
                    component=component[:64],
                    metric=metric[:64],
                    value=Decimal(str(value)),
                    tags=tags,
                )
                if created_at is not None:
                    entry.created_at = created_at
                session.add(entry)
                await session.commit()
                return True
            except SQLAlchemyError:
                # Perf log is non-critical observability. Do not break main business flow.
                await session.rollback()
                return False
