"""
Phase1.1 C3：PositionManager.reconcile → EXTERNAL_SYNC（含定价优先级）
Phase1.1 C4：对账/同步完成后调用 RiskManager 全量检查，不通过时与 C5 衔接。

对账结果以 EXTERNAL_SYNC trade 落库，更新 position_snapshot（positions 表），写 position_reconcile_log。
定价优先级（写死）：交易所价 > 本地参考价 > 兜底价；档位在日志中可追溯。
reconcile 写路径持 ReconcileLock，锁内仅 DB 写；trade + position + log 同一事务。
同步完成后（锁外、同一事务内）执行 full_check，使用同步后最新数据；不通过时调用 on_risk_check_failed 与 C5 衔接。
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.trade import Trade, SOURCE_TYPE_EXTERNAL_SYNC
from src.models.position_reconcile_log import SYNC_TRADE
from src.repositories.trade_repo import TradeRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.position_reconcile_log_repo import PositionReconcileLogRepository
from src.locks.reconcile_lock import ReconcileLock

logger = logging.getLogger(__name__)

# C3-04/C3-05：定价档位枚举，用于日志可追溯
PRICE_TIER_EXCHANGE = "EXCHANGE"
PRICE_TIER_LOCAL_REF = "LOCAL_REF"
PRICE_TIER_FALLBACK = "FALLBACK"


@dataclass
class ReconcileItem:
    """
    单条待同步的对账项（由调用方在锁外准备）。
    external_trade_id 必填；定价三档可选，按优先级选用。
    """
    external_trade_id: str
    symbol: str
    side: str  # "BUY" | "SELL"
    quantity: Decimal
    exchange_price: Optional[Decimal] = None   # 第一优先：交易所成交价/结算价
    local_ref_price: Optional[Decimal] = None   # 第二优先：本地参考价
    fallback_price: Optional[Decimal] = None    # 第三优先：兜底价（无则必须由调用方保证）


def resolve_price_and_tier(item: ReconcileItem) -> Tuple[Decimal, str]:
    """
    C3-04：定价优先级写死 —— 交易所价 > 本地参考价 > 兜底价。
    返回 (price, tier) 供落库与日志可追溯（C3-05）。
    """
    if item.exchange_price is not None:
        return (item.exchange_price, PRICE_TIER_EXCHANGE)
    if item.local_ref_price is not None:
        return (item.local_ref_price, PRICE_TIER_LOCAL_REF)
    if item.fallback_price is not None:
        return (item.fallback_price, PRICE_TIER_FALLBACK)
    raise ValueError(
        "ReconcileItem must have at least one of exchange_price, local_ref_price, fallback_price"
    )


class ReconcileLockNotAcquiredError(Exception):
    """C3-06：reconcile 写路径必须持锁；acquire 失败时抛出（或返回结构化结果，此处用异常）。"""
    pass


class PositionManager:
    """
    Phase1.1 C3：对账入口。
    不持有 session 生命周期；调用方传入 session，reconcile 内用同一 session 做锁内事务写。
    """

    def __init__(
        self,
        trade_repo: TradeRepository,
        position_repo: PositionRepository,
        reconcile_log_repo: PositionReconcileLogRepository,
    ):
        self._trade_repo = trade_repo
        self._position_repo = position_repo
        self._reconcile_log_repo = reconcile_log_repo

    async def reconcile(
        self,
        session: AsyncSession,
        strategy_id: str,
        items: List[ReconcileItem],
        *,
        lock_holder_id: str = "position-manager-reconcile",
        max_acquire_retries: int = 2,
        retry_interval_seconds: float = 0.1,
        risk_manager: Any,
        risk_config_override: Optional[Any] = None,
        on_risk_check_failed: Optional[Callable[[str, str, str], Awaitable[None]]] = None,
    ) -> dict:
        """
        C3：对需同步的差异生成 EXTERNAL_SYNC trade、更新 position_snapshot、写 position_reconcile_log。
        锁外准备：调用方已提供 items（含定价三档）；此处锁外仅做定价与档位解析。
        锁内：同一事务内写 trade、更新 position、写 reconcile_log；禁止外部 I/O。
        C4-01：risk_manager 必填，不得跳过 full_check；None 时显式失败。
        C4-02：同步后从本 session 的 position_repo 读取 positions 传入 full_check，保证“同步后最新数据”。
        """
        if risk_manager is None:
            raise ValueError(
                "C4-01: risk_manager is required for reconcile; full_check must not be skipped. "
                "Pass a RiskManager instance."
            )

        # ---------- 锁外准备（禁止放锁内）：计算定价与档位 ----------
        resolved: List[Tuple[ReconcileItem, Decimal, str]] = []
        for item in items:
            price, tier = resolve_price_and_tier(item)
            resolved.append((item, price, tier))

        # ---------- 持锁 + 同一事务内写入 ----------
        lock = ReconcileLock(
            session,
            lock_holder_id,
            max_acquire_retries=max_acquire_retries,
            retry_interval_seconds=retry_interval_seconds,
        )
        synced = 0
        skipped_idempotent = 0

        async with lock.use_lock(strategy_id) as acquired:
            if not acquired:
                logger.warning("reconcile lock not acquired strategy_id=%s", strategy_id)
                raise ReconcileLockNotAcquiredError(
                    f"ReconcileLock not acquired for strategy_id={strategy_id}"
                )

            # 锁内仅 DB 写（C3-06）；事务边界由 session 管理，调用方须在 begin() 内调用本方法
            if not session.in_transaction():
                raise RuntimeError(
                    "PositionManager.reconcile must be called inside an active transaction "
                    "(e.g. async with session.begin()) so that trade + position_snapshot + "
                    "position_reconcile_log are in the same consistency boundary."
                )

            for item, price, tier in resolved:
                # 幂等优化：先查再写（仅优化，最终幂等由 UNIQUE 冲突兜底）
                existing = await self._trade_repo.get_by_strategy_external_trade_id(
                    strategy_id, item.external_trade_id
                )
                if existing is not None:
                    skipped_idempotent += 1
                    logger.info(
                        "reconcile idempotent skip strategy_id=%s external_trade_id=%s",
                        strategy_id, item.external_trade_id,
                    )
                    continue

                # 单条 item 用 savepoint，IntegrityError 时仅回滚本条，外事务仍有效以便 release 锁
                try:
                    async with session.begin_nested():
                        # C3-01：写入 EXTERNAL_SYNC trade（A2）；UNIQUE 冲突由 DB 兜底
                        trade_id = f"EXTSYNC:{strategy_id}:{item.external_trade_id}"
                        trade = Trade(
                            trade_id=trade_id,
                            strategy_id=strategy_id,
                            source_type=SOURCE_TYPE_EXTERNAL_SYNC,
                            external_trade_id=item.external_trade_id,
                            symbol=item.symbol,
                            side=item.side,
                            quantity=item.quantity,
                            price=price,
                            slippage=Decimal("0"),
                            realized_pnl=Decimal("0"),
                            executed_at=datetime.now(timezone.utc),
                            is_simulated=False,
                        )
                        await self._trade_repo.create(trade)
                        # C3-02：更新 position_snapshot（本地 positions 表为真理源）
                        await self._position_repo.upsert(
                            strategy_id,
                            item.symbol,
                            item.quantity,
                            side="LONG" if item.side == "BUY" else "SHORT",
                            avg_price=price,
                        )
                        # C3-03：写 position_reconcile_log（A3）event_type=SYNC_TRADE, external_trade_id, price_tier 落盘
                        await self._reconcile_log_repo.log_event_in_txn(
                            strategy_id=strategy_id,
                            event_type=SYNC_TRADE,
                            external_trade_id=item.external_trade_id,
                            price_tier=tier,
                        )
                        logger.info(
                            "reconcile sync_trade strategy_id=%s external_trade_id=%s symbol=%s side=%s "
                            "quantity=%s price=%s price_tier=%s",
                            strategy_id, item.external_trade_id, item.symbol, item.side,
                            item.quantity, price, tier,
                        )
                        synced += 1
                except IntegrityError:
                    # 幂等 DB 兜底：UNIQUE(strategy_id, external_trade_id) 冲突视为成功，不使 reconcile 整体失败
                    skipped_idempotent += 1
                    logger.info(
                        "reconcile idempotent skip (unique conflict) strategy_id=%s external_trade_id=%s",
                        strategy_id, item.external_trade_id,
                    )
                    continue

        # ---------- C4：同步完成后全量风控检查（锁已释放，仍同一事务）；C4-02 从本 session 读取后传入 ----------
        positions_sync_after = await self._position_repo.get_all_by_strategy(strategy_id)
        logger.info("reconcile post_sync full_check trigger strategy_id=%s", strategy_id)
        try:
            result = await risk_manager.full_check(strategy_id, positions_sync_after, risk_config_override)
        except Exception:
            logger.exception("reconcile post_sync full_check failed strategy_id=%s", strategy_id)
            raise
        risk_check_passed = result.get("passed", True)
        risk_reason_code = result.get("reason_code")
        risk_message = result.get("message")
        _msg_summary = (risk_message or "")[:200]
        logger.info(
            "reconcile post_sync full_check strategy_id=%s passed=%s reason_code=%s message=%s",
            strategy_id, risk_check_passed, risk_reason_code, _msg_summary,
        )
        if not risk_check_passed and on_risk_check_failed is not None:
            await on_risk_check_failed(strategy_id, risk_reason_code or "", risk_message or "")

        return {
            "ok": True,
            "synced": synced,
            "skipped_idempotent": skipped_idempotent,
            "risk_check_passed": risk_check_passed,
            "risk_reason_code": risk_reason_code,
            "risk_message": risk_message,
        }
