"""
Phase1.1 C1：ReconcileLock（DB 原子租约锁 + TTL）

仅允许基于数据库的租约锁，使用单条原子 UPDATE 进行 acquire/renew/release。
禁止 SELECT FOR UPDATE、禁止长事务持锁期间做外部 I/O。
真理源（C1-10）：strategy_runtime_state 表中 lock_holder_id、locked_at、lock_ttl_seconds；
过期/续期判定必须使用行上的 lock_ttl_seconds 列，不得用环境变量绕过。

【锁行不存在责任边界】调用方在 acquire 前必须确保存在 strategy_runtime_state 行（A1/业务初始化）；
无行时 UPDATE 影响 0 行，acquire 返回 False，与「锁被他人占用」在返回值上不可区分；
调用方通过「先确保行存在」或「用 repo.get_by_strategy_id 检查行是否存在」区分。
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 仅用于默认值/回填（如插入新行时）；过期计算以行上 lock_ttl_seconds 列为准（C1-10）
_DEFAULT_TTL_SECONDS = 30


def _ttl_seconds_from_env() -> int:
    """环境变量 RECONCILE_LOCK_TTL_SECONDS，仅作默认值/回填，不参与 acquire/renew 的过期判定。"""
    raw = (os.environ.get("RECONCILE_LOCK_TTL_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_TTL_SECONDS
    try:
        n = int(raw)
        return n if n > 0 else _DEFAULT_TTL_SECONDS
    except ValueError:
        return _DEFAULT_TTL_SECONDS


class ReconcileLock:
    """
    Phase1.1 C1：基于 strategy_runtime_state 的 DB 原子租约锁。

    - acquire/renew/release 均为单条原子 UPDATE，禁止 SELECT FOR UPDATE。
    - 过期/续期判定使用行上 lock_ttl_seconds 列（C1-10），不以构造参数或环境变量为准。
    - ttl_seconds 构造参数仅作默认值/回填用途（如创建行时），不参与 WHERE 条件。
    - 失败策略：立即失败或有限重试（最多 max_acquire_retries 次，间隔 retry_interval_seconds）。
    - 调用方负责事务边界；持锁内禁止外部 I/O（由调用方遵守）。
    """

    def __init__(
        self,
        session: AsyncSession,
        holder_id: str,
        ttl_seconds: Optional[int] = None,
        max_acquire_retries: int = 0,
        retry_interval_seconds: float = 0.1,
    ):
        """
        Args:
            session: 异步 DB 会话；调用方管理生命周期与事务。
            holder_id: 本实例/进程的锁持有者标识。
            ttl_seconds: 仅用于默认值/回填（如插入行时）；acquire/renew 的过期判定使用行上 lock_ttl_seconds 列。None 时从环境变量或 30 读取。
            max_acquire_retries: acquire 失败时的最大重试次数，0 表示立即失败（C1-07）。
            retry_interval_seconds: 重试间隔（秒），如 0.1 表示 100ms。
        """
        self._session = session
        self._holder_id = holder_id
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else _ttl_seconds_from_env()
        self._max_acquire_retries = max(0, max_acquire_retries)
        self._retry_interval_seconds = max(0.0, retry_interval_seconds)

    # ---------- 单条原子 UPDATE（C1-02 / C1-03 / C1-04）；TTL 取自行上 lock_ttl_seconds（C1-10）----------

    async def acquire(self, strategy_id: str) -> bool:
        """
        加锁：单条原子 UPDATE，条件为当前无锁或锁已过期（C1-02）。
        过期判定使用行上 lock_ttl_seconds 列：datetime(locked_at, '+'||lock_ttl_seconds||' seconds') < datetime('now')。
        affected_rows == 1 则成功，否则失败。支持有限重试（C1-07）。
        无行或锁被占用时均返回 False；调用方须先确保行存在以区分。
        """
        # SQLite：使用列 lock_ttl_seconds 作为 TTL 真理源（C1-10）
        sql = text(
            """
            UPDATE strategy_runtime_state
            SET lock_holder_id = :holder_id,
                locked_at = datetime('now')
            WHERE strategy_id = :strategy_id
              AND (
                    lock_holder_id IS NULL
                    OR datetime(locked_at, '+' || cast(lock_ttl_seconds as text) || ' seconds') < datetime('now')
                  )
            """
        )
        params = {"holder_id": self._holder_id, "strategy_id": strategy_id}

        for attempt in range(self._max_acquire_retries + 1):
            result = await self._session.execute(sql, params)
            rowcount = result.rowcount
            if rowcount == 1:
                logger.info("ReconcileLock acquired strategy_id=%s holder=%s", strategy_id, self._holder_id)
                return True
            if attempt < self._max_acquire_retries:
                await asyncio.sleep(self._retry_interval_seconds)
            else:
                break
        logger.debug("ReconcileLock acquire failed strategy_id=%s holder=%s", strategy_id, self._holder_id)
        return False

    async def renew(self, strategy_id: str) -> bool:
        """
        续期：单条原子 UPDATE，条件为当前锁持有者为本实例且未过期（C1-03）。
        未过期判定使用行上 lock_ttl_seconds 列：datetime(locked_at, '+'||lock_ttl_seconds||' seconds') > datetime('now')。
        affected_rows == 1 则续期成功。
        """
        # SQLite：使用列 lock_ttl_seconds 作为 TTL 真理源（C1-10）
        sql = text(
            """
            UPDATE strategy_runtime_state
            SET locked_at = datetime('now')
            WHERE strategy_id = :strategy_id
              AND lock_holder_id = :holder_id
              AND datetime(locked_at, '+' || cast(lock_ttl_seconds as text) || ' seconds') > datetime('now')
            """
        )
        params = {"holder_id": self._holder_id, "strategy_id": strategy_id}
        result = await self._session.execute(sql, params)
        if result.rowcount == 1:
            logger.debug("ReconcileLock renewed strategy_id=%s holder=%s", strategy_id, self._holder_id)
            return True
        return False

    async def release(self, strategy_id: str) -> bool:
        """
        释放：单条原子 UPDATE，条件为当前锁持有者为本实例（C1-04）。
        affected_rows == 1 则释放成功。
        """
        sql = text(
            """
            UPDATE strategy_runtime_state
            SET lock_holder_id = NULL,
                locked_at = NULL
            WHERE strategy_id = :strategy_id
              AND lock_holder_id = :holder_id
            """
        )
        params = {"holder_id": self._holder_id, "strategy_id": strategy_id}
        result = await self._session.execute(sql, params)
        if result.rowcount == 1:
            logger.info("ReconcileLock released strategy_id=%s holder=%s", strategy_id, self._holder_id)
            return True
        return False

    async def is_held_by_me(self, strategy_id: str) -> bool:
        """
        查询当前是否由本实例持有锁（仅读，允许 SELECT；非加锁语义）。
        """
        sql = text(
            """
            SELECT 1 FROM strategy_runtime_state
            WHERE strategy_id = :strategy_id
              AND lock_holder_id = :holder_id
            LIMIT 1
            """
        )
        result = await self._session.execute(sql, {"strategy_id": strategy_id, "holder_id": self._holder_id})
        return result.scalar() is not None

    @asynccontextmanager
    async def use_lock(self, strategy_id: str) -> AsyncIterator[bool]:
        """
        上下文管理器：acquire 成功后 yield True，退出时 release（含异常时释放，C2 持锁边界）。
        若 acquire 失败则 yield False，不执行 release。
        """
        ok = await self.acquire(strategy_id)
        try:
            yield ok
        finally:
            if ok:
                await self.release(strategy_id)
