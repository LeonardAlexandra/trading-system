"""
Phase1.1 D4：恢复失败 → 返回标准 diff 测试（B1 负向链路）

走真实 B1 路由 POST /strategy/{id}/resume，构造强校验必然失败场景，
断言 HTTP 400、body 为结构化 diff JSON（禁止纯文本），diff 顶层字段及 diff.checks 至少 1 个失败项。
"""
import pytest
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import create_engine
from fastapi.testclient import TestClient

from src.app.dependencies import get_db_session, set_session_factory
from src.database.connection import Base
from src.models.strategy_runtime_state import STATUS_RUNNING
from tests.fixtures.resume_fail_fixtures import (
    strategy_id_for_resume_fail,
    status_that_fails_resume_check,
)


# B1 diff 标准公式（Phase1.1）
RESUME_CHECK_FAILED_CODE = "RESUME_CHECK_FAILED"
DIFF_TOP_LEVEL_KEYS = {"code", "checks", "snapshot"}
CHECK_ENTRY_KEYS = {"field", "expected", "actual", "pass"}


async def _ensure_runtime_state(session: AsyncSession, strategy_id: str, status: str) -> None:
    await session.execute(
        text(
            "INSERT OR REPLACE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, :st, 30)"
        ),
        {"sid": strategy_id, "st": status},
    )
    await session.flush()


@pytest.fixture
async def d4_resume_fail_setup(tmp_path: Path, monkeypatch):
    """
    D4：文件 DB + 应用配置；插入「强校验必然失败」状态（如 RUNNING → state_is_paused 失败）。
    应用与测试共用同一 DB，以便 B1 路由读到该状态。
    """
    db_file = tmp_path / "test_d4_resume.db"
    db_url_sync = "sqlite:///" + str(db_file)
    db_url_async = "sqlite+aiosqlite:///" + str(db_file)

    Base.metadata.create_all(create_engine(db_url_sync))
    monkeypatch.setenv("DATABASE_URL", db_url_async)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))

    from src.app.main import create_app
    app = create_app()

    engine = create_async_engine(
        db_url_async,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    set_session_factory(session_factory)

    strategy_id = strategy_id_for_resume_fail()
    status = status_that_fails_resume_check()
    async with get_db_session() as session:
        await _ensure_runtime_state(session, strategy_id, status)
        await session.commit()

    yield app, strategy_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_d4_resume_fail_returns_400_and_structured_diff(d4_resume_fail_setup):
    """
    D4：强校验不通过时，真实 B1 路由返回 400，body 为结构化 diff（code, checks, snapshot）；
    diff.checks 至少 1 个失败项；禁止纯文本；若有 snapshot 须可解析。
    """
    app, strategy_id = d4_resume_fail_setup

    with TestClient(app) as client:
        response = client.post(f"/strategy/{strategy_id}/resume")

    assert response.status_code == 400, "D4: 强校验失败必须返回 400，不得 2xx/4xx 其他/5xx"

    # 禁止纯文本：必须为 JSON
    try:
        body = response.json()
    except Exception as e:
        raise AssertionError(f"D4: 响应体必须为可解析 JSON，禁止纯文本: {e}") from e

    assert isinstance(body, dict), "D4: body 必须为 JSON 对象"

    # 顶层字段（Phase1.1 diff 标准公式）
    for key in DIFF_TOP_LEVEL_KEYS:
        assert key in body, f"D4: diff 必须包含顶层字段 {key!r}"

    assert body.get("code") == RESUME_CHECK_FAILED_CODE, (
        f"D4: code 须为 {RESUME_CHECK_FAILED_CODE!r}"
    )

    checks = body.get("checks")
    assert isinstance(checks, list), "D4: checks 须为 array"
    assert len(checks) >= 1, "D4: checks 至少 1 项"
    failed = [c for c in checks if c.get("pass") is False]
    assert len(failed) >= 1, "D4: diff.checks 至少 1 个失败项（pass=false）"

    for c in checks:
        for k in CHECK_ENTRY_KEYS:
            assert k in c, f"D4: checks 项须含字段 {k!r}"

    snapshot = body.get("snapshot")
    assert snapshot is not None, "D4: snapshot 必须存在"
    assert isinstance(snapshot, dict), "D4: snapshot 须为可解析对象（dict）"
    assert "strategy_id" in snapshot
    assert snapshot.get("strategy_id") == strategy_id
    assert "status" in snapshot


@pytest.mark.asyncio
async def test_d4_resume_fail_diff_structure_no_plain_text(d4_resume_fail_setup):
    """
    D4：断言非 400 / body 非 JSON / diff 缺字段或结构不符 / diff.checks 为空 → 显式失败。
    """
    app, strategy_id = d4_resume_fail_setup

    with TestClient(app) as client:
        response = client.post(f"/strategy/{strategy_id}/resume")

    if response.status_code != 400:
        pytest.fail(f"D4: 强校验失败须返回 400，实际 {response.status_code}")

    try:
        body = response.json()
    except Exception:
        pytest.fail("D4: 响应体须为 JSON，不得为纯文本")

    if not isinstance(body, dict):
        pytest.fail("D4: body 须为 JSON 对象")

    missing = DIFF_TOP_LEVEL_KEYS - set(body.keys())
    if missing:
        pytest.fail(f"D4: diff 缺字段: {missing}")

    if not isinstance(body.get("checks"), list) or len(body["checks"]) == 0:
        pytest.fail("D4: checks 须为非空 array")

    if all(c.get("pass") for c in body["checks"]):
        pytest.fail("D4: checks 须至少 1 项 pass=false")
