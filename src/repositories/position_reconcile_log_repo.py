"""
Phase1.1 A3：position_reconcile_log 表 Repository

写入 reconcile log 时填充 external_trade_id、event_type（仅允许 Phase1.1 封闭枚举）。
A3-05 硬契约：任何 position_reconcile_log 写入必须发生在事务内；否则拒绝并抛出 PositionReconcileLogNotInTransactionError。
推荐入口：log_event_in_txn(session 同事务内调用)。
"""
from typing import List, Optional

from sqlalchemy import select
from src.models.position_reconcile_log import PositionReconcileLog, validate_event_type
from src.repositories.base import BaseRepository


class PositionReconcileLogNotInTransactionError(RuntimeError):
    """A3-05：在未处于事务内的 session 上写入 position_reconcile_log 时抛出。要求写入必须与对账/挂起/恢复在同一事务内。"""

    def __init__(self, message: str = "position_reconcile_log write must run inside an active transaction (session.in_transaction())."):
        self.message = message
        super().__init__(self.message)


class PositionReconcileLogRepository(BaseRepository[PositionReconcileLog]):
    """position_reconcile_log 表访问；event_type 仅接受预定义枚举；写入前强制校验 session 处于事务内。"""

    def _require_transaction(self) -> None:
        """A3-05 防呆：当前 session 不在事务内则拒绝写入并抛出 PositionReconcileLogNotInTransactionError。"""
        if not self.session.in_transaction():
            raise PositionReconcileLogNotInTransactionError(
                "position_reconcile_log write must run inside an active transaction. "
                "Use 'async with session.begin():' (or session.begin() before write) and call create/log_event_in_txn within that block."
            )

    async def log_event_in_txn(
        self,
        strategy_id: str,
        event_type: str,
        external_trade_id: Optional[str] = None,
        price_tier: Optional[str] = None,
        diff_snapshot: Optional[str] = None,
    ) -> PositionReconcileLog:
        """
        A3-05 推荐主入口：在同一 session/transaction 内写一条日志，最省事即正确用法。
        C3 封版：SYNC_TRADE 时传入 price_tier 落盘可追溯。
        C5/C6：STRATEGY_PAUSED 时传入 diff_snapshot（差异快照 JSON 文本）。
        """
        self._require_transaction()
        if not validate_event_type(event_type):
            raise ValueError(f"event_type must be one of Phase1.1 closed enum, got: {event_type!r}")
        log = PositionReconcileLog(
            strategy_id=strategy_id,
            event_type=event_type,
            external_trade_id=external_trade_id,
            price_tier=price_tier,
            diff_snapshot=diff_snapshot,
        )
        self.session.add(log)
        return log

    async def create(self, log: PositionReconcileLog) -> PositionReconcileLog:
        """写入一条日志；调用方须保证 event_type 为 Phase1.1 封闭枚举值，且当前 session 已处于事务内。"""
        self._require_transaction()
        if not validate_event_type(log.event_type):
            raise ValueError(f"event_type must be one of Phase1.1 closed enum, got: {log.event_type!r}")
        self.session.add(log)
        return log

    async def list_by_strategy(
        self, strategy_id: str, limit: Optional[int] = None
    ) -> List[PositionReconcileLog]:
        """按 strategy_id 查询，按 created_at 倒序。"""
        stmt = (
            select(PositionReconcileLog)
            .where(PositionReconcileLog.strategy_id == strategy_id)
            .order_by(PositionReconcileLog.created_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
