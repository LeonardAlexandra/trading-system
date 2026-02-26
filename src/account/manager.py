"""
PR9/PR15c：账户管理器（Phase1.0 遗漏接口补齐）
通过 ExchangeAdapter.get_account_info 或 balance_repo fallback 提供 AccountInfo，供风控使用。
"""
from decimal import Decimal
from typing import Any, Optional

from src.adapters.models import AccountInfo, AccountInfoError


class AccountManager:
    """
    PR9：获取账户信息（余额等），供风控使用。
    优先走 exchange_adapter.get_account_info()；若无实现或失败则从 balance_repo 组装 AccountInfo。
    """

    def __init__(
        self,
        exchange_adapter: Any,
        balance_repo: Optional[Any] = None,
    ):
        self._exchange_adapter = exchange_adapter
        self._balance_repo = balance_repo

    async def get_account_info(self) -> AccountInfo:
        """
        获取账户信息。优先交易所适配器；失败或无实现时从 balance_repo 读取并组装。
        异常统一封装为 AccountInfoError。
        """
        try:
            return await self._exchange_adapter.get_account_info()
        except Exception:
            pass
        # Fallback: 从 balance_repo 组装（交易所未实现或失败时）
        if self._balance_repo is None:
            raise AccountInfoError("get_account_info not available and no balance_repo")
        try:
            rows = await self._balance_repo.list_all()
        except Exception as e:
            raise AccountInfoError(f"balance_repo list_all failed: {e}") from e
        balances: dict[str, dict[str, Any]] = {}
        for row in rows:
            asset = getattr(row, "asset", None) or ""
            if not asset:
                continue
            avail = getattr(row, "available", None)
            if avail is None:
                avail = Decimal("0")
            if not isinstance(avail, (str, int, float, Decimal)):
                avail = Decimal("0")
            try:
                avail_decimal = Decimal(str(avail))
            except Exception:
                avail_decimal = Decimal("0")
            balances[asset] = {"available": str(avail_decimal), "total": str(avail_decimal)}
        return AccountInfo(balances=balances, equity=None)
