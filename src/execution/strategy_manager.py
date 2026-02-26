"""
Phase1.1 C5：策略挂起（PAUSED + STRATEGY_PAUSED 终态日志，同一事务）
Phase1.1 C6：STRATEGY_PAUSED 终态日志含差异快照（格式固定、可解析、与 B1 diff 可复用）

当风控判定超仓或不可接受时，将策略状态更新为 PAUSED、写入 STRATEGY_PAUSED 终态日志（含差异快照），
二者在同一事务内完成；持 ReconcileLock 期间仅做 DB 写，禁止外部 I/O。
"""

# C6 差异快照 schema（预定义字段，不得超出；与 B1 diff 可复用部分结构）
# - reason_code: str, 风控/挂起原因码，如 POSITION_LIMIT_EXCEEDED
# - message: str, 说明文本，最大 DIFF_SNAPSHOT_MAX_MESSAGE_LEN 字符
# - positions: list[{symbol, side, quantity}] 当前持仓摘要（不含敏感数据）
# 禁止包含：账户 ID、余额、webhook secret、raw payload、签名等敏感信息（Phase1.1 日志/快照约定）
DIFF_SNAPSHOT_MAX_MESSAGE_LEN = 500
DIFF_SNAPSHOT_REQUIRED_KEYS = frozenset({"reason_code", "message", "positions"})

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.position_reconcile_log import STRATEGY_PAUSED, STRATEGY_RESUMED
from src.models.strategy_runtime_state import STATUS_PAUSED
from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.repositories.position_repository import PositionRepository
from src.locks.reconcile_lock import ReconcileLock

logger = logging.getLogger(__name__)

# B1 diff 标准：400 响应体顶层字段（Phase1.1 唯一标准，不得另起格式）
RESUME_CHECK_FAILED_CODE = "RESUME_CHECK_FAILED"
FIELD_STATE_IS_PAUSED = "state_is_paused"
FIELD_RISK_PASSED = "risk_passed"


def _build_diff_snapshot(
    reason_code: str,
    message: str,
    positions: List[Any],
) -> str:
    """
    C6：组装 STRATEGY_PAUSED 差异快照（当前持仓 + 挂起原因），格式固定、可解析，与 B1 diff 可复用。

    仅包含预定义字段（reason_code, message, positions），不包含敏感数据。
    生成失败时抛出异常，由调用方事务回滚，避免「有状态无快照」不一致。
    """
    positions_summary = [
        {
            "symbol": getattr(p, "symbol", None),
            "side": getattr(p, "side", None),
            "quantity": str(getattr(p, "quantity", 0)),
        }
        for p in positions
    ]
    payload: Dict[str, Any] = {
        "reason_code": reason_code or "",
        "message": (message or "")[:DIFF_SNAPSHOT_MAX_MESSAGE_LEN],
        "positions": positions_summary,
    }
    try:
        out = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        logger.exception("C6: diff_snapshot build failed: %s", e)
        raise RuntimeError(f"C6: diff_snapshot must be serializable: {e!s}") from e
    if not out or not out.strip():
        raise RuntimeError("C6: diff_snapshot must be non-empty")
    return out


async def pause_strategy(
    session: AsyncSession,
    strategy_id: str,
    reason_code: str,
    message: str,
    *,
    state_repo: StrategyRuntimeStateRepository,
    reconcile_log_repo: PositionReconcileLogRepository,
    position_repo: PositionRepository,
    lock_holder_id: str = "strategy-pause",
) -> bool:
    """
    C5：风控不通过/超仓时挂起策略——更新 PAUSED + 写 STRATEGY_PAUSED 终态日志（含差异快照），同一事务内完成。

    持 ReconcileLock 期间仅做：更新 strategy_runtime_state.status、写 position_reconcile_log；
    禁止锁内外部 I/O。任一步失败则整体回滚（由调用方事务边界保证）。

    Returns:
        True 表示挂起成功（状态已更新且日志已写），False 表示未获取到锁。
    """
    if not session.in_transaction():
        raise RuntimeError(
            "pause_strategy must be called inside an active transaction "
            "(e.g. async with session.begin()) so that PAUSED and STRATEGY_PAUSED log are in the same boundary."
        )
    lock = ReconcileLock(session, lock_holder_id, max_acquire_retries=2, retry_interval_seconds=0.1)
    async with lock.use_lock(strategy_id) as acquired:
        if not acquired:
            logger.warning("pause_strategy: ReconcileLock not acquired strategy_id=%s", strategy_id)
            return False
        positions = await position_repo.get_all_by_strategy(strategy_id)
        diff_snapshot = _build_diff_snapshot(reason_code, message, positions)
        updated = await state_repo.update_status_to_paused(strategy_id)
        if not updated:
            logger.error("pause_strategy: update_status_to_paused failed strategy_id=%s", strategy_id)
            raise RuntimeError(
                f"C5: Failed to set PAUSED for strategy_id={strategy_id} (row not found or not updated)"
            )
        await reconcile_log_repo.log_event_in_txn(
            strategy_id=strategy_id,
            event_type=STRATEGY_PAUSED,
            diff_snapshot=diff_snapshot,
        )
        logger.info(
            "pause_strategy: strategy_id=%s set PAUSED and STRATEGY_PAUSED log written reason_code=%s",
            strategy_id,
            reason_code,
        )
        return True
    # 未获取到锁时不会进入上述 return True 分支，此处不可达；为类型/防御性保留
    return False


