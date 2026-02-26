"""
执行事件 Repository（PR8：audit/events 落库；PR13：count 限频）
P2-1：未传 created_at 时由本方法内部生成，保证同一次 execute_one 内事件 created_at 自然递增。
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, func

from src.models.execution_event import ExecutionEvent
from src.repositories.base import BaseRepository


class ExecutionEventRepository(BaseRepository[ExecutionEvent]):
    """执行事件表 Repository"""

    async def append_event(
        self,
        decision_id: str,
        event_type: str,
        *,
        status: Optional[str] = None,
        reason_code: Optional[str] = None,
        message: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        attempt_count: Optional[int] = None,
        created_at: Optional[datetime] = None,
        account_id: Optional[str] = None,
        exchange_profile: Optional[str] = None,
        dry_run: Optional[bool] = None,
        live_enabled: Optional[bool] = None,
        rehearsal: Optional[bool] = None,
    ) -> ExecutionEvent:
        """
        追加一条事件（轻量写入，允许在事务内调用）。
        PR13：支持 account_id、exchange_profile、dry_run 追溯与标记。
        PR14a：支持 live_enabled 追溯。PR16：支持 rehearsal 追溯。
        """
        event = ExecutionEvent(
            id=str(uuid.uuid4()),
            decision_id=decision_id,
            event_type=event_type,
            status=status,
            reason_code=reason_code,
            message=message,
            exchange_order_id=exchange_order_id,
            attempt_count=attempt_count,
            account_id=account_id,
            exchange_profile=exchange_profile,
            dry_run=dry_run if dry_run is not None else False,
            live_enabled=live_enabled if live_enabled is not None else False,
            rehearsal=rehearsal if rehearsal is not None else False,
        )
        # PR16c：rehearsal 唯一权威来源为 execution_events.rehearsal 列；message 不再包含 "rehearsal=" 字样
        if created_at is not None:
            event.created_at = created_at
        else:
            event.created_at = datetime.now(timezone.utc)
        self.session.add(event)
        return event

    async def list_by_decision_id(self, decision_id: str) -> List[ExecutionEvent]:
        """按 decision_id 查询事件，按 created_at 升序。"""
        stmt = (
            select(ExecutionEvent)
            .where(ExecutionEvent.decision_id == decision_id)
            .order_by(ExecutionEvent.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_order_submissions_since(
        self, since: datetime, account_id: Optional[str] = None
    ) -> int:
        """PR13：统计 since 以来 ORDER_SUBMIT_STARTED 事件数。PR14a：可选按 account_id 过滤。"""
        stmt = select(func.count(ExecutionEvent.id)).where(
            ExecutionEvent.event_type == "ORDER_SUBMIT_STARTED",
            ExecutionEvent.created_at >= since,
        )
        if account_id is not None:
            stmt = stmt.where(ExecutionEvent.account_id == account_id)
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)
