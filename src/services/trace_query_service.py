"""
Phase1.2 C2：全链路追溯查询聚合服务（蓝本 D.2 + B.2）

仅做只读聚合，不修改表结构、不新增迁移、不写入。
数据来源：dedup_signal, decision_order_map, decision_snapshot, decision_order_map(execution), trade。
execution 节点：来自 decision_order_map 同一行（execution_id=decision_id, order_id=local_order_id/exchange_order_id, status）。
trade 节点：trade 表按 decision_id 关联。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.dedup_signal import DedupSignal
from src.models.decision_order_map import DecisionOrderMap
from src.models.decision_snapshot import DecisionSnapshot
from src.models.trade import Trade
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
from src.repositories.dedup_signal_repo import DedupSignalRepository
from src.models.decision_order_map_status import RESERVED, FAILED as STATUS_FAILED
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.schemas.trace import (
    ALL_MISSING_NODES,
    DecisionSummary,
    MISSING_NODE_DECISION,
    MISSING_NODE_DECISION_SNAPSHOT,
    MISSING_NODE_EXECUTION,
    MISSING_NODE_SIGNAL,
    MISSING_NODE_TRADE,
    TRACE_STATUS_COMPLETE,
    TRACE_STATUS_NOT_FOUND,
    TRACE_STATUS_PARTIAL,
    TRACE_STATUS_FAILED,
    TraceResult,
    TraceSummary,
)


def _signal_to_dict(s: DedupSignal, decision: Optional[DecisionOrderMap] = None) -> Dict[str, Any]:
    """signal 节点：至少含 signal_id, received_at；有 decision 时可补 symbol, action(side)。"""
    out: Dict[str, Any] = {
        "signal_id": s.signal_id,
        "received_at": s.received_at.isoformat() if s.received_at else None,
        "first_seen_at": s.first_seen_at.isoformat() if s.first_seen_at else None,
        "processed": s.processed,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
    if decision is not None:
        out["symbol"] = decision.symbol
        out["action"] = decision.side
    return out


def _decision_to_dict(d: DecisionOrderMap) -> Dict[str, Any]:
    """decision 节点：至少含 decision_id, strategy_id, symbol, side, quantity, reason 等。"""
    return {
        "decision_id": d.decision_id,
        "strategy_id": d.strategy_id,
        "symbol": d.symbol,
        "side": d.side,
        "quantity": str(d.quantity) if d.quantity is not None else None,
        "signal_id": d.signal_id,
        "status": d.status,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "reserved_at": d.reserved_at.isoformat() if d.reserved_at else None,
        "reason": getattr(d, "reason", None),
    }


def _snapshot_to_dict(s: DecisionSnapshot) -> Dict[str, Any]:
    """decision_snapshot 节点：与 C.1 表字段对应。"""
    return {
        "id": s.id,
        "decision_id": s.decision_id,
        "strategy_id": s.strategy_id,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "signal_state": s.signal_state,
        "position_state": s.position_state,
        "risk_check_result": s.risk_check_result,
        "decision_result": s.decision_result,
    }


def _execution_to_dict(d: DecisionOrderMap) -> Dict[str, Any]:
    """execution 节点：来自 decision_order_map，至少含 execution_id, decision_id, order_id, status。"""
    return {
        "execution_id": d.decision_id,
        "decision_id": d.decision_id,
        "order_id": d.local_order_id or d.exchange_order_id,
        "local_order_id": d.local_order_id,
        "exchange_order_id": d.exchange_order_id,
        "status": d.status,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _trade_to_dict(t: Trade) -> Dict[str, Any]:
    """trade 节点：至少含 trade_id, decision_id, symbol, side, quantity, price, realized_pnl。"""
    return {
        "trade_id": t.trade_id,
        "decision_id": t.decision_id,
        "execution_id": t.execution_id,
        "strategy_id": t.strategy_id,
        "symbol": t.symbol,
        "side": t.side,
        "quantity": str(t.quantity) if t.quantity is not None else None,
        "price": str(t.price) if t.price is not None else None,
        "realized_pnl": str(t.realized_pnl) if t.realized_pnl is not None else None,
        "executed_at": t.executed_at.isoformat() if t.executed_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


class TraceQueryService:
    """
    全链路追溯查询聚合服务。仅读聚合，不写入、不改表。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._dedup_repo = DedupSignalRepository(session)
        self._dom_repo = DecisionOrderMapRepository(session)
        self._snapshot_repo = DecisionSnapshotRepository(session)

    async def get_trace_by_signal_id(self, signal_id: str) -> TraceResult:
        """
        按 signal_id 聚合整条链路。
        查不到任何节点时返回 NOT_FOUND；部分存在时返回 PARTIAL + 已存在节点 + missing_nodes。
        """
        missing: List[str] = []
        signal_data: Optional[Dict[str, Any]] = None
        decision_row: Optional[DecisionOrderMap] = None
        snapshot_row: Optional[DecisionSnapshot] = None
        trade_row: Optional[Trade] = None

        # 1. signal
        signal = await self._dedup_repo.get(signal_id)
        if signal is None:
            return TraceResult(
                trace_status=TRACE_STATUS_NOT_FOUND,
                missing_nodes=ALL_MISSING_NODES.copy(),
                signal=None,
                decision=None,
                decision_snapshot=None,
                execution=None,
                trade=None,
            )
        signal_data = _signal_to_dict(signal)

        # 2. decision (by signal_id)
        stmt_dom = select(DecisionOrderMap).where(DecisionOrderMap.signal_id == signal_id).limit(1)
        result = await self.session.execute(stmt_dom)
        decision_row = result.scalar_one_or_none()
        if decision_row is None:
            missing.extend([MISSING_NODE_DECISION, MISSING_NODE_DECISION_SNAPSHOT, MISSING_NODE_EXECUTION, MISSING_NODE_TRADE])
            return TraceResult(
                trace_status=TRACE_STATUS_PARTIAL,
                missing_nodes=missing,
                signal=signal_data,
                decision=None,
                decision_snapshot=None,
                execution=None,
                trade=None,
            )

        decision_id = decision_row.decision_id
        decision_data = _decision_to_dict(decision_row)
        signal_data = _signal_to_dict(signal, decision_row)

        # 3. decision_snapshot
        snapshot_row = await self._snapshot_repo.get_by_decision_id(decision_id)
        if snapshot_row is None:
            missing.append(MISSING_NODE_DECISION_SNAPSHOT)

        # 4. execution（来自同一 decision_order_map 行；蓝本：有 decision 无 execution 时 missing 含 execution）
        # 视为“有 execution”仅当已提交（非仅 RESERVED 或已有 order_id）且非 FAILED
        has_execution = (
            (decision_row.local_order_id is not None
             or decision_row.exchange_order_id is not None
             or decision_row.status != RESERVED)
            and decision_row.status != STATUS_FAILED
        )
        execution_data = _execution_to_dict(decision_row) if has_execution else None
        if not has_execution:
            missing.append(MISSING_NODE_EXECUTION)

        # 5. trade
        stmt_trade = select(Trade).where(Trade.decision_id == decision_id).limit(1)
        res_trade = await self.session.execute(stmt_trade)
        trade_row = res_trade.scalar_one_or_none()
        if trade_row is None:
            missing.append(MISSING_NODE_TRADE)

        # 判断最终状态：如果 decision 状态为 FAILED，则 trace_status 至少为 PARTIAL/FAILED
        final_status = TRACE_STATUS_COMPLETE if not missing else TRACE_STATUS_PARTIAL
        if decision_row.status == STATUS_FAILED:
            final_status = TRACE_STATUS_FAILED

        missing_reason = None
        if decision_row.status == STATUS_FAILED:
            # 兼容字段名：优先取 reason，若模型无此字段则尝试 last_error
            fail_reason_val = getattr(decision_row, 'reason', None) or getattr(decision_row, 'last_error', None)
            missing_reason = {"failed_reason": fail_reason_val or "Decision marked as FAILED"}

        return TraceResult(
            trace_status=final_status,
            missing_nodes=missing,
            missing_reason=missing_reason,
            signal=signal_data,
            decision=decision_data,
            decision_snapshot=_snapshot_to_dict(snapshot_row) if snapshot_row else None,
            execution=execution_data,
            trade=_trade_to_dict(trade_row) if trade_row else None,
        )

    async def get_trace_by_decision_id(self, decision_id: str) -> TraceResult:
        """
        按 decision_id 聚合整条链路。
        查不到 decision 即 NOT_FOUND；否则按 signal_id 拉 signal，再补 snapshot/execution/trade。
        """
        decision_row = await self._dom_repo.get_by_decision_id(decision_id)
        if decision_row is None:
            return TraceResult(
                trace_status=TRACE_STATUS_NOT_FOUND,
                missing_nodes=ALL_MISSING_NODES.copy(),
                signal=None,
                decision=None,
                decision_snapshot=None,
                execution=None,
                trade=None,
            )

        signal_id = decision_row.signal_id
        missing: List[str] = []
        signal_data: Optional[Dict[str, Any]] = None
        snapshot_row: Optional[DecisionSnapshot] = None
        trade_row: Optional[Trade] = None

        if signal_id:
            signal = await self._dedup_repo.get(signal_id)
            if signal is not None:
                signal_data = _signal_to_dict(signal, decision_row)
            else:
                missing.append(MISSING_NODE_SIGNAL)
        else:
            missing.append(MISSING_NODE_SIGNAL)

        decision_data = _decision_to_dict(decision_row)
        snapshot_row = await self._snapshot_repo.get_by_decision_id(decision_id)
        if snapshot_row is None:
            missing.append(MISSING_NODE_DECISION_SNAPSHOT)
        # 视为“有 execution”仅当已提交（非仅 RESERVED 或已有 order_id）且非 FAILED
        has_execution = (
            (decision_row.local_order_id is not None
             or decision_row.exchange_order_id is not None
             or decision_row.status != RESERVED)
            and decision_row.status != STATUS_FAILED
        )
        execution_data = _execution_to_dict(decision_row) if has_execution else None
        if not has_execution:
            missing.append(MISSING_NODE_EXECUTION)

        stmt_trade = select(Trade).where(Trade.decision_id == decision_id).limit(1)
        res_trade = await self.session.execute(stmt_trade)
        trade_row = res_trade.scalar_one_or_none()
        if trade_row is None:
            missing.append(MISSING_NODE_TRADE)

        # 判断最终状态：如果 decision 状态为 FAILED，则 trace_status 强制为 FAILED
        final_status = TRACE_STATUS_COMPLETE if not missing else TRACE_STATUS_PARTIAL
        if decision_row.status == STATUS_FAILED:
            final_status = TRACE_STATUS_FAILED

        missing_reason = None
        if decision_row.status == STATUS_FAILED:
            # 兼容字段名：优先取 reason，若模型无此字段则尝试 last_error
            fail_reason_val = getattr(decision_row, 'reason', None) or getattr(decision_row, 'last_error', None)
            missing_reason = {"failed_reason": fail_reason_val or "Decision marked as FAILED"}

        return TraceResult(
            trace_status=final_status,
            missing_nodes=missing,
            missing_reason=missing_reason,
            signal=signal_data,
            decision=decision_data,
            decision_snapshot=_snapshot_to_dict(snapshot_row) if snapshot_row else None,
            execution=execution_data,
            trade=_trade_to_dict(trade_row) if trade_row else None,
        )

    async def list_decisions(
        self,
        strategy_id: str,
        start_ts: datetime,
        end_ts: datetime,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DecisionSummary]:
        """按 strategy_id + 时间范围分页列表。"""
        stmt = (
            select(DecisionOrderMap)
            .where(
                DecisionOrderMap.strategy_id == strategy_id,
                DecisionOrderMap.created_at >= start_ts,
                DecisionOrderMap.created_at <= end_ts,
            )
            .order_by(DecisionOrderMap.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        return [
            DecisionSummary(
                decision_id=r.decision_id,
                strategy_id=r.strategy_id or "",
                symbol=r.symbol or "",
                side=r.side or "",
                quantity=r.quantity,
                created_at=r.created_at,
                status=r.status,
                signal_id=r.signal_id,
            )
            for r in rows
        ]

    async def list_decisions_by_time(
        self,
        start_ts: datetime,
        end_ts: datetime,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DecisionSummary]:
        """按时间范围分页列表（不按 strategy_id 过滤）。"""
        stmt = (
            select(DecisionOrderMap)
            .where(
                DecisionOrderMap.created_at >= start_ts,
                DecisionOrderMap.created_at <= end_ts,
            )
            .order_by(DecisionOrderMap.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        return [
            DecisionSummary(
                decision_id=r.decision_id,
                strategy_id=r.strategy_id or "",
                symbol=r.symbol or "",
                side=r.side or "",
                quantity=r.quantity,
                created_at=r.created_at,
                status=r.status,
                signal_id=r.signal_id,
            )
            for r in rows
        ]

    async def get_recent_n(self, n: int, strategy_id: Optional[str] = None) -> List[DecisionSummary]:
        """最近 n 条决策；可选 strategy_id 过滤。"""
        stmt = select(DecisionOrderMap).order_by(DecisionOrderMap.created_at.desc()).limit(n)
        if strategy_id is not None:
            stmt = stmt.where(DecisionOrderMap.strategy_id == strategy_id)
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        return [
            DecisionSummary(
                decision_id=r.decision_id,
                strategy_id=r.strategy_id or "",
                symbol=r.symbol or "",
                side=r.side or "",
                quantity=r.quantity,
                created_at=r.created_at,
                status=r.status,
                signal_id=r.signal_id,
            )
            for r in rows
        ]

    LIST_TRACES_MAX_LIMIT = 100

    async def list_traces(
        self,
        start_ts: datetime,
        end_ts: datetime,
        strategy_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TraceSummary]:
        """
        C8 多笔回放：按时间范围（及可选 strategy_id）分页，返回 list[TraceSummary]。
        每条必含 trace_status；PARTIAL 时 missing_nodes 必填且非空；与单链路 B.2 一致。
        """
        limit = min(limit, self.LIST_TRACES_MAX_LIMIT)
        if strategy_id is not None:
            decisions = await self.list_decisions(strategy_id, start_ts, end_ts, limit=limit, offset=offset)
        else:
            decisions = await self.list_decisions_by_time(start_ts, end_ts, limit=limit, offset=offset)

        result: List[TraceSummary] = []
        for d in decisions:
            trace = await self.get_trace_by_decision_id(d.decision_id)
            dec = trace.decision or {}
            summary_parts = []
            if dec.get("symbol"):
                summary_parts.append(dec["symbol"])
            if dec.get("side"):
                summary_parts.append(dec["side"])
            summary_str = " ".join(summary_parts) if summary_parts else None

            result.append(
                TraceSummary(
                    decision_id=d.decision_id,
                    trace_status=trace.trace_status,
                    missing_nodes=list(trace.missing_nodes) if trace.missing_nodes else [],
                    strategy_id=d.strategy_id or dec.get("strategy_id"),
                    symbol=d.symbol or dec.get("symbol"),
                    created_at=d.created_at,
                    signal_id=d.signal_id or dec.get("signal_id"),
                    summary=summary_str,
                )
            )
        return result
