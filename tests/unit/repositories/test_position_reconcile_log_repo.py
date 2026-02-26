"""
Phase1.1 A3：PositionReconcileLogRepository 单元测试

- A3-05 防呆：无事务时写入必须拒绝并抛出 PositionReconcileLogNotInTransactionError。
- event_type 非法值时 DB CHECK 约束触发 IntegrityError。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.database.connection import Base
from src.models.position_reconcile_log import PositionReconcileLog, RECONCILE_START
from src.repositories.position_reconcile_log_repo import (
    PositionReconcileLogNotInTransactionError,
    PositionReconcileLogRepository,
)


@pytest.fixture
async def a3_session_factory():
    """内存 SQLite + 建表，供 A3 单测使用。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autobegin=True,
    )


@pytest.mark.asyncio
async def test_create_without_transaction_raises(a3_session_factory):
    """A3-05 防呆：session 未在事务内时 create() 必须拒绝并抛出 PositionReconcileLogNotInTransactionError。"""
    session_factory = a3_session_factory
    async with session_factory() as session:
        repo = PositionReconcileLogRepository(session)
        log = PositionReconcileLog(strategy_id="S1", event_type=RECONCILE_START)
        # 不调用 session.begin()，直接 create：应触发事务检查失败
        with pytest.raises(PositionReconcileLogNotInTransactionError) as exc_info:
            await repo.create(log)
        assert "transaction" in str(exc_info.value).lower()
        assert "position_reconcile_log" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_log_event_in_txn_without_transaction_raises(a3_session_factory):
    """A3-05 防呆：session 未在事务内时 log_event_in_txn() 必须拒绝并抛出 PositionReconcileLogNotInTransactionError。"""
    session_factory = a3_session_factory
    async with session_factory() as session:
        repo = PositionReconcileLogRepository(session)
        with pytest.raises(PositionReconcileLogNotInTransactionError) as exc_info:
            await repo.log_event_in_txn("S1", RECONCILE_START)
        assert "transaction" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_log_event_in_txn_inside_transaction_succeeds(a3_session_factory):
    """在 session.begin() 内调用 log_event_in_txn 应成功写入（推荐主路径）。"""
    session_factory = a3_session_factory
    async with session_factory() as session:
        async with session.begin():
            repo = PositionReconcileLogRepository(session)
            log = await repo.log_event_in_txn("S1", RECONCILE_START)
            assert log.id is None  # 未 flush 前可能未赋 id
            assert log.strategy_id == "S1"
            assert log.event_type == RECONCILE_START
    # 事务提交后可见
    async with session_factory() as session2:
        repo2 = PositionReconcileLogRepository(session2)
        async with session2.begin():
            listed = await repo2.list_by_strategy("S1", limit=5)
            assert len(listed) >= 1
            assert listed[0].event_type == RECONCILE_START


@pytest.mark.asyncio
async def test_invalid_event_type_db_check_constraint_fails(a3_session_factory):
    """非法 event_type 写入触发 DB CHECK 约束，抛出 IntegrityError（证据：来自 ck_position_reconcile_log_event_type）。"""
    session_factory = a3_session_factory
    async with session_factory() as session:
        with pytest.raises(IntegrityError) as exc_info:
            async with session.begin():
                # 绕过 Repo 校验，直接写非法 event_type，由 DB CHECK 拒绝
                await session.execute(
                    text(
                        "INSERT INTO position_reconcile_log (strategy_id, event_type) VALUES (:s, :e)"
                    ),
                    {"s": "S1", "e": "INVALID_EVENT_TYPE"},
                )
        err_msg = str(exc_info.value).lower()
        assert "check" in err_msg or "constraint" in err_msg or "event_type" in err_msg
        assert "position_reconcile_log" in err_msg or "event_type" in err_msg or "check" in err_msg
