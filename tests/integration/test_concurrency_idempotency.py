"""
并发/高频场景下的幂等性测试（Phase1.0 封版补强）

验证关键不变量在并发场景下的保持：
- INV-1: 同一 signal_id 只能产生一次有效下单
- INV-3: 同一 decision_id 只能产生一次有效下单
- INV-9: 风控拒绝的决策不得下单
"""
import asyncio
import base64
import hashlib
import hmac
import json
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from unittest.mock import AsyncMock, MagicMock

from src.app.main import create_app
from src.adapters.tradingview_adapter import TradingViewAdapter
from src.database.connection import Base
from src.app.dependencies import get_db_session, set_session_factory
from src.repositories.dedup_signal_repo import DedupSignalRepository
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.application.signal_service import SignalApplicationService
from src.schemas.signals import TradingViewSignal
from src.common.event_types import RISK_REJECTED, ORDER_REJECTED, ORDER_SUBMIT_OK
import src.models

# 与 fixture 中 monkeypatch 一致
TEST_WEBHOOK_SECRET = "test_webhook_secret"


def _make_signature(secret: str, payload_bytes: bytes) -> str:
    """使用与 TradingViewAdapter 相同的算法生成签名"""
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    ).decode("utf-8")


@pytest.fixture
def app(monkeypatch, tmp_path):
    """创建测试应用"""
    monkeypatch.setenv("TV_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("STRATEGY_ID", "TEST_STRATEGY_V1")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    tmp_db_path = (tmp_path / "test_concurrency.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + tmp_db_path)
    # 创建表结构
    sync_engine = create_engine("sqlite:///" + tmp_db_path)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    return create_app()


