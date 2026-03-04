"""
Phase 2.2：BI 只读 API 路由（A1、A2、B1、B2）

本文件为 Phase 2.2 BI 层的所有只读端点的唯一实现文件。

【只读边界（宪法级约束，写死）】
- 所有端点均为 GET，不提供 POST/PUT/DELETE。
- 不调用 Evaluator.evaluate、Optimizer.suggest、ReleaseGate 任何写接口。
- 不写入任何 Phase 1.2/2.0/2.1 业务表。
- 不新增计算口径，不派生第二套指标。
- 不生成"新解释""自动结论""建议怎么做"。
- 不成为控制面（无触发按钮、无状态变更入口）。

【数据来源（写死）】
- A1 /stats          ← Phase 2.0: metrics_snapshot 只读查询
- A1 /equity_curve   ← Phase 1.2: trade 表只读聚合（按 2.0 口径）
- A2 /decision_flow  ← Phase 1.2: TraceQueryService 只读（C2 追溯 API）
- B1 /version_history    ← Phase 2.1: param_version 只读查询
- B1 /evaluation_history ← Phase 2.0: evaluation_report 只读查询
- B2 /release_audit      ← Phase 2.1: release_audit 只读查询

【脱敏（B4，写死）】
- 当前为单租户/内网使用，不实现认证层。
- API key、交易所密钥、okx secret 等敏感字段不在任何响应中出现。
- operator_or_rule_id 字段在 viewer 层按"***" 处理（可选）。
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select, func as sa_func

from src.app.dependencies import get_db_session
from src.models.evaluation_report import EvaluationReport
from src.models.metrics_snapshot import MetricsSnapshot
from src.models.param_version import ParamVersion
from src.models.release_audit import ReleaseAudit
from src.models.trade import Trade
from src.services.trace_query_service import TraceQueryService
from src.schemas.trace import TRACE_STATUS_NOT_FOUND, TRACE_STATUS_PARTIAL

router = APIRouter(prefix="/api/bi", tags=["bi"])

# ────────── 常量 ──────────
_BI_READONLY_NOTE = "本 API 为只读，不改变任何业务状态。"
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


# ────────── 辅助 ──────────

def _parse_dt(s: Optional[str], default: Optional[datetime] = None) -> Optional[datetime]:
    if not s:
        return default
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return default


def _decimal_to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


# ═══════════════════════════════════════════════════════════════════
# A1 — 完整交易统计（数据来自 Phase 2.0 metrics_snapshot）
# ═══════════════════════════════════════════════════════════════════

@router.get("/stats", summary="完整交易统计 [只读]")
async def get_stats(
    from_: Optional[str] = Query(None, alias="from", description="ISO8601 开始时间"),
    to: Optional[str] = Query(None, description="ISO8601 结束时间"),
    group_by: Optional[str] = Query(None, description="day | week | strategy_id（当前返回汇总）"),
    strategy_id: Optional[str] = Query(None, description="策略 ID（可选过滤）"),
):
    """
    A1：完整交易统计只读 API。

    数据来自 Phase 2.0 metrics_snapshot（只读查询），与 2.0 指标口径完全一致。
    不在 BI 层重算指标，不写任何业务表。

    {readonly_note}
    """.format(readonly_note=_BI_READONLY_NOTE)
    from_dt = _parse_dt(from_)
    to_dt = _parse_dt(to)

    async with get_db_session() as session:
        stmt = select(MetricsSnapshot)
        if strategy_id:
            stmt = stmt.where(MetricsSnapshot.strategy_id == strategy_id)
        if from_dt:
            stmt = stmt.where(MetricsSnapshot.period_end >= from_dt)
        if to_dt:
            stmt = stmt.where(MetricsSnapshot.period_start <= to_dt)
        stmt = stmt.order_by(desc(MetricsSnapshot.period_end), desc(MetricsSnapshot.id))
        result = await session.execute(stmt)
        snapshots = list(result.scalars().all())

    items = [
        {
            "id": s.id,
            "strategy_id": s.strategy_id,
            "strategy_version_id": s.strategy_version_id,
            "param_version_id": s.param_version_id,
            "period_start": s.period_start.isoformat() if s.period_start else None,
            "period_end": s.period_end.isoformat() if s.period_end else None,
            "trade_count": s.trade_count,
            "win_rate": _decimal_to_float(s.win_rate),
            "realized_pnl": _decimal_to_float(s.realized_pnl),
            "max_drawdown": _decimal_to_float(s.max_drawdown),
            "avg_holding_time_sec": _decimal_to_float(s.avg_holding_time_sec),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]
    return {
        "note": _BI_READONLY_NOTE,
        "data_source": "Phase 2.0 metrics_snapshot (read-only)",
        "group_by": group_by,
        "count": len(items),
        "items": items,
    }


# ═══════════════════════════════════════════════════════════════════
# A1 — 权益曲线（数据来自 Phase 1.2 trade 表，只读聚合）
# ═══════════════════════════════════════════════════════════════════

@router.get("/equity_curve", summary="权益曲线 [只读]")
async def get_equity_curve(
    strategy_id: Optional[str] = Query(None, description="策略 ID"),
    from_: Optional[str] = Query(None, alias="from", description="ISO8601 开始时间"),
    to: Optional[str] = Query(None, description="ISO8601 结束时间"),
    granularity: Optional[str] = Query("day", description="day | week（当前聚合粒度说明）"),
):
    """
    A1：权益曲线只读 API。

    数据来自 Phase 1.2 trade 表（realized_pnl 累积曲线），与 2.0 评估口径一致。
    不在 BI 层引入新口径；按时间排序返回累积 realized_pnl 时序点。

    {readonly_note}
    """.format(readonly_note=_BI_READONLY_NOTE)
    from_dt = _parse_dt(from_)
    to_dt = _parse_dt(to)

    async with get_db_session() as session:
        stmt = select(Trade).where(Trade.realized_pnl.isnot(None))
        if strategy_id:
            stmt = stmt.where(Trade.strategy_id == strategy_id)
        if from_dt:
            stmt = stmt.where(Trade.executed_at >= from_dt)
        if to_dt:
            stmt = stmt.where(Trade.executed_at <= to_dt)
        stmt = stmt.order_by(Trade.executed_at)
        result = await session.execute(stmt)
        trades = list(result.scalars().all())

    cumulative = Decimal("0")
    points = []
    for t in trades:
        pnl = t.realized_pnl if t.realized_pnl is not None else Decimal("0")
        cumulative += pnl
        points.append(
            {
                "trade_id": t.trade_id,
                "strategy_id": t.strategy_id,
                "executed_at": t.executed_at.isoformat() if t.executed_at else None,
                "realized_pnl": _decimal_to_float(pnl),
                "cumulative_pnl": _decimal_to_float(cumulative),
            }
        )

    return {
        "note": _BI_READONLY_NOTE,
        "data_source": "Phase 1.2 trade table (read-only, realized_pnl cumulative)",
        "granularity": granularity,
        "strategy_id": strategy_id,
        "count": len(points),
        "points": points,
    }


# ═══════════════════════════════════════════════════════════════════
# A2 — 决策过程展示（数据来自 Phase 1.2 TraceQueryService）
# ═══════════════════════════════════════════════════════════════════

@router.get("/decision_flow", summary="单笔决策链路 [只读]")
async def get_decision_flow(
    decision_id: Optional[str] = Query(None),
    signal_id: Optional[str] = Query(None),
):
    """
    A2：单笔决策链路只读展示（信号→理由→风控→执行）。

    数据来自 Phase 1.2 TraceQueryService（只读）。
    PARTIAL/NOT_FOUND 时清晰展示 trace_status 与 missing_nodes。
    不在 BI 层生成新解释或推断原因。

    {readonly_note}
    """.format(readonly_note=_BI_READONLY_NOTE)
    if not decision_id and not signal_id:
        return _err(400, "需要提供 decision_id 或 signal_id")

    async with get_db_session() as session:
        svc = TraceQueryService(session)
        if decision_id:
            result = await svc.get_trace_by_decision_id(decision_id)
        else:
            result = await svc.get_trace_by_signal_id(signal_id)

    if result.trace_status == TRACE_STATUS_NOT_FOUND:
        return _err(404, f"未找到对应的决策链路 (decision_id={decision_id}, signal_id={signal_id})")

    trace_dict = result.to_dict()
    trace_dict["note"] = _BI_READONLY_NOTE
    trace_dict["data_source"] = "Phase 1.2 TraceQueryService (read-only)"
    # PARTIAL/NOT_FOUND 时 missing_nodes 已在 trace_dict 中
    return trace_dict


@router.get("/decision_flow/list", summary="决策链路列表 [只读]")
async def list_decision_flow(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    strategy_id: Optional[str] = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """
    A2：决策链路列表只读展示。

    数据来自 Phase 1.2 TraceQueryService（只读）。
    每条含 trace_status、missing_nodes（若 PARTIAL）。
    不生成新解释，不写任何业务表。

    {readonly_note}
    """.format(readonly_note=_BI_READONLY_NOTE)
    now = datetime.now(timezone.utc)
    from_dt = _parse_dt(from_, default=now.replace(year=now.year - 1))
    to_dt = _parse_dt(to, default=now)

    from src.services import audit_service

    async with get_db_session() as session:
        items = await audit_service.list_traces(
            session,
            from_ts=from_dt,
            to_ts=to_dt,
            strategy_id=strategy_id,
            limit=limit,
            offset=offset,
        )

    return {
        "note": _BI_READONLY_NOTE,
        "data_source": "Phase 1.2 TraceQueryService (read-only)",
        "count": len(items),
        "items": [
            {
                "decision_id": t.decision_id,
                "strategy_id": t.strategy_id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": _decimal_to_float(t.quantity),
                "trace_status": getattr(t, "trace_status", None),
                "missing_nodes": getattr(t, "missing_nodes", []),
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in items
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# B1 — 版本历史（数据来自 Phase 2.1 param_version）
# ═══════════════════════════════════════════════════════════════════

@router.get("/version_history", summary="参数版本历史 [只读]")
async def get_version_history(
    strategy_id: Optional[str] = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
):
    """
    B1：策略/参数版本变更历史只读展示。

    数据来自 Phase 2.1 param_version（只读查询）。
    展示字段与 2.1 schema 一致；不合成综合评分或自动结论。

    {readonly_note}
    """.format(readonly_note=_BI_READONLY_NOTE)
    async with get_db_session() as session:
        stmt = select(ParamVersion)
        if strategy_id:
            stmt = stmt.where(ParamVersion.strategy_id == strategy_id)
        stmt = stmt.order_by(desc(ParamVersion.created_at), desc(ParamVersion.id)).limit(limit)
        result = await session.execute(stmt)
        versions = list(result.scalars().all())

    return {
        "note": _BI_READONLY_NOTE,
        "data_source": "Phase 2.1 param_version (read-only)",
        "count": len(versions),
        "items": [
            {
                "id": v.id,
                "param_version_id": v.param_version_id,
                "strategy_id": v.strategy_id,
                "strategy_version_id": v.strategy_version_id,
                "params": v.params,
                "release_state": v.release_state,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "updated_at": v.updated_at.isoformat() if v.updated_at else None,
            }
            for v in versions
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# B1 — 评估历史（数据来自 Phase 2.0 evaluation_report）
# ═══════════════════════════════════════════════════════════════════

@router.get("/evaluation_history", summary="评估报告历史 [只读]")
async def get_evaluation_history(
    strategy_id: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
):
    """
    B1：评估报告历史只读展示。

    数据来自 Phase 2.0 evaluation_report（只读查询），字段与 2.0 schema 一致。
    不调用 Evaluator.evaluate，不合成综合评分。

    {readonly_note}
    """.format(readonly_note=_BI_READONLY_NOTE)
    from_dt = _parse_dt(from_)
    to_dt = _parse_dt(to)

    async with get_db_session() as session:
        stmt = select(EvaluationReport)
        if strategy_id:
            stmt = stmt.where(EvaluationReport.strategy_id == strategy_id)
        if from_dt:
            stmt = stmt.where(EvaluationReport.evaluated_at >= from_dt)
        if to_dt:
            stmt = stmt.where(EvaluationReport.evaluated_at <= to_dt)
        stmt = stmt.order_by(desc(EvaluationReport.evaluated_at), desc(EvaluationReport.id)).limit(limit)
        result = await session.execute(stmt)
        reports = list(result.scalars().all())

    return {
        "note": _BI_READONLY_NOTE,
        "data_source": "Phase 2.0 evaluation_report (read-only)",
        "count": len(reports),
        "items": [
            {
                "id": r.id,
                "strategy_id": r.strategy_id,
                "strategy_version_id": r.strategy_version_id,
                "param_version_id": r.param_version_id,
                "evaluated_at": r.evaluated_at.isoformat() if r.evaluated_at else None,
                "period_start": r.period_start.isoformat() if r.period_start else None,
                "period_end": r.period_end.isoformat() if r.period_end else None,
                "objective_definition": r.objective_definition,
                "constraint_definition": r.constraint_definition,
                "baseline_version_id": r.baseline_version_id,
                "conclusion": r.conclusion,
                "comparison_summary": r.comparison_summary,
                "metrics_snapshot_id": r.metrics_snapshot_id,
            }
            for r in reports
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# B2 — 门禁/回滚/自动停用历史（数据来自 Phase 2.1 release_audit）
# ═══════════════════════════════════════════════════════════════════

@router.get("/release_audit", summary="门禁/回滚/停用历史 [只读]")
async def get_release_audit(
    strategy_id: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
):
    """
    B2：门禁/回滚/自动停用历史只读展示。

    数据来自 Phase 2.1 release_audit（只读查询）。
    action/gate_type 等字段与 2.1 定义一致；不触发任何门禁或回滚。
    本接口不成为"第二个 ReleaseGate"。

    {readonly_note}
    """.format(readonly_note=_BI_READONLY_NOTE)
    from_dt = _parse_dt(from_)
    to_dt = _parse_dt(to)

    async with get_db_session() as session:
        stmt = select(ReleaseAudit)
        if strategy_id:
            stmt = stmt.where(ReleaseAudit.strategy_id == strategy_id)
        if from_dt:
            stmt = stmt.where(ReleaseAudit.created_at >= from_dt)
        if to_dt:
            stmt = stmt.where(ReleaseAudit.created_at <= to_dt)
        stmt = stmt.order_by(desc(ReleaseAudit.created_at), desc(ReleaseAudit.id)).limit(limit)
        result = await session.execute(stmt)
        records = list(result.scalars().all())

    return {
        "note": _BI_READONLY_NOTE,
        "data_source": "Phase 2.1 release_audit (read-only)",
        "count": len(records),
        "items": [
            {
                "id": r.id,
                "strategy_id": r.strategy_id,
                "param_version_id": r.param_version_id,
                "action": r.action,
                "gate_type": r.gate_type,
                "passed": r.passed,
                # B4 脱敏：operator_or_rule_id 仅展示是否存在，不暴露内部规则 ID
                "has_operator": r.operator_or_rule_id is not None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "payload": r.payload,
            }
            for r in records
        ],
    }
