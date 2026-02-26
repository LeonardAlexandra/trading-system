"""
SignalApplicationService 单元测试（mock Repository）
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from src.application.signal_service import SignalApplicationService, generate_decision_id
from src.schemas.signals import TradingViewSignal


@pytest.fixture
def signal():
    return TradingViewSignal(
        signal_id="sig-001",
        strategy_id="MOCK_STRATEGY_V1",
        symbol="BTCUSDT",
        side="BUY",
        timestamp=datetime.now(timezone.utc),
        raw_payload={"symbol": "BTCUSDT", "action": "BUY"},
        source="tradingview",
    )


@pytest.fixture
def config():
    return {"strategy": {"strategy_id": "MOCK_STRATEGY_V1"}}


@pytest.mark.asyncio
async def test_first_signal_returns_accepted_with_decision_id(signal, config):
    """首次信号 -> accepted + decision_id + signal_id"""
    dedup_repo = AsyncMock()
    dedup_repo.try_insert = AsyncMock(return_value=True)
    dom_repo = AsyncMock()
    dom_repo.create_reserved = AsyncMock(return_value=None)

    service = SignalApplicationService(dedup_repo, dom_repo)
    result = await service.handle_tradingview_signal(signal, config)

    assert result["status"] == "accepted"
    assert "decision_id" in result
    assert result["signal_id"] == signal.signal_id
    dedup_repo.try_insert.assert_called_once()
    dom_repo.create_reserved.assert_called_once()
    call_kw = dom_repo.create_reserved.call_args[1]
    assert call_kw["signal_id"] == signal.signal_id
    assert call_kw["strategy_id"] == signal.strategy_id
    assert call_kw["symbol"] == signal.symbol
    assert call_kw["side"] == signal.side


@pytest.mark.asyncio
async def test_duplicate_signal_returns_duplicate_ignored(signal, config):
    """重复信号 -> duplicate_ignored，不写 DecisionOrderMap"""
    dedup_repo = AsyncMock()
    dedup_repo.try_insert = AsyncMock(return_value=False)
    dom_repo = AsyncMock()
    dom_repo.create_reserved = AsyncMock()

    service = SignalApplicationService(dedup_repo, dom_repo)
    result = await service.handle_tradingview_signal(signal, config)

    assert result == {"status": "duplicate_ignored"}
    dedup_repo.try_insert.assert_called_once()
    dom_repo.create_reserved.assert_not_called()


@pytest.mark.asyncio
async def test_generate_decision_id_unique():
    """decision_id 集中生成且唯一"""
    ids = {generate_decision_id() for _ in range(100)}
    assert len(ids) == 100
