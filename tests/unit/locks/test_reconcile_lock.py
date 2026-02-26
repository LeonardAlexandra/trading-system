"""
Phase1.1 C1：ReconcileLock 单元测试

- acquire/release/renew 为单条原子 UPDATE；禁止 SELECT FOR UPDATE。
- TTL 过期后可被抢占（C1-06）；有限重试或立即失败（C1-07）。
- 同一 strategy 仅一会话持锁；释放后或过期后其他会话可获取。
"""
import asyncio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.database.connection import Base
from src.locks.reconcile_lock import ReconcileLock


@pytest.fixture
async def c1_session_factory():
    """内存 SQLite + 建表，供 C1 单测使用。"""
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


async def _ensure_row(session: AsyncSession, strategy_id: str, lock_ttl_seconds: int = 30) -> None:
    """确保 strategy_runtime_state 存在一行（A1 前置）；无则插入。"""
    await session.execute(
        text(
            "INSERT OR IGNORE INTO strategy_runtime_state (strategy_id, lock_ttl_seconds) VALUES (:sid, :ttl)"
        ),
        {"sid": strategy_id, "ttl": lock_ttl_seconds},
    )
    await session.flush()


@pytest.mark.asyncio
async def test_acquire_release_success(c1_session_factory):
    """acquire 成功则返回 True，release 后再次 acquire 成功（C1-02、C1-04）。"""
    async with c1_session_factory() as session:
        await _ensure_row(session, "s1")
        await session.commit()
    async with c1_session_factory() as session:
        lock = ReconcileLock(session, "holder-1", ttl_seconds=30, max_acquire_retries=0)
        assert await lock.acquire("s1") is True
        await session.commit()
    async with c1_session_factory() as session:
        lock = ReconcileLock(session, "holder-1", ttl_seconds=30)
        assert await lock.release("s1") is True
        await session.commit()
    async with c1_session_factory() as session:
        lock = ReconcileLock(session, "holder-1", ttl_seconds=30)
        assert await lock.acquire("s1") is True
        await session.commit()


@pytest.mark.asyncio
async def test_acquire_fails_when_held_by_other(c1_session_factory):
    """同一 strategy 仅一会话持锁；其他会话 acquire 失败（C1-02）。"""
    async with c1_session_factory() as session:
        await _ensure_row(session, "s1")
        await session.commit()
    async with c1_session_factory() as session:
        lock_a = ReconcileLock(session, "holder-A", ttl_seconds=30, max_acquire_retries=0)
        assert await lock_a.acquire("s1") is True
        await session.commit()
    async with c1_session_factory() as session:
        lock_b = ReconcileLock(session, "holder-B", ttl_seconds=30, max_acquire_retries=0)
        assert await lock_b.acquire("s1") is False
        await session.commit()


@pytest.mark.asyncio
async def test_release_only_by_holder(c1_session_factory):
    """仅锁持有者可 release；他人 release 影响 0 行（C1-04）。"""
    async with c1_session_factory() as session:
        await _ensure_row(session, "s1")
        await session.commit()
    async with c1_session_factory() as session:
        lock_a = ReconcileLock(session, "holder-A", ttl_seconds=30)
        assert await lock_a.acquire("s1") is True
        await session.commit()
    async with c1_session_factory() as session:
        lock_b = ReconcileLock(session, "holder-B", ttl_seconds=30)
        assert await lock_b.release("s1") is False
        await session.commit()
    async with c1_session_factory() as session:
        lock_a = ReconcileLock(session, "holder-A", ttl_seconds=30)
        assert await lock_a.release("s1") is True
        await session.commit()


@pytest.mark.asyncio
async def test_renew_success(c1_session_factory):
    """持锁且未过期时 renew 成功（C1-03）。"""
    async with c1_session_factory() as session:
        await _ensure_row(session, "s1")
        await session.commit()
    async with c1_session_factory() as session:
        lock = ReconcileLock(session, "holder-1", ttl_seconds=30)
        assert await lock.acquire("s1") is True
        assert await lock.renew("s1") is True
        assert await lock.release("s1") is True
        await session.commit()


