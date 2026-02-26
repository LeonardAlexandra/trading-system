"""
PR15c：AccountManager 单元测试。
- exchange_adapter.get_account_info 正常时返回 AccountInfo
- exchange_adapter 失败时 fallback 到 balance_repo（若有）
"""
import pytest

from src.account.manager import AccountManager
from src.adapters.models import AccountInfo, AccountInfoError


@pytest.mark.asyncio
async def test_get_account_info_from_exchange_adapter():
    """exchange_adapter.get_account_info 正常时返回 AccountInfo。"""
    class MockAdapter:
        async def get_account_info(self):
            return AccountInfo(
                balances={"USDT": {"available": "1000", "total": "1000"}},
                equity=None,
            )

    manager = AccountManager(exchange_adapter=MockAdapter(), balance_repo=None)
    info = await manager.get_account_info()
    assert isinstance(info, AccountInfo)
    assert "USDT" in info.balances
    assert info.balances["USDT"].get("available") == "1000"


@pytest.mark.asyncio
async def test_get_account_info_fallback_to_balance_repo():
    """exchange_adapter 失败时从 balance_repo 组装 AccountInfo。"""
    class FailingAdapter:
        async def get_account_info(self):
            raise AccountInfoError("not implemented")

    class FakeBalanceRepo:
        async def list_all(self):
            from src.models.balance import Balance
            return [
                type("Row", (), {"asset": "USDT", "available": "500"})(),
            ]

    manager = AccountManager(exchange_adapter=FailingAdapter(), balance_repo=FakeBalanceRepo())
    info = await manager.get_account_info()
    assert isinstance(info, AccountInfo)
    assert "USDT" in info.balances
    assert info.balances["USDT"].get("available") == "500"


@pytest.mark.asyncio
async def test_get_account_info_no_fallback_raises():
    """exchange 失败且无 balance_repo 时抛 AccountInfoError。"""
    class FailingAdapter:
        async def get_account_info(self):
            raise AccountInfoError("unavailable")

    manager = AccountManager(exchange_adapter=FailingAdapter(), balance_repo=None)
    with pytest.raises(AccountInfoError) as exc_info:
        await manager.get_account_info()
    assert "not available" in str(exc_info.value).lower() or "balance_repo" in str(exc_info.value).lower()
