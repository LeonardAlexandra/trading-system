"""
Phase1.1 D1：TTL 锁超时测试（验证 ReconcileLock TTL 功能）

- 验证 ReconcileLock 在 TTL 过期后释放，其他会话可重新获取锁，且无无限占锁。
- 测试环境使用短 TTL（1～2 秒），禁止使用生产 TTL（30 秒）或 sleep(30)；依赖可配置短 TTL 保证自动化执行。
"""
import asyncio
import pytest
from sqlalchemy import text

from src.app.dependencies import set_session_factory
from src.locks.reconcile_lock import ReconcileLock

# D1：测试用短 TTL（秒），满足「1～2 秒」要求，使 CI 在数秒内完成锁过期断言
D1_TEST_TTL_SECONDS = 1
D1_SLEEP_AFTER_HOLD = 2.0


async def _ensure_row_with_short_ttl(session, strategy_id: str, lock_ttl_seconds: int = D1_TEST_TTL_SECONDS):
    """确保 strategy_runtime_state 存在且行上 lock_ttl_seconds 为短 TTL（D1 禁止生产 30 秒）。"""
    await session.execute(
        text(
            "INSERT OR REPLACE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, 'RUNNING', :ttl)"
        ),
        {"sid": strategy_id, "ttl": lock_ttl_seconds},
    )
    await session.flush()


@pytest.mark.asyncio
async def test_d1_ttl_expiry_other_session_can_acquire(db_session_factory):
    """
    D1：获取 ReconcileLock 后不释放、不续期，等待超过 TTL；验证另一会话在 TTL 后可成功获取锁。
    使用行上 lock_ttl_seconds=1，等待 2 秒后断言新会话可获取，不依赖人工等待、禁止 sleep(30)。
    """
    set_session_factory(db_session_factory)
    strategy_id = "D1_TTL_STRAT"
    async with db_session_factory() as session:
        await _ensure_row_with_short_ttl(session, strategy_id, lock_ttl_seconds=D1_TEST_TTL_SECONDS)
        await session.commit()
    async with db_session_factory() as session:
        async with session.begin():
            lock_a = ReconcileLock(session, "holder-A", ttl_seconds=D1_TEST_TTL_SECONDS, max_acquire_retries=0)
            assert await lock_a.acquire(strategy_id) is True
    await asyncio.sleep(D1_SLEEP_AFTER_HOLD)
    async with db_session_factory() as session:
        async with session.begin():
            lock_b = ReconcileLock(session, "holder-B", ttl_seconds=D1_TEST_TTL_SECONDS, max_acquire_retries=0)
            assert await lock_b.acquire(strategy_id) is True


@pytest.mark.asyncio
async def test_d1_explicit_release_then_other_session_can_acquire(db_session_factory):
    """D1：显式释放后，新会话可立即获取锁。"""
    set_session_factory(db_session_factory)
    strategy_id = "D1_RELEASE_STRAT"
    async with db_session_factory() as session:
        await _ensure_row_with_short_ttl(session, strategy_id)
        await session.commit()
    async with db_session_factory() as session:
        async with session.begin():
            lock_a = ReconcileLock(session, "holder-A", max_acquire_retries=0)
            assert await lock_a.acquire(strategy_id) is True
            assert await lock_a.release(strategy_id) is True
    async with db_session_factory() as session:
        async with session.begin():
            lock_b = ReconcileLock(session, "holder-B", max_acquire_retries=0)
            assert await lock_b.acquire(strategy_id) is True