@pytest.mark.asyncio
async def test_ttl_expiry_allow_steal(c1_session_factory):
    """锁超过 TTL 未续期后，其他会话可成功获取锁（C1-05、C1-06）；TTL 取自行上 lock_ttl_seconds（C1-10）。"""
    # 行上 lock_ttl_seconds=1，过期判定以列为准，不依赖 ReconcileLock 构造参数
    async with c1_session_factory() as session:
        await _ensure_row(session, "s1", lock_ttl_seconds=1)
        await session.commit()
    async with c1_session_factory() as session:
        lock_a = ReconcileLock(session, "holder-A", max_acquire_retries=0)
        assert await lock_a.acquire("s1") is True
        await session.commit()
    await asyncio.sleep(2.0)
    async with c1_session_factory() as session:
        lock_b = ReconcileLock(session, "holder-B", max_acquire_retries=0)
        assert await lock_b.acquire("s1") is True
        await session.commit()


@pytest.mark.asyncio
async def test_ttl_from_column_30s_not_expired(c1_session_factory):
    """行上 lock_ttl_seconds=30 时，1.5 秒内锁未过期，其他会话无法抢占（证明 TTL 真理源为列）。"""
    async with c1_session_factory() as session:
        await _ensure_row(session, "s1", lock_ttl_seconds=30)
        await session.commit()
    async with c1_session_factory() as session:
        lock_a = ReconcileLock(session, "holder-A", max_acquire_retries=0)
        assert await lock_a.acquire("s1") is True
        await session.commit()
    await asyncio.sleep(1.5)
    async with c1_session_factory() as session:
        lock_b = ReconcileLock(session, "holder-B", max_acquire_retries=0)
        assert await lock_b.acquire("s1") is False
    async with c1_session_factory() as session:
        lock_a = ReconcileLock(session, "holder-A")
        assert await lock_a.release("s1") is True
        await session.commit()


@pytest.mark.asyncio
async def test_is_held_by_me(c1_session_factory):
    """is_held_by_me 仅读；持有时为 True，释放后为 False。"""
    async with c1_session_factory() as session:
        await _ensure_row(session, "s1")
        await session.commit()
    async with c1_session_factory() as session:
        lock = ReconcileLock(session, "me", ttl_seconds=30)
        assert await lock.is_held_by_me("s1") is False
        assert await lock.acquire("s1") is True
        assert await lock.is_held_by_me("s1") is True
        await lock.release("s1")
        assert await lock.is_held_by_me("s1") is False
        await session.commit()


@pytest.mark.asyncio
async def test_use_lock_context_manager(c1_session_factory):
    """use_lock 上下文：acquire 成功则 yield True，退出时 release（含异常）。"""
    async with c1_session_factory() as session:
        await _ensure_row(session, "s1")
        await session.commit()
    async with c1_session_factory() as session:
        lock = ReconcileLock(session, "ctx-holder", ttl_seconds=30)
        async with lock.use_lock("s1") as ok:
            assert ok is True
            assert await lock.is_held_by_me("s1") is True
        await session.commit()
    async with c1_session_factory() as session:
        lock2 = ReconcileLock(session, "other", ttl_seconds=30)
        assert await lock2.acquire("s1") is True
        await session.commit()


@pytest.mark.asyncio
async def test_acquire_immediate_fail_no_retry(c1_session_factory):
    """max_acquire_retries=0 时抢占失败立即返回 False（C1-07）。"""
    async with c1_session_factory() as session:
        await _ensure_row(session, "s1")
        await session.commit()
    async with c1_session_factory() as session:
        lock_a = ReconcileLock(session, "A", ttl_seconds=30, max_acquire_retries=0)
        assert await lock_a.acquire("s1") is True
        await session.commit()
    async with c1_session_factory() as session:
        lock_b = ReconcileLock(session, "B", ttl_seconds=30, max_acquire_retries=0)
        assert await lock_b.acquire("s1") is False
        await session.commit()


@pytest.mark.asyncio
async def test_acquire_no_row_returns_false(c1_session_factory):
    """strategy_id 无对应行时 UPDATE 影响 0 行，acquire 返回 False。"""
    async with c1_session_factory() as session:
        lock = ReconcileLock(session, "h", ttl_seconds=30)
        assert await lock.acquire("nonexistent") is False
        await session.commit()
