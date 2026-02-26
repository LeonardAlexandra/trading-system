"""
Phase2.0 D7：技术债专项修复 — TRACE 集成测试
验证：
1. 构造 FAILED decision（无 execution）
2. 调用 Trace API 返回 200 及详细失败原因
3. trace_status = FAILED，missing_nodes 含 execution/trade
4. 验证只读边界：数据库行数未变化
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from datetime import datetime, timezone

from src.app.main import create_app
from src.app.dependencies import get_db_session
from src.models.decision_order_map import DecisionOrderMap
from src.models.decision_order_map_status import FAILED
from src.schemas.trace import TRACE_STATUS_FAILED, MISSING_NODE_EXECUTION, MISSING_NODE_TRADE
from sqlalchemy import event

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)

@pytest.mark.asyncio
async def test_failed_decision_trace_200_and_reason(client, db_session_factory):
    """
    AC-D2-TRACE-404-01: FAILED decision 可通过 Trace API 查询，返回 200 及原因。
    任务 3: 只读边界强反证升级 (SQLAlchemy 事件钩子拦截)。
    """
    decision_id = f"test-failed-trace-{datetime.now(timezone.utc).timestamp()}"
    failed_reason = "Test risk check failed"
    
    # 1. 构造 FAILED decision
    async with get_db_session() as session:
        new_decision = DecisionOrderMap(
            decision_id=decision_id,
            signal_id=f"sig-{decision_id}",
            strategy_id="test-strat",
            symbol="BTC/USDT",
            side="BUY",
            quantity=1.0,
            status=FAILED,
            last_error=failed_reason,
            created_at=datetime.now(timezone.utc)
        )
        session.add(new_decision)
        await session.commit()

    # 2. 强锁死只读：注册事件钩子拦截任何写操作
    write_detected = []
    
    # 获取 engine (来自 db_session_factory 的 bind)
    engine = db_session_factory.kw['bind']
    
    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        stmt_upper = statement.upper().strip()
        # 任务 1: 移除 PERF_LOG 写入白名单，实现全量 SQL 写拦截
        if any(stmt_upper.startswith(prefix) for prefix in ["INSERT", "UPDATE", "DELETE", "REPLACE"]):
            write_detected.append(statement)

    try:
        # 3. 调用 Trace API
        response = client.get(f"/api/trace/decision/{decision_id}")
        
        # 4. 验证响应内容
        assert response.status_code == 200
        data = response.json()
        assert data["trace_status"] == TRACE_STATUS_FAILED
        assert MISSING_NODE_EXECUTION in data["missing_nodes"]
        assert MISSING_NODE_TRADE in data["missing_nodes"]
        assert data["missing_reason"]["failed_reason"] == failed_reason
        assert data["decision"]["decision_id"] == decision_id
        
        # 5. 强锁死断言：API 调用期间不得有写操作
        assert len(write_detected) == 0, f"ReadOnly Violation! Detected writes: {write_detected}"
        
    finally:
        # 清理事件监听，避免影响后续测试
        event.remove(engine.sync_engine, "before_cursor_execute", receive_before_cursor_execute)
