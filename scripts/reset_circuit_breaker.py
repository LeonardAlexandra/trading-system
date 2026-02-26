#!/usr/bin/env python3
"""
PR16：断路器回滚入口脚本（受控）。
- 输入 account_id
- 打印当前 circuit 状态
- 执行 reset（归零 failures_count、清除 opened_at_utc）
- 写 execution_events：CIRCUIT_RESET_BY_OPERATOR（不含 secret）
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

# 项目根目录加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.repositories.circuit_breaker_repository import CircuitBreakerRepository
from src.repositories.execution_event_repository import ExecutionEventRepository
from src.common.event_types import CIRCUIT_RESET_BY_OPERATOR


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        try:
            from src.config.app_config import load_app_config
            cfg = load_app_config()
            url = cfg.database.url or "sqlite+aiosqlite:///./trading_system.db"
        except Exception:
            url = "sqlite+aiosqlite:///./trading_system.db"
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        url = "sqlite+aiosqlite://" + url[len("sqlite://"):]
    return url


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/reset_circuit_breaker.py <account_id>")
        print("Example: python scripts/reset_circuit_breaker.py acc1")
        sys.exit(1)
    account_id = (sys.argv[1] or "").strip()
    if not account_id:
        print("Error: account_id is required")
        sys.exit(1)

    db_url = _get_db_url()
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        repo = CircuitBreakerRepository(session)
        state_before = await repo.get_state(account_id)
        print(f"account_id={account_id}")
        if state_before is None:
            print("current state: no row (no failures recorded)")
        else:
            print(
                f"current state: failures_count={state_before.failures_count}, "
                f"opened_at_utc={state_before.opened_at_utc}"
            )

        await repo.close_circuit(account_id)

        decision_id = f"operator-reset-{account_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        event_repo = ExecutionEventRepository(session)
        await event_repo.append_event(
            decision_id,
            CIRCUIT_RESET_BY_OPERATOR,
            message=f"account_id={account_id} reset by operator",
        )
        await session.commit()
        print("reset done.")
        print(f"event written: {CIRCUIT_RESET_BY_OPERATOR} decision_id={decision_id}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