@pytest.fixture
def client(app):
    """创建测试客户端"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def db_session_factory(tmp_path):
    """创建数据库 SessionFactory"""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    
    tmp_db_path = (tmp_path / "test_concurrency_async.db").as_posix()
    database_url = "sqlite+aiosqlite:///" + tmp_db_path
    
    # 创建同步引擎先建表
    sync_engine = create_engine("sqlite:///" + tmp_db_path)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    
    # 创建异步引擎和 SessionFactory
    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)
    
    yield session_factory
    
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_signal_id_deduplication(client):
    """
    场景1：同一 signal_id 并发提交 N 次（10 次），断言只有 1 次产生有效决策/下单，其余为 duplicate_ignored
    
    验证 INV-1: 同一 signal_id 只能产生一次有效下单
    """
    # 准备相同的 payload（确保 signal_id 一致）
    payload = {
        "signal_id": "test-concurrent-signal-001",  # 固定 signal_id
        "symbol": "BTCUSDT",
        "action": "BUY",
        "side": "BUY",
        "timestamp": "2026-02-03T10:00:00Z",
        "indicator_name": "TEST",
        "strategy_id": "TEST_STRATEGY_V1",
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _make_signature(TEST_WEBHOOK_SECRET, payload_bytes)
    
    headers = {
        "Content-Type": "application/json",
        "X-TradingView-Signature": signature,
    }
    
    # 并发提交 10 次（使用线程池执行同步 HTTP 请求）
    import concurrent.futures
    
    def send_webhook():
        response = client.post(
            "/webhook/tradingview",
            content=payload_bytes,
            headers=headers,
        )
        return response.status_code, response.json()
    
    # 使用线程池并发执行
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(send_webhook) for _ in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    # 验证结果
    accepted_count = 0
    duplicate_count = 0
    decision_ids = set()
    
    for status_code, data in results:
        assert status_code == 200, f"Expected 200, got {status_code}: {data}"
        
        if data.get("status") == "accepted":
            accepted_count += 1
            decision_ids.add(data.get("decision_id"))
        elif data.get("status") == "duplicate_ignored":
            duplicate_count += 1
    
    # 断言：只有 1 次 accepted，其余 9 次为 duplicate_ignored
    assert accepted_count == 1, f"Expected 1 accepted, got {accepted_count}. Results: {results}"
    assert duplicate_count == 9, f"Expected 9 duplicates, got {duplicate_count}. Results: {results}"
    assert len(decision_ids) == 1, f"Expected 1 unique decision_id, got {len(decision_ids)}: {decision_ids}"
    
    # 验证数据库：只有 1 条 DedupSignal 记录（signal_id 由 parse_signal 按语义字段哈希得到，与 payload["signal_id"] 不同）
    parsed_signal = TradingViewAdapter.parse_signal(payload_bytes)
    from src.app.dependencies import get_db_session
    async with get_db_session() as session:
        dedup_repo = DedupSignalRepository(session)
        # 通过查询验证（try_insert 会返回 False 如果已存在）；使用与 Webhook 一致的 signal_id（parse_signal 的哈希）
        inserted = await dedup_repo.try_insert(
            signal_id=parsed_signal.signal_id,
            received_at=datetime.now(timezone.utc),
            raw_payload=None,
        )
        assert not inserted, "Signal should already exist in database"


@pytest.mark.asyncio
async def test_concurrent_decision_id_execution(db_session_factory, tmp_path):
    """
    场景2：同一 decision_id/同一 RESERVED 决策被并发执行，断言只有 1 次 claim 成功，其余幂等返回，不会重复下单
    
    验证 INV-3: 同一 decision_id 只能产生一次有效下单
    验证 try_claim_reserved 的原子性
    """
    decision_id = "test-concurrent-decision-001"
    signal_id = "test-concurrent-signal-002"
    
    # 预置 RESERVED 决策
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="TEST_STRATEGY_V1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=datetime.now(timezone.utc),
            quantity=Decimal("1"),
        )
    
    # Mock ExchangeAdapter 以验证下单调用次数（共享 mock 对象）
    mock_exchange = MagicMock(spec=PaperExchangeAdapter)
    mock_order = MagicMock(
        order_id="mock-order-001",
        exchange_order_id="ex-order-001",
        status="FILLED",
        filled_quantity=Decimal("1"),
        average_price=Decimal("50000"),
    )
    mock_exchange.create_order = AsyncMock(return_value=mock_order)
    
    # 并发执行 10 次（每个任务使用独立的 session，但共享 mock_exchange）
    async def execute_decision():
        async with get_db_session() as session:
            dom_repo = DecisionOrderMapRepository(session)
            risk_manager = RiskManager()
            engine = ExecutionEngine(
                dom_repo=dom_repo,
                exchange_adapter=mock_exchange,  # 共享 mock 对象
                risk_manager=risk_manager,
            )
            return await engine.execute_one(decision_id)
    
    tasks = [execute_decision() for _ in range(10)]
    results = await asyncio.gather(*tasks)
    
    # 验证结果
    filled_count = 0
    skipped_count = 0
    
    for result in results:
        status = result.get("status")
        if status == "filled":
            filled_count += 1
        elif status == "skipped":
            skipped_count += 1
            assert result.get("reason_code") == "SKIPPED_ALREADY_CLAIMED"
    
    # 断言：只有 1 次 filled，其余 9 次为 skipped
    assert filled_count == 1, f"Expected 1 filled, got {filled_count}. Results: {results}"
    assert skipped_count == 9, f"Expected 9 skipped, got {skipped_count}. Results: {results}"
    
    # 验证 ExchangeAdapter.create_order 只被调用 1 次
    assert mock_exchange.create_order.call_count == 1, f"Expected 1 call to create_order, got {mock_exchange.create_order.call_count}"
    
    # 验证数据库：只有 1 条 FILLED 记录
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        decision = await dom_repo.get_by_decision_id(decision_id)
        assert decision is not None
        assert decision.status == "FILLED"
        assert decision.local_order_id is not None


@pytest.mark.asyncio
async def test_concurrent_risk_rejection_no_order(db_session_factory, tmp_path):
    """
    场景3：并发下风控拒绝仍不得触发 ExchangeAdapter.create_order
    
    验证 INV-9: 风控拒绝的决策不得下单
    """
    decision_id = "test-concurrent-risk-reject-001"
    signal_id = "test-concurrent-signal-003"
    
    # 预置 RESERVED 决策（使用超大数量以触发风控拒绝）
    async with get_db_session() as session:
        dom_repo = DecisionOrderMapRepository(session)
        await dom_repo.create_reserved(
            decision_id=decision_id,
            signal_id=signal_id,
            strategy_id="TEST_STRATEGY_V1",
            symbol="BTCUSDT",
            side="BUY",
            created_at=datetime.now(timezone.utc),
            quantity=Decimal("1000"),  # 超大数量，触发单笔限制
        )
    
    # Mock ExchangeAdapter 以验证下单调用次数（应该为 0，共享 mock 对象）
    mock_exchange = MagicMock(spec=PaperExchangeAdapter)
    mock_exchange.create_order = AsyncMock()
    
    # 创建 RiskManager（配置单笔最大限制为 10）
    from src.execution.risk_config import RiskConfig
    risk_config = RiskConfig(max_order_qty=Decimal("10"))  # 限制单笔最大为 10
    
    # 并发执行 10 次（每个任务使用独立的 session，但共享 mock_exchange）
    async def execute_decision():
        async with get_db_session() as session:
            dom_repo = DecisionOrderMapRepository(session)
            risk_manager = RiskManager(risk_config=risk_config)
            engine = ExecutionEngine(
                dom_repo=dom_repo,
                exchange_adapter=mock_exchange,  # 共享 mock 对象
                risk_manager=risk_manager,
            )
            return await engine.execute_one(decision_id)
    
    tasks = [execute_decision() for _ in range(10)]
    results = await asyncio.gather(*tasks)
    
    # 验证结果：所有执行都应该被风控拒绝
    rejected_count = 0
    failed_count = 0
    skipped_count = 0

    for result in results:
        status = result.get("status")
        reason_code = result.get("reason_code")

        if status == "failed" and reason_code == "ORDER_SIZE_EXCEEDED":
            rejected_count += 1
        elif status == "failed":
            failed_count += 1
        elif status == "skipped":
            skipped_count += 1

    # 断言：共 10 次执行；1 次抢到并风控拒绝，其余 9 次 skipped（未下单）；不要求全部为 rejected/failed
    assert rejected_count + failed_count + skipped_count == 10, f"Expected 10 total, got rejected={rejected_count}, failed={failed_count}, skipped={skipped_count}. Results: {results}"
    assert rejected_count >= 1, f"Expected at least 1 risk rejection, got rejected={rejected_count}. Results: {results}"
    
    # 验证 ExchangeAdapter.create_order 从未被调用
    assert mock_exchange.create_order.call_count == 0, f"Expected 0 calls to create_order, got {mock_exchange.create_order.call_count}"
    
    # 验证 execution_events：应该有 RISK_REJECTED 事件，但无 ORDER_SUBMIT_OK
    async with get_db_session() as session:
        event_repo = ExecutionEventRepository(session)
        events = await event_repo.list_by_decision_id(decision_id)
        event_types = [e.event_type for e in events]
        
        # 应该有 RISK_REJECTED 或 ORDER_REJECTED 事件
        assert RISK_REJECTED in event_types or ORDER_REJECTED in event_types, f"Expected RISK_REJECTED/ORDER_REJECTED event, got: {event_types}"
        
        # 不应该有 ORDER_SUBMIT_OK 事件
        assert ORDER_SUBMIT_OK not in event_types, f"Should not have ORDER_SUBMIT_OK event, got: {event_types}"


@pytest.mark.asyncio
async def test_concurrent_signal_service_idempotency(db_session_factory, tmp_path):
    """
    场景4：并发调用 SignalApplicationService.handle_tradingview_signal，验证去重和决策创建的幂等性
    """
    signal_id = "test-concurrent-service-001"
    
    # 创建信号
    signal = TradingViewSignal(
        signal_id=signal_id,
        symbol="BTCUSDT",
        side="BUY",
        strategy_id="TEST_STRATEGY_V1",
        timestamp=datetime.now(timezone.utc),
        raw_payload={},
    )
    
    config = {"strategy": {"strategy_id": "TEST_STRATEGY_V1"}}
    
    # 并发调用 10 次
    async def handle_signal():
        async with get_db_session() as session:
            dedup_repo = DedupSignalRepository(session)
            dom_repo = DecisionOrderMapRepository(session)
            service = SignalApplicationService(dedup_repo, dom_repo)
            return await service.handle_tradingview_signal(signal, config)
    
    tasks = [handle_signal() for _ in range(10)]
    results = await asyncio.gather(*tasks)
    
    # 验证结果
    accepted_count = 0
    duplicate_count = 0
    decision_ids = set()
    
    for result in results:
        if result.get("status") == "accepted":
            accepted_count += 1
            decision_ids.add(result.get("decision_id"))
        elif result.get("status") == "duplicate_ignored":
            duplicate_count += 1
    
    # 断言：只有 1 次 accepted，其余 9 次为 duplicate_ignored
    assert accepted_count == 1, f"Expected 1 accepted, got {accepted_count}. Results: {results}"
    assert duplicate_count == 9, f"Expected 9 duplicates, got {duplicate_count}. Results: {results}"
    assert len(decision_ids) == 1, f"Expected 1 unique decision_id, got {len(decision_ids)}: {decision_ids}"
    
    # 验证数据库：只有 1 条 DedupSignal 和 1 条 DecisionOrderMap 记录
    async with get_db_session() as session:
        dedup_repo = DedupSignalRepository(session)
        dom_repo = DecisionOrderMapRepository(session)
        
        # 验证 DedupSignal
        inserted = await dedup_repo.try_insert(
            signal_id=signal_id,
            received_at=datetime.now(timezone.utc),
            raw_payload=None,
        )
        assert not inserted, "Signal should already exist"
        
        # 验证 DecisionOrderMap（应该只有 1 条 RESERVED 记录）
        decision = await dom_repo.get_by_decision_id(list(decision_ids)[0])
        assert decision is not None
        assert decision.status == "RESERVED"
        assert decision.signal_id == signal_id
