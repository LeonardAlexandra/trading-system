"""
Phase1.1 B1：POST /strategy/{id}/resume（强校验恢复 + diff 标准公式）
Phase1.1 B2：GET /strategy/{id}/status（只读状态查询，可选但推荐）

路径参数 id 为策略 ID。强校验未通过返回 400 且响应体为 Phase1.1 diff 结构；
通过则 2xx，策略状态变为 RUNNING，STRATEGY_RESUMED 落库（与 C7 衔接）。
B2 为只读接口，不改变状态、不写 DB、不触发 reconcile/risk。
"""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.app.dependencies import get_db_session
from src.execution.strategy_manager import resume_strategy
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.models.strategy_runtime_state import STATUS_PAUSED
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/strategy", tags=["strategy"])


@router.get("/{id}/status")
async def get_strategy_status(id: str):
    """
    B2：只读策略状态查询。真理源为 strategy_runtime_state 及与状态相关表；
    不改变任何状态、不写 DB、不触发 reconcile/risk。不存在的 id 返回 404。
    """
    strategy_id = id.strip()
    if not strategy_id:
        return JSONResponse(
            status_code=422,
            content={"detail": "strategy id is required", "code": "INVALID_ID"},
        )
    async with get_db_session() as session:
        state_repo = StrategyRuntimeStateRepository(session)
        reconcile_log_repo = PositionReconcileLogRepository(session)
        state = await state_repo.get_by_strategy_id(strategy_id)
        if state is None:
            return JSONResponse(
                status_code=404,
                content={"detail": "strategy not found", "strategy_id": strategy_id},
            )
        # 与恢复相关的摘要：是否可 resume、最后对账相关时间（来自 position_reconcile_log）
        logs = await reconcile_log_repo.list_by_strategy(strategy_id, limit=1)
    last_reconcile_at = None
    if logs:
        last_reconcile_at = logs[0].created_at.isoformat() if logs[0].created_at else None
    payload = {
        "strategy_id": strategy_id,
        "status": state.status,
        "can_resume": state.status == STATUS_PAUSED,
        "last_reconcile_at": last_reconcile_at,
    }
    return JSONResponse(status_code=200, content=payload)


@router.post("/{id}/resume")
async def post_resume(id: str):
    """
    B1：强校验恢复。仅当策略状态为 PAUSED 且风控 full_check 通过时恢复为 RUNNING 并写 STRATEGY_RESUMED。
    否则返回 400 及标准 diff（code, checks, snapshot）。
    """
    strategy_id = id.strip()
    if not strategy_id:
        return JSONResponse(
            status_code=422,
            content={"detail": "strategy id is required", "code": "INVALID_ID"},
        )
    async with get_db_session() as session:
        async with session.begin():
            state_repo = StrategyRuntimeStateRepository(session)
            position_repo = PositionRepository(session)
            reconcile_log_repo = PositionReconcileLogRepository(session)
            risk_config = RiskConfig()
            risk_manager = RiskManager(position_repo=position_repo, risk_config=risk_config)
            outcome, diff = await resume_strategy(
                session,
                strategy_id,
                state_repo=state_repo,
                position_repo=position_repo,
                reconcile_log_repo=reconcile_log_repo,
                risk_manager=risk_manager,
                risk_config_override=risk_config,
            )
    if outcome == "not_found":
        return JSONResponse(
            status_code=404,
            content={"detail": "strategy not found", "strategy_id": strategy_id},
        )
    if outcome == "check_failed":
        return JSONResponse(status_code=400, content=diff)
    return JSONResponse(status_code=200, content={"status": "resumed", "strategy_id": strategy_id})
