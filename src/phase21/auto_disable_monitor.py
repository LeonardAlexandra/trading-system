"""
Phase2.1 B.2：AutoDisableMonitor — 异常触发自动熔断

触发条件（B.2 默认阈值，均可配置覆盖）：
  - 连续亏损笔数 ≥ 5 笔（consecutive_loss_trades）
  - 连续亏损金额 ≥ 1000（consecutive_loss_amount）
  - 最大回撤 ≥ 10%（max_drawdown_pct）
  - 系统健康检查失败（db_ok 或 exchange_ok 为 False）

触发时（三者均执行，写死）：
  1. active → disabled
  2. 若有 stable，stable → active（自动回滚）
  3. 写 release_audit(action=AUTO_DISABLE) + 写 LogRepository 强告警

本模块仅读 trade 表（计算连续亏损），不写 Phase 2.0 表（B.6 约束）。
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.release_audit import ReleaseAudit, ACTION_AUTO_DISABLE
from src.models.trade import Trade
from src.models.param_version import RELEASE_STATE_DISABLED, RELEASE_STATE_ACTIVE, RELEASE_STATE_STABLE
from src.repositories.param_version_repository import ParamVersionRepository
from src.repositories.release_audit_repository import ReleaseAuditRepository


@dataclass
class AutoDisableConfig:
    """B.2 异常条件阈值（均可覆盖）。"""
    consecutive_loss_trades: int = 5           # 连续亏损笔数
    consecutive_loss_amount: float = 1000.0    # 连续亏损累计金额
    max_drawdown_pct: float = 10.0             # 最大回撤百分比（%）
    check_health: bool = True                  # 是否检查健康状态


@dataclass
class AutoDisableResult:
    triggered: bool
    trigger_reason: Optional[str] = None
    prev_active_id: Optional[str] = None
    rolled_back_to: Optional[str] = None      # stable 版本 ID（若有）
    audit_id: Optional[int] = None
    detail: Dict[str, Any] = field(default_factory=dict)


class AutoDisableMonitor:
    """
    异常检测与自动熔断。

    仅读 trade 表（计算连续亏损）；不写 evaluation_report / metrics_snapshot（B.6）。
    触发时调用 ReleaseGate 的底层逻辑完成状态迁移，并写强告警日志。
    """

    def __init__(
        self,
        session: AsyncSession,
        param_version_repo: ParamVersionRepository,
        release_audit_repo: ReleaseAuditRepository,
        config: Optional[AutoDisableConfig] = None,
    ) -> None:
        self._session = session
        self._pv_repo = param_version_repo
        self._audit_repo = release_audit_repo
        self._cfg = config or AutoDisableConfig()

    async def check_and_disable(
        self,
        strategy_id: str,
        *,
        db_ok: bool = True,
        exchange_ok: bool = True,
    ) -> AutoDisableResult:
        """
        检查当前策略是否触发熔断条件。
        若触发则执行三步操作：停用 active、回滚 stable（若存在）、写审计。
        """
        trigger_reason, detail = await self._detect_trigger(
            strategy_id, db_ok=db_ok, exchange_ok=exchange_ok
        )
        if not trigger_reason:
            return AutoDisableResult(triggered=False, detail=detail)

        # 步骤 1：active → disabled
        active_pv = await self._pv_repo.get_active(strategy_id)
        stable_pv = await self._pv_repo.get_stable(strategy_id)

        prev_active_id = active_pv.param_version_id if active_pv else None
        rolled_back_to = None

        if active_pv is not None:
            await self._pv_repo.update_release_state(
                active_pv.param_version_id, RELEASE_STATE_DISABLED
            )

        # 步骤 2：若有 stable，自动回滚 stable → active
        if stable_pv is not None and (
            active_pv is None or stable_pv.param_version_id != active_pv.param_version_id
        ):
            await self._pv_repo.update_release_state(
                stable_pv.param_version_id, RELEASE_STATE_ACTIVE
            )
            rolled_back_to = stable_pv.param_version_id

        # 步骤 3：写 release_audit 强告警记录
        payload: Dict[str, Any] = {
            "trigger_reason": trigger_reason,
            "detail": detail,
            "prev_active_param_version_id": prev_active_id,
            "rollback_target": rolled_back_to,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        audit = ReleaseAudit(
            strategy_id=strategy_id,
            param_version_id=prev_active_id,
            action=ACTION_AUTO_DISABLE,
            gate_type=None,
            passed=False,
            operator_or_rule_id="auto_disable_monitor",
            created_at=datetime.now(timezone.utc),
            payload=payload,
        )
        audit_row = await self._audit_repo.append(audit)

        return AutoDisableResult(
            triggered=True,
            trigger_reason=trigger_reason,
            prev_active_id=prev_active_id,
            rolled_back_to=rolled_back_to,
            audit_id=audit_row.id,
            detail=detail,
        )

    async def _detect_trigger(
        self,
        strategy_id: str,
        *,
        db_ok: bool,
        exchange_ok: bool,
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        检测熔断触发条件。
        返回 (trigger_reason_or_None, detail_dict)。
        """
        cfg = self._cfg
        detail: Dict[str, Any] = {}

        # 健康检查失败
        if cfg.check_health and (not db_ok or not exchange_ok):
            return (
                "health_check_failure",
                {"db_ok": db_ok, "exchange_ok": exchange_ok},
            )

        # 读取最近 N 笔 trade（用于连续亏损检测）
        n = max(cfg.consecutive_loss_trades, 20)  # 多读几条，确保能计算
        stmt = (
            select(Trade)
            .where(Trade.strategy_id == strategy_id)
            .order_by(desc(Trade.executed_at))
            .limit(n)
        )
        result = await self._session.execute(stmt)
        trades: List[Trade] = list(result.scalars().all())

        if not trades:
            return None, detail

        # 按时间正序排列（最老的在前）
        trades_sorted = sorted(trades, key=lambda t: (t.executed_at or datetime.min, t.trade_id or ""))

        # 计算连续亏损笔数与累计亏损金额（从最新交易往前数）
        consecutive_loss = 0
        consecutive_loss_amount = Decimal("0")
        for t in reversed(trades_sorted):
            pnl = t.realized_pnl if t.realized_pnl is not None else Decimal("0")
            if pnl < Decimal("0"):
                consecutive_loss += 1
                consecutive_loss_amount += abs(pnl)
            else:
                break  # 遇到盈利交易，连续亏损链中断

        detail["consecutive_loss_trades"] = consecutive_loss
        detail["consecutive_loss_amount"] = float(consecutive_loss_amount)

        if consecutive_loss >= cfg.consecutive_loss_trades:
            return (
                f"consecutive_loss_trades>={cfg.consecutive_loss_trades}",
                detail,
            )

        if float(consecutive_loss_amount) >= cfg.consecutive_loss_amount:
            return (
                f"consecutive_loss_amount>={cfg.consecutive_loss_amount}",
                detail,
            )

        # 最大回撤检测（使用 realized_pnl 累计曲线的峰谷回撤）
        max_drawdown_pct = _compute_max_drawdown_pct(trades_sorted)
        detail["max_drawdown_pct"] = max_drawdown_pct

        if max_drawdown_pct >= cfg.max_drawdown_pct:
            return (
                f"max_drawdown_pct>={cfg.max_drawdown_pct}",
                detail,
            )

        return None, detail


def _compute_max_drawdown_pct(trades: List[Trade]) -> float:
    """
    基于 realized_pnl 累计曲线计算峰谷最大回撤百分比。
    仅用于内部熔断判断，不产出 Phase 2.0 评估结论。
    """
    if not trades:
        return 0.0

    cumulative = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")

    for t in trades:
        pnl = t.realized_pnl if t.realized_pnl is not None else Decimal("0")
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        if peak > Decimal("0"):
            dd = (peak - cumulative) / peak * Decimal("100")
            if dd > max_dd:
                max_dd = dd

    return float(max_dd)
