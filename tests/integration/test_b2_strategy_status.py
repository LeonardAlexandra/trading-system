"""
Phase1.1 B2：GET /strategy/{id}/status（只读状态查询）

验收：存在 id 返回 200 + 状态与恢复摘要；不存在返回 404；接口无副作用，与 DB 一致。
"""
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from src.app.dependencies import get_db_session, set_session_factory
from src.models.strategy_runtime_state import STATUS_PAUSED, STATUS_RUNNING


async def _ensure_runtime_state(session, strategy_id: str, status: str):
    await session.execute(
        text(
            "INSERT OR REPLACE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, :st, 30)"
        ),
        {"sid": strategy_id, "st": status},
    )


@pytest.mark.asyncio
async def test_b2_get_status_200_when_exists_running(db_session_factory):
    """B2：存在的 strategy id 且状态 RUNNING，返回 200 及 status、can_resume 等。"""
    set_session_factory(db_session_factory)
    strategy_id = "B2_STATUS_RUNNING"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id, STATUS_RUNNING)

    from src.app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        set_session_factory(db_session_factory)
        response = client.get(f"/strategy/{strategy_id}/status")

    assert response.status_code == 200
    data = response.json()
    assert data.get("strategy_id") == strategy_id
    assert data.get("status") == STATUS_RUNNING
    assert data.get("can_resume") is False
    assert "last_reconcile_at" in data


@pytest.mark.asyncio
async def test_b2_get_status_200_when_exists_paused(db_session_factory):
    """B2：存在的 strategy id 且状态 PAUSED，返回 200，can_resume 为 True。"""
    set_session_factory(db_session_factory)
    strategy_id = "B2_STATUS_PAUSED"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id, STATUS_PAUSED)

    from src.app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        set_session_factory(db_session_factory)
        response = client.get(f"/strategy/{strategy_id}/status")

    assert response.status_code == 200
    data = response.json()
    assert data.get("strategy_id") == strategy_id
    assert data.get("status") == STATUS_PAUSED
    assert data.get("can_resume") is True
    assert "last_reconcile_at" in data


@pytest.mark.asyncio
async def test_b2_get_status_404_when_not_exists(db_session_factory):
    """B2：不存在的 strategy id 返回 404。"""
    set_session_factory(db_session_factory)

    from src.app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        set_session_factory(db_session_factory)
        response = client.get("/strategy/NONEXISTENT_STRAT_ID/status")

    assert response.status_code == 404
    data = response.json()
    assert data.get("detail") == "strategy not found"
    assert data.get("strategy_id") == "NONEXISTENT_STRAT_ID"


@pytest.mark.asyncio
async def test_b2_get_status_read_only_no_side_effects(db_session_factory):
    """B2：多次调用 GET status 不改变状态，响应与 DB 一致。"""
    set_session_factory(db_session_factory)
    strategy_id = "B2_READONLY_STRAT"
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id, STATUS_PAUSED)

    from src.app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        set_session_factory(db_session_factory)
        r1 = client.get(f"/strategy/{strategy_id}/status")
        r2 = client.get(f"/strategy/{strategy_id}/status")

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json().get("status") == STATUS_PAUSED

    async with get_db_session() as session:
        from src.repositories.strategy_runtime_state_repo import StrategyRuntimeStateRepository
        state_repo = StrategyRuntimeStateRepository(session)
        state = await state_repo.get_by_strategy_id(strategy_id)
    assert state is not None
    assert state.status == STATUS_PAUSED
    assert r1.json().get("status") == state.status, "B2: 响应须与 DB 一致"
