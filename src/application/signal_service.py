"""
Signal 应用服务层（PR5：去重 + 决策占位，不执行、不风控）

职责：确定性决策占位（RESERVED），不推进状态机，不调用交易所。
C7：决策生成打点 latency_ms（可选 perf_writer，独立事务 commit）。
"""
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING
from sqlalchemy.exc import OperationalError

from src.schemas.signals import TradingViewSignal
from src.repositories.dedup_signal_repo import DedupSignalRepository
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository

if TYPE_CHECKING:
    from src.repositories.perf_log_repository import PerfLogWriter


def generate_decision_id() -> str:
    """集中生成 decision_id（UUID v4），保证唯一且可追溯"""
    return str(uuid.uuid4())


class SignalApplicationService:
    """
    信号应用服务：去重 + 决策占位（RESERVED）。
    不引入 ExecutionEngine / Risk / 交易所。
    """

    def __init__(
        self,
        dedup_signal_repo: DedupSignalRepository,
        decision_order_map_repo: DecisionOrderMapRepository,
        *,
        perf_writer: Optional["PerfLogWriter"] = None,
    ):
        self._dedup_repo = dedup_signal_repo
        self._dom_repo = decision_order_map_repo
        self._perf_writer = perf_writer

    async def handle_tradingview_signal(
        self,
        signal: TradingViewSignal,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        处理 TradingView 信号：去重 + 占位（RESERVED）。

        - 若重复信号：返回 {"status": "duplicate_ignored"}，不写 DecisionOrderMap。
        - 若首次信号：写 DedupSignal + DecisionOrderMap(RESERVED)，返回 accepted + decision_id + signal_id。

        Args:
            signal: 已解析的 TradingViewSignal
            config: 应用配置（需含 strategy.strategy_id）

        Returns:
            {"status": "accepted", "decision_id": str, "signal_id": str}
            或 {"status": "duplicate_ignored"}
        """
        t0 = time.perf_counter()
        received_at = datetime.now(timezone.utc)
        try:
            inserted = await self._dedup_repo.try_insert(
                signal_id=signal.signal_id,
                received_at=received_at,
                raw_payload=None,
            )
        except OperationalError as exc:
            # SQLite lock contention in concurrent duplicate submissions should not surface as 500.
            if "database is locked" in str(exc).lower():
                inserted = False
            else:
                raise
        if not inserted:
            if self._perf_writer:
                await self._perf_writer.write_once(
                    "signal_service",
                    "latency_ms",
                    (time.perf_counter() - t0) * 1000,
                    tags={"strategy_id": signal.strategy_id or ""},
                )
            return {"status": "duplicate_ignored"}

        # PR11：strategy_id 来自 payload（已在 Webhook 校验存在且启用）
        strategy_id = signal.strategy_id
        if not strategy_id:
            raise ValueError("strategy_id required")
        decision_id = generate_decision_id()
        created_at = datetime.now(timezone.utc)

        try:
            await self._dom_repo.create_reserved(
                decision_id=decision_id,
                signal_id=signal.signal_id,
                strategy_id=strategy_id,
                symbol=signal.symbol,
                side=signal.side,
                created_at=created_at,
            )
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            # Clear failed tx state to avoid PendingRollbackError in dependency commit.
            await self._dom_repo.session.rollback()
            if self._perf_writer:
                await self._perf_writer.write_once(
                    "signal_service",
                    "latency_ms",
                    (time.perf_counter() - t0) * 1000,
                    tags={"strategy_id": strategy_id},
                )
            return {"status": "duplicate_ignored"}
        if self._perf_writer:
            await self._perf_writer.write_once(
                "signal_service",
                "latency_ms",
                (time.perf_counter() - t0) * 1000,
                tags={"strategy_id": strategy_id},
            )
        return {
            "status": "accepted",
            "decision_id": decision_id,
            "signal_id": signal.signal_id,
        }
