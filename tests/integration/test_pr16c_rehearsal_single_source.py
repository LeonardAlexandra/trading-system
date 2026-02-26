"""
PR16c：rehearsal 单一真源回归测试。
- 唯一权威来源为 execution_events.rehearsal 列；message 不包含 "rehearsal=" 字样。
- 生成 rehearsal 事件后断言 event.rehearsal=True 且 event.message 不包含 "rehearsal="。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.repositories.execution_event_repository import ExecutionEventRepository


@pytest.fixture
def pr16c_rehearsal_db_url(tmp_path):
    return "sqlite+aiosqlite:///" + (tmp_path / "pr16c_rehearsal.db").as_posix()


@pytest.fixture
async def pr16c_rehearsal_session_factory(pr16c_rehearsal_db_url):
    sync_url = pr16c_rehearsal_db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    aengine = create_async_engine(pr16c_rehearsal_db_url, echo=False)
    session_factory = async_sessionmaker(
        aengine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    yield session_factory
    await aengine.dispose()


@pytest.mark.asyncio
async def test_rehearsal_event_rehearsal_column_true_message_no_rehearsal_literal(pr16c_rehearsal_session_factory):
    """
    PR16c：生成 rehearsal=True 事件后，断言 event.rehearsal=True 且 event.message 不包含 "rehearsal="。
    """
    async with pr16c_rehearsal_session_factory() as session:
        repo = ExecutionEventRepository(session)
        ev = await repo.append_event(
            "decision-pr16c-1",
            "CLAIMED",
            message="demo rehearsal run",
            rehearsal=True,
        )
        await session.commit()
        assert ev.rehearsal is True
        assert "rehearsal=" not in (ev.message or "")


@pytest.mark.asyncio
async def test_rehearsal_event_with_null_message_no_rehearsal_literal(pr16c_rehearsal_session_factory):
    """rehearsal=True、message=None 时，message 仍不包含 'rehearsal='。"""
    async with pr16c_rehearsal_session_factory() as session:
        repo = ExecutionEventRepository(session)
        ev = await repo.append_event(
            "decision-pr16c-2",
            "ORDER_SUBMIT_STARTED",
            message=None,
            rehearsal=True,
        )
        await session.commit()
        assert ev.rehearsal is True
        assert "rehearsal=" not in (ev.message or "")
