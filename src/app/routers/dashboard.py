"""
Phase1.2 B1：最小 Dashboard 列表与汇总 API（TDASH-1）

仅消费 Phase1.2 已有数据（decision_snapshot、trade），只读，无副作用。
口径 D.7：trade_count = trade 表条数，pnl_sum = sum(realized_pnl)，无 trade 时为 0。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db_session
from src.models.decision_snapshot import DecisionSnapshot
from src.models.trade import Trade
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository

DASHBOARD_LIST_MAX_LIMIT = 100
DASHBOARD_RECENT_DEFAULT_N = 20
DASHBOARD_RECENT_MAX_N = 100

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _parse_iso_or_400(s: Optional[str], param_name: str) -> Optional[datetime]:
    """解析 ISO8601（支持 Z / +00:00）；参数存在但非法时抛出 HTTP 400。"""
    if s is None or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid {param_name}")


def _decision_row_to_item(row: DecisionSnapshot) -> dict:
    dr = row.decision_result or {}
    return {
        "decision_id": row.decision_id,
        "strategy_id": row.strategy_id,
        "symbol": dr.get("symbol") if isinstance(dr, dict) else "",
        "side": dr.get("side") if isinstance(dr, dict) else "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/decisions")
async def get_dashboard_decisions(
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    strategy_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=DASHBOARD_LIST_MAX_LIMIT),
):
    """
    GET /api/dashboard/decisions?from=&to=&strategy_id=&limit=100
    返回至少 decision_id, strategy_id, symbol, side, created_at。数据来自 decision_snapshot。
    """
    from_dt = _parse_iso_or_400(from_ts, "from")
    to_dt = _parse_iso_or_400(to_ts, "to")
    async with get_db_session() as session:
        repo = DecisionSnapshotRepository(session)
        if strategy_id and strategy_id.strip():
            start = from_dt or datetime(2000, 1, 1, tzinfo=timezone.utc)
            end = to_dt or datetime.now(timezone.utc)
            rows = await repo.list_by_strategy_time(strategy_id.strip(), start, end, limit=limit, offset=0)
        else:
            stmt = select(DecisionSnapshot).order_by(DecisionSnapshot.created_at.desc()).limit(limit)
            if from_dt:
                stmt = stmt.where(DecisionSnapshot.created_at >= from_dt)
            if to_dt:
                stmt = stmt.where(DecisionSnapshot.created_at <= to_dt)
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
        return [_decision_row_to_item(r) for r in rows]


@router.get("/executions")
async def get_dashboard_executions(
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=DASHBOARD_LIST_MAX_LIMIT),
):
    """
    GET /api/dashboard/executions?from=&to=&limit=100
    返回至少 decision_id, symbol, side, quantity, price, realized_pnl, created_at。数据来自 trade。
    """
    from_dt = _parse_iso_or_400(from_ts, "from")
    to_dt = _parse_iso_or_400(to_ts, "to")
    async with get_db_session() as session:
        stmt = select(Trade).order_by(Trade.created_at.desc()).limit(limit)
        if from_dt:
            stmt = stmt.where(Trade.created_at >= from_dt)
        if to_dt:
            stmt = stmt.where(Trade.created_at <= to_dt)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        out = []
        for r in rows:
            out.append({
                "decision_id": r.decision_id,
                "symbol": r.symbol,
                "side": r.side,
                "quantity": float(r.quantity) if r.quantity is not None else 0,
                "price": float(r.price) if r.price is not None else 0,
                "realized_pnl": float(r.realized_pnl) if r.realized_pnl is not None else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return out


@router.get("/summary")
async def get_dashboard_summary(
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    group_by: str = Query("day", pattern="^(day|strategy)$"),
):
    """
    GET /api/dashboard/summary?from=&to=&group_by=day|strategy
    返回 [{ group_key, trade_count, pnl_sum }]。无 trade 时返回 []。
    """
    from_dt = _parse_iso_or_400(from_ts, "from")
    to_dt = _parse_iso_or_400(to_ts, "to")
    async with get_db_session() as session:
        if group_by == "strategy":
            group_col = Trade.strategy_id
        else:
            group_col = func.date(Trade.created_at)
        stmt = select(
            group_col.label("group_key"),
            func.count(Trade.trade_id).label("trade_count"),
            func.coalesce(func.sum(Trade.realized_pnl), 0).label("pnl_sum"),
        ).group_by(group_col)
        if from_dt:
            stmt = stmt.where(Trade.created_at >= from_dt)
        if to_dt:
            stmt = stmt.where(Trade.created_at <= to_dt)
        result = await session.execute(stmt)
        rows = result.all()
        out = []
        for r in rows:
            gk = r.group_key
            if hasattr(gk, "isoformat"):
                gk = gk.isoformat() if gk else ""
            out.append({
                "group_key": str(gk) if gk is not None else "",
                "trade_count": r.trade_count or 0,
                "pnl_sum": float(r.pnl_sum) if r.pnl_sum is not None else 0,
            })
        if not out:
            return []
        return out


@router.get("/recent")
async def get_dashboard_recent(
    n: int = Query(DASHBOARD_RECENT_DEFAULT_N, ge=1, le=DASHBOARD_RECENT_MAX_N),
):
    """
    GET /api/dashboard/recent?n=20
    返回最近 n 条成交（trade 表，按 created_at 倒序）。字段同 executions。
    """
    async with get_db_session() as session:
        stmt = select(Trade).order_by(Trade.created_at.desc()).limit(n)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        out = []
        for r in rows:
            out.append({
                "decision_id": r.decision_id,
                "symbol": r.symbol,
                "side": r.side,
                "quantity": float(r.quantity) if r.quantity is not None else 0,
                "price": float(r.price) if r.price is not None else 0,
                "realized_pnl": float(r.realized_pnl) if r.realized_pnl is not None else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return out
