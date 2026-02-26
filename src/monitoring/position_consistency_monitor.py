"""
Phase1.2 C6：对账状态监控（reconcile job status）（T1.2a-5）

PositionConsistencyMonitor.get_status(strategy_id=None) -> list[ConsistencyStatus]。
数据来源：position_snapshot（positions 表）与 position_reconcile_log（对账结果）。
本模块不判断持仓与外部 diff 一致性，仅监控对账流程是否失败/卡住（RECONCILE_FAILED / RECONCILE_START 未结束）。
当对账状态为 WARNING/CRITICAL 时仅写 LogRepository（event_type=reconcile_status_alert），不污染 metrics、不调用 AlertSystem.evaluate_rules。
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.execution.exchange_adapter import ExchangeAdapter
from src.models.position_reconcile_log import RECONCILE_END, RECONCILE_FAILED, RECONCILE_START
from src.monitoring.alert_system import AlertSystem
from src.monitoring.health_checker import HealthChecker
from src.monitoring.system_monitor import SystemMonitor
from src.repositories.log_repository import LogRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.repositories.position_repository import PositionRepository

# 对账状态：OK / WARNING（进行中或卡住）/ CRITICAL（失败）
RECONCILE_STATUS_OK = "OK"
RECONCILE_STATUS_WARNING = "WARNING"
RECONCILE_STATUS_CRITICAL = "CRITICAL"


@dataclass
class ConsistencyStatus:
    """C6 蓝本：单条对账状态，必含四字段。reconcile_status 表示对账状态（非持仓 diff 一致性）。"""
    strategy_id: str
    symbol: str
    reconcile_status: str  # OK | WARNING | CRITICAL，对账流程状态
    last_reconcile_at: Optional[datetime]  # 来自 position_reconcile_log.created_at


def _reconcile_status_from_latest_event(event_type: Optional[str]) -> str:
    """
    从 position_reconcile_log 最新 event_type 推导对账状态。
    RECONCILE_FAILED -> CRITICAL；RECONCILE_START（未见到 END）-> WARNING；RECONCILE_END 等 -> OK。
    """
    if event_type == RECONCILE_FAILED:
        return RECONCILE_STATUS_CRITICAL
    if event_type == RECONCILE_START:
        return RECONCILE_STATUS_WARNING
    return RECONCILE_STATUS_OK


class PositionConsistencyMonitor:
    """
    C6：对账状态监控。只读聚合 position_snapshot（positions 表）与 position_reconcile_log；
    当存在 WARNING/CRITICAL（对账失败或卡住）时仅写 LogRepository（reconcile_status_alert），不调用 AlertSystem.evaluate_rules，不污染 metrics。
    """

    def __init__(
        self,
        position_repo: PositionRepository,
        reconcile_log_repo: PositionReconcileLogRepository,
        alert_system: AlertSystem,
        system_monitor: SystemMonitor,
        health_checker: HealthChecker,
        log_repo: LogRepository,
        exchange_adapter: ExchangeAdapter,
    ):
        self._position_repo = position_repo
        self._reconcile_log_repo = reconcile_log_repo
        self._alert_system = alert_system
        self._system_monitor = system_monitor
        self._health_checker = health_checker
        self._log_repo = log_repo
        self._exchange_adapter = exchange_adapter

    async def get_status(
        self,
        session: AsyncSession,
        strategy_id: Optional[str] = None,
    ) -> List[ConsistencyStatus]:
        """
        返回 list[ConsistencyStatus]；strategy_id 为空时返回全策略。
        数据来源：positions 表（position_snapshot）与 position_reconcile_log。
        当任一条对账状态为 WARNING 或 CRITICAL 时：仅写 LogRepository（event_type=reconcile_status_alert，CRITICAL 写 ERROR 级）。
        """
        if strategy_id is not None:
            positions = await self._position_repo.get_all_by_strategy(strategy_id)
        else:
            positions = await self._position_repo.list_all()

        strategy_ids = list({p.strategy_id for p in positions})
        latest_by_strategy: dict[str, Any] = {}
        for sid in strategy_ids:
            logs = await self._reconcile_log_repo.list_by_strategy(sid, limit=1)
            if logs:
                latest_by_strategy[sid] = logs[0]
            else:
                latest_by_strategy[sid] = None

        result: List[ConsistencyStatus] = []
        has_bad = False
        bad_details: List[dict] = []

        for p in positions:
            sid = p.strategy_id
            latest = latest_by_strategy.get(sid)
            if latest is not None:
                event_type = latest.event_type
                created_at = latest.created_at
            else:
                event_type = None
                created_at = None

            status = _reconcile_status_from_latest_event(event_type)
            result.append(
                ConsistencyStatus(
                    strategy_id=sid,
                    symbol=p.symbol,
                    reconcile_status=status,
                    last_reconcile_at=created_at,
                )
            )
            if status in (RECONCILE_STATUS_WARNING, RECONCILE_STATUS_CRITICAL):
                has_bad = True
                bad_details.append({
                    "strategy_id": sid,
                    "symbol": p.symbol,
                    "reconcile_status": status,
                    "last_reconcile_at": created_at.isoformat() if created_at else None,
                })

        if has_bad:
            await self._trigger_reconcile_status_alert(session, bad_details)

        return result

    async def _trigger_reconcile_status_alert(
        self,
        session: AsyncSession,
        bad_details: List[dict],
    ) -> None:
        """
        对账状态异常时仅写 LogRepository，不调用 AlertSystem.evaluate_rules，不污染 metrics。
        CRITICAL 写 ERROR 级，WARNING 写 WARNING 级；event_type=reconcile_status_alert。
        """
        component = "position_consistency_monitor"
        has_critical = any(d.get("reconcile_status") == RECONCILE_STATUS_CRITICAL for d in bad_details)
        level = "ERROR" if has_critical else "WARNING"
        message = (
            f"Reconcile status alert: {len(bad_details)} item(s) in WARNING/CRITICAL; "
            f"details={bad_details}"
        )
        await self._log_repo.write(
            level,
            component,
            message,
            event_type="reconcile_status_alert",
            payload={"items": bad_details},
        )