async def _build_resumed_snapshot(
    strategy_id: str, reconcile_log_repo: PositionReconcileLogRepository
) -> str:
    """
    C7：构建 STRATEGY_RESUMED 终态日志的 diff_snapshot（与 B1 恢复成功分支同事务内调用）。

    内容至少含：触发方式（trigger）、恢复前状态（previous_status）；可选恢复前挂起原因（来自最近一条 STRATEGY_PAUSED 的 reason_code/message）。
    策略 ID 在行上；恢复时间由 position_reconcile_log.created_at 记录。
    """
    payload: Dict[str, Any] = {
        "trigger": "API",
        "previous_status": STATUS_PAUSED,
    }
    try:
        logs = await reconcile_log_repo.list_by_strategy(strategy_id, limit=50)
        for log in logs:
            if getattr(log, "event_type", None) == STRATEGY_PAUSED and getattr(log, "diff_snapshot", None):
                raw = log.diff_snapshot.strip()
                if raw:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        payload["previous_paused_reason_code"] = data.get("reason_code")
                        payload["previous_paused_message"] = (data.get("message") or "")[:500]
                    break
    except Exception:
        pass
    return json.dumps(payload, ensure_ascii=False)


def _build_resume_diff(
    strategy_id: str,
    current_status: str,
    checks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """B1：构建 400 响应体 diff，结构固定（code, checks, snapshot），可被调用方解析。"""
    return {
        "code": RESUME_CHECK_FAILED_CODE,
        "checks": checks,
        "snapshot": {
            "strategy_id": strategy_id,
            "status": current_status,
        },
    }


async def resume_strategy(
    session: AsyncSession,
    strategy_id: str,
    *,
    state_repo: StrategyRuntimeStateRepository,
    position_repo: PositionRepository,
    reconcile_log_repo: PositionReconcileLogRepository,
    risk_manager: Any,
    risk_config_override: Optional[Any] = None,
    lock_holder_id: str = "strategy-resume",
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    B1：强校验恢复。仅当 state_is_paused 且 risk_passed 时执行恢复；否则返回 diff 供 400 响应。

    强校验项：策略状态为 PAUSED、风控 full_check 通过。
    成功时：持锁内更新 RUNNING + 写 STRATEGY_RESUMED 终态日志（与 C7 同事务）。
    Returns:
        ("ok", None) 恢复成功；
        ("not_found", None) 策略不存在；
        ("check_failed", diff) 强校验未通过，diff 符合 Phase1.1 标准公式。
    """
    if not session.in_transaction():
        raise RuntimeError(
            "resume_strategy must be called inside an active transaction "
            "(e.g. async with session.begin()) so that RUNNING and STRATEGY_RESUMED are in the same boundary."
        )
    state = await state_repo.get_by_strategy_id(strategy_id)
    if state is None:
        return ("not_found", None)
    current_status = getattr(state, "status", None) or ""
    check_state_paused = current_status == STATUS_PAUSED
    positions = await position_repo.get_all_by_strategy(strategy_id)
    risk_result = await risk_manager.full_check(strategy_id, positions, risk_config_override)
    risk_passed = risk_result.get("passed", False)
    checks = [
        {
            "field": FIELD_STATE_IS_PAUSED,
            "expected": True,
            "actual": current_status == STATUS_PAUSED,
            "pass": check_state_paused,
        },
        {
            "field": FIELD_RISK_PASSED,
            "expected": True,
            "actual": risk_passed,
            "pass": risk_passed,
        },
    ]
    if not check_state_paused or not risk_passed:
        diff = _build_resume_diff(strategy_id, current_status, checks)
        logger.info(
            "resume_strategy: strong check failed strategy_id=%s checks=%s",
            strategy_id,
            [c["pass"] for c in checks],
        )
        return ("check_failed", diff)
    lock = ReconcileLock(session, lock_holder_id, max_acquire_retries=2, retry_interval_seconds=0.1)
    async with lock.use_lock(strategy_id) as acquired:
        if not acquired:
            checks_lock = [
                {"field": "lock_acquired", "expected": True, "actual": False, "pass": False},
            ]
            diff = _build_resume_diff(strategy_id, current_status, checks + checks_lock)
            return ("check_failed", diff)
        updated = await state_repo.update_status_to_running(strategy_id)
        if not updated:
            logger.error("resume_strategy: update_status_to_running failed strategy_id=%s", strategy_id)
            raise RuntimeError(f"B1: Failed to set RUNNING for strategy_id={strategy_id}")
        # C7：STRATEGY_RESUMED 终态日志内容至少含策略 ID（行上）、恢复时间（created_at）、触发方式、可选恢复前挂起原因
        resumed_snapshot = await _build_resumed_snapshot(strategy_id, reconcile_log_repo)
        await reconcile_log_repo.log_event_in_txn(
            strategy_id=strategy_id,
            event_type=STRATEGY_RESUMED,
            diff_snapshot=resumed_snapshot,
        )
        logger.info("resume_strategy: strategy_id=%s set RUNNING and STRATEGY_RESUMED log written", strategy_id)
        return ("ok", None)
