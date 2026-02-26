"""
风控模块（PR6 接口 + PR9 最小规则集；PR15c 可开关余额/总敞口检查；Phase1.1 C4 全量检查）
"""
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.position_repository import PositionRepository
from src.repositories.risk_state_repository import RiskStateRepository
from src.execution.risk_config import RiskConfig
from src.common.reason_codes import (
    COOLDOWN_ACTIVE,
    DUPLICATE_DIRECTION,
    POSITION_LIMIT_EXCEEDED,
    ORDER_SIZE_EXCEEDED,
    INSUFFICIENT_BALANCE,
    TOTAL_EXPOSURE_EXCEEDED,
)


class RiskManager:
    """
    PR9：4 条规则按顺序执行，命中即拒绝。
    PR15c：可注入 account_manager、market_data_adapter；enable_balance_checks/enable_total_exposure_checks 默认关闭。
    """

    def __init__(
        self,
        position_repo: Optional[PositionRepository] = None,
        dom_repo: Optional[DecisionOrderMapRepository] = None,
        risk_state_repo: Optional[RiskStateRepository] = None,
        risk_config: Optional[RiskConfig] = None,
        *,
        account_manager: Optional[Any] = None,
        market_data_adapter: Optional[Any] = None,
    ):
        self._position_repo = position_repo
        self._dom_repo = dom_repo
        self._risk_state_repo = risk_state_repo
        self._config = risk_config or RiskConfig()
        self._account_manager = account_manager
        self._market_data_adapter = market_data_adapter

    async def check(self, decision: Any, risk_config_override: Optional[RiskConfig] = None) -> Dict[str, Any]:
        """
        执行前置风控检查（4 条规则按序，命中即拒绝）。
        PR11：risk_config_override 为策略级风控配置，未传则用实例默认 _config（按 strategy_id 隔离）。
        Returns:
            {"allowed": bool, "reason_code": str | None, "message": str | None}
        """
        config = risk_config_override if risk_config_override is not None else self._config
        strategy_id = (getattr(decision, "strategy_id", None) or "") or ""
        symbol = (getattr(decision, "symbol", None) or "") or ""
        side = (getattr(decision, "side", None) or "") or ""
        qty = decision.quantity if getattr(decision, "quantity", None) is not None else Decimal("1")
        if not isinstance(qty, Decimal):
            qty = Decimal(str(qty))
        now = datetime.now(timezone.utc)

        # 1) 冷却时间。策略：成交后 cooldown（last_allowed_at 仅在 ExecutionEngine FILLED 后写入，见 RiskStateRepository）
        if config.cooldown_seconds > 0 and self._risk_state_repo:
            rs = await self._risk_state_repo.get(strategy_id, symbol, side)
            if rs and rs.last_allowed_at:
                last = rs.last_allowed_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                elapsed = (now - last).total_seconds()
                if elapsed < config.cooldown_seconds:
                    return {
                        "allowed": False,
                        "reason_code": COOLDOWN_ACTIVE,
                        "message": f"cooldown_seconds={config.cooldown_seconds} not elapsed",
                    }

        # 2) 同向重复抑制
        if config.same_direction_dedupe_window_seconds > 0 and self._dom_repo:
            since = now - timedelta(seconds=config.same_direction_dedupe_window_seconds)
            current_decision_id = getattr(decision, "decision_id", None) or ""
            exists = await self._dom_repo.exists_recent_filled_or_submitting(
                strategy_id, symbol, side, since, exclude_decision_id=current_decision_id
            )
            if exists:
                return {
                    "allowed": False,
                    "reason_code": DUPLICATE_DIRECTION,
                    "message": "same direction within dedupe window",
                }

        # 3) 最大仓位限制（PR11：按 strategy_id 查仓位，隔离策略）
        if config.max_position_qty is not None and self._position_repo:
            pos = await self._position_repo.get(strategy_id, symbol)
            current = (pos.quantity if pos else Decimal("0")) or Decimal("0")
            if current + qty > config.max_position_qty:
                return {
                    "allowed": False,
                    "reason_code": POSITION_LIMIT_EXCEEDED,
                    "message": f"position would exceed max_position_qty={config.max_position_qty}",
                }

        # 4) 单笔最大下单量
        if config.max_order_qty is not None and qty > config.max_order_qty:
            return {
                "allowed": False,
                "reason_code": ORDER_SIZE_EXCEEDED,
                "message": f"order qty {qty} exceeds max_order_qty={config.max_order_qty}",
            }

        # 5) PR15c：余额检查（仅 BUY 且 enable_balance_checks=true）
        if getattr(config, "enable_balance_checks", False) and (side or "").upper() == "BUY":
            if self._account_manager and self._market_data_adapter:
                try:
                    market_data = await self._market_data_adapter.get_market_data(symbol)
                    last_price = float(getattr(market_data, "last_price", 0) or 0)
                    if last_price <= 0:
                        return {
                            "allowed": False,
                            "reason_code": INSUFFICIENT_BALANCE,
                            "message": "market price unavailable for balance check",
                        }
                    notional = float(qty) * last_price
                    account_info = await self._account_manager.get_account_info()
                    quote_asset = getattr(config, "quote_asset_for_balance", "USDT") or "USDT"
                    bal = (account_info.balances or {}).get(quote_asset) or {}
                    available_raw = bal.get("available") or bal.get("total") or "0"
                    try:
                        available = float(available_raw)
                    except (TypeError, ValueError):
                        available = 0.0
                    if notional > available:
                        return {
                            "allowed": False,
                            "reason_code": INSUFFICIENT_BALANCE,
                            "message": f"insufficient balance: notional {notional} > available {available} {quote_asset}",
                        }
                except Exception as e:
                    return {
                        "allowed": False,
                        "reason_code": INSUFFICIENT_BALANCE,
                        "message": f"balance check failed: {e}",
                    }

        # 6) PR15c：总敞口检查（enable_total_exposure_checks=true）
        if getattr(config, "enable_total_exposure_checks", False) and self._position_repo and self._market_data_adapter and self._account_manager:
            max_ratio = getattr(config, "max_exposure_ratio", None)
            if max_ratio is not None and max_ratio > 0:
                try:
                    account_info = await self._account_manager.get_account_info()
                    equity_raw = getattr(account_info, "equity", None)
                    if equity_raw is not None:
                        try:
                            equity = float(equity_raw)
                        except (TypeError, ValueError):
                            equity = 0.0
                    else:
                        equity = 0.0
                        for _asset, b in (account_info.balances or {}).items():
                            try:
                                equity += float(b.get("total") or b.get("available") or 0)
                            except (TypeError, ValueError):
                                pass
                    if equity <= 0:
                        pass  # 无权益则不限制
                    else:
                        pos = await self._position_repo.get(strategy_id, symbol)
                        current_qty = (pos.quantity if pos else Decimal("0")) or Decimal("0")
                        try:
                            md = await self._market_data_adapter.get_market_data(symbol)
                            last_price = float(getattr(md, "last_price", 0) or 0)
                        except Exception:
                            last_price = 0.0
                        exposure = float(current_qty) * last_price
                        if exposure > equity * max_ratio:
                            return {
                                "allowed": False,
                                "reason_code": TOTAL_EXPOSURE_EXCEEDED,
                                "message": f"total exposure {exposure} > equity*ratio {equity * max_ratio}",
                            }
                except Exception:
                    pass  # 敞口检查失败时不阻塞（保守：仅明确超限时拒单）

        return {"allowed": True, "reason_code": None, "message": None}

    async def full_check(
        self,
        strategy_id: str,
        positions: List[Any],
        risk_config_override: Optional[RiskConfig] = None,
    ) -> Dict[str, Any]:
        """
        Phase1.1 C4：对账/EXTERNAL_SYNC 同步后的全量风控检查。
        C4-02 工程硬约束：持仓数据由调用方传入（position_manager 从同一事务 position_repo 读取的同步后最新数据），
        本方法不再从 self._position_repo 读取，避免隐含“同 session”前提。
        规则与 check() 一致（C4-04）。Returns: {"passed": bool, "reason_code": str | None, "message": str | None}
        """
        config = risk_config_override if risk_config_override is not None else self._config

        # 仓位限制：对传入的 positions 逐条校验，与 check() 规则一致（C4-04）
        if config.max_position_qty is not None:
            for pos in positions or []:
                qty = (getattr(pos, "quantity", None) or Decimal("0")) if pos else Decimal("0")
                if not isinstance(qty, Decimal):
                    qty = Decimal(str(qty))
                if qty > config.max_position_qty:
                    symbol = getattr(pos, "symbol", "") or ""
                    return {
                        "passed": False,
                        "reason_code": POSITION_LIMIT_EXCEEDED,
                        "message": f"strategy_id={strategy_id} symbol={symbol} position {qty} exceeds max_position_qty={config.max_position_qty}",
                    }

        # PR15c：总敞口检查（全量：传入的 positions 敞口之和 vs 权益比例）
        if getattr(config, "enable_total_exposure_checks", False) and self._market_data_adapter and self._account_manager:
            max_ratio = getattr(config, "max_exposure_ratio", None)
            if max_ratio is not None and max_ratio > 0 and positions:
                try:
                    account_info = await self._account_manager.get_account_info()
                    equity_raw = getattr(account_info, "equity", None)
                    if equity_raw is not None:
                        try:
                            equity = float(equity_raw)
                        except (TypeError, ValueError):
                            equity = 0.0
                    else:
                        equity = 0.0
                        for _asset, b in (account_info.balances or {}).items():
                            try:
                                equity += float(b.get("total") or b.get("available") or 0)
                            except (TypeError, ValueError):
                                pass
                    if equity > 0:
                        total_exposure = 0.0
                        for pos in positions:
                            qty = float((getattr(pos, "quantity", None) or Decimal("0")) or Decimal("0")) if pos else 0.0
                            symbol = getattr(pos, "symbol", "") or ""
                            try:
                                md = await self._market_data_adapter.get_market_data(symbol)
                                last_price = float(getattr(md, "last_price", 0) or 0)
                            except Exception:
                                last_price = 0.0
                            total_exposure += qty * last_price
                        if total_exposure > equity * max_ratio:
                            return {
                                "passed": False,
                                "reason_code": TOTAL_EXPOSURE_EXCEEDED,
                                "message": f"strategy_id={strategy_id} total_exposure={total_exposure} > equity*ratio={equity * max_ratio}",
                            }
                except Exception:
                    pass

        return {"passed": True, "reason_code": None, "message": None}
