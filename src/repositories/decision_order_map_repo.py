"""
DecisionOrderMap Repository（决策订单映射表，PR5 占位 + PR6 执行）
"""
from decimal import Decimal
from typing import Optional, List, Union
from datetime import datetime, timezone
from sqlalchemy import select, update, or_

from src.models.decision_order_map import DecisionOrderMap
from src.models.decision_order_map_status import RESERVED, SUBMITTING, PENDING_EXCHANGE, FILLED
from src.repositories.base import BaseRepository


class DecisionOrderMapRepository(BaseRepository[DecisionOrderMap]):
    """决策订单映射表 Repository"""
    
    async def create_reserved(
        self,
        decision_id: str,
        signal_id: str,
        strategy_id: str,
        symbol: str,
        side: str,
        created_at: datetime,
        quantity: Union[str, Decimal, int, None] = None,
    ) -> DecisionOrderMap:
        """
        创建 RESERVED 占位记录（PR5 写入 symbol/side/strategy_id/signal_id/quantity 供 PR6 执行读取）。
        quantity 统一以 Decimal 落库。
        """
        qty = Decimal(str(quantity)) if quantity is not None else Decimal("1")
        decision_order_map = DecisionOrderMap(
            decision_id=decision_id,
            status=RESERVED,
            signal_id=signal_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            quantity=qty,
        )
        self.session.add(decision_order_map)
        await self.session.flush()
        return decision_order_map
    
    async def get_by_decision_id(self, decision_id: str) -> Optional[DecisionOrderMap]:
        """
        根据 decision_id 查询决策订单映射记录
        
        Args:
            decision_id: 决策 ID
        
        Returns:
            DecisionOrderMap 对象，如果不存在则返回 None
        """
        stmt = select(DecisionOrderMap).where(DecisionOrderMap.decision_id == decision_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def update_status(
        self,
        decision_id: str,
        status: str,
        *,
        local_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None
    ) -> None:
        """
        更新状态（不做状态机校验；只负责落库）
        
        Args:
            decision_id: 决策 ID
            status: 新状态
            local_order_id: 本地订单号（可选）
            exchange_order_id: 交易所订单号（可选）
        
        Note:
            - 不做状态机校验，只负责数据库更新
            - 不在这里 commit，由上层 session 生命周期管理
        """
        stmt = select(DecisionOrderMap).where(DecisionOrderMap.decision_id == decision_id)
        result = await self.session.execute(stmt)
        decision_order_map = result.scalar_one_or_none()
        
        if decision_order_map is None:
            raise ValueError(f"DecisionOrderMap with decision_id={decision_id} not found")
        
        # 更新字段
        decision_order_map.status = status
        if local_order_id is not None:
            decision_order_map.local_order_id = local_order_id
        if exchange_order_id is not None:
            decision_order_map.exchange_order_id = exchange_order_id
        
        # 注意：不在这里 commit，由上层 session 生命周期管理

    async def try_claim_reserved(self, decision_id: str, now: Optional[datetime] = None) -> Optional[DecisionOrderMap]:
        """
        原子抢占：将 status=RESERVED 且 (next_run_at IS NULL OR next_run_at<=now) 的记录更新为 SUBMITTING。
        并发安全，仅当条件满足时更新一行。
        Returns:
            抢占成功返回该行（已刷新），否则 None。
        """
        now = now or datetime.now(timezone.utc)
        stmt = (
            update(DecisionOrderMap)
            .where(
                DecisionOrderMap.decision_id == decision_id,
                DecisionOrderMap.status == RESERVED,
                or_(
                    DecisionOrderMap.next_run_at.is_(None),
                    DecisionOrderMap.next_run_at <= now,
                ),
            )
            .values(status=SUBMITTING, updated_at=now)
        )
        result = await self.session.execute(stmt)
        if result.rowcount != 1:
            return None
        await self.session.flush()
        return await self.get_by_decision_id(decision_id)

    async def list_reserved_ready(self, limit: int = 10, now: Optional[datetime] = None) -> List[DecisionOrderMap]:
        """
        查询可执行的 RESERVED 记录：status=RESERVED 且 (next_run_at IS NULL OR next_run_at<=now)，按 created_at 升序。
        """
        now = now or datetime.now(timezone.utc)
        stmt = (
            select(DecisionOrderMap)
            .where(
                DecisionOrderMap.status == RESERVED,
                or_(
                    DecisionOrderMap.next_run_at.is_(None),
                    DecisionOrderMap.next_run_at <= now,
                ),
            )
            .order_by(DecisionOrderMap.created_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def exists_recent_filled_or_submitting(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        since: datetime,
        *,
        exclude_decision_id: Optional[str] = None,
    ) -> bool:
        """同 (strategy_id, symbol, side) 在 since 之后是否存在 FILLED、SUBMITTING 或 PENDING_EXCHANGE 记录（用于同向重复抑制）。exclude_decision_id 排除当前决策。"""
        conditions = [
            DecisionOrderMap.strategy_id == strategy_id,
            DecisionOrderMap.symbol == symbol,
            DecisionOrderMap.side == side,
            DecisionOrderMap.status.in_([FILLED, SUBMITTING, PENDING_EXCHANGE]),
            DecisionOrderMap.updated_at >= since,
        ]
        if exclude_decision_id is not None:
            conditions.append(DecisionOrderMap.decision_id != exclude_decision_id)
        stmt = (
            select(DecisionOrderMap.decision_id)
            .where(*conditions)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def update_submitting_to_pending_exchange(
        self, decision_id: str, updated_at: datetime
    ) -> int:
        """
        Phase1.1 C2 阶段1：仅当 status=SUBMITTING 时更新为 PENDING_EXCHANGE（持锁内调用）。
        返回受影响行数（1 表示成功）。
        """
        stmt = (
            update(DecisionOrderMap)
            .where(
                DecisionOrderMap.decision_id == decision_id,
                DecisionOrderMap.status == SUBMITTING,
            )
            .values(status=PENDING_EXCHANGE, updated_at=updated_at)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def update_after_exchange(
        self,
        decision_id: str,
        status: str,
        *,
        local_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        attempt_count: Optional[int] = None,
        last_error: Optional[str] = None,
        next_run_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        """
        交易所调用后更新：status、local_order_id、exchange_order_id、attempt_count、last_error、next_run_at、updated_at。
        """
        row = await self.get_by_decision_id(decision_id)
        if row is None:
            raise ValueError(f"DecisionOrderMap with decision_id={decision_id} not found")
        row.status = status
        if local_order_id is not None:
            row.local_order_id = local_order_id
        if exchange_order_id is not None:
            row.exchange_order_id = exchange_order_id
        if attempt_count is not None:
            row.attempt_count = attempt_count
        if last_error is not None:
            row.last_error = last_error
        if next_run_at is not None:
            row.next_run_at = next_run_at
        if updated_at is not None:
            row.updated_at = updated_at
