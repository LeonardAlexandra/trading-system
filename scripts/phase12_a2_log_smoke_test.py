#!/usr/bin/env python3
"""
Phase1.2 A2 系统级最小可用性验证：向 log 表写入 1 条记录并查询回显。
临时验证脚本，不实现 LogRepository；仅证明 log 表可被系统写入与读取。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.models.log_entry import LogEntry


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        url = "sqlite+aiosqlite:///./phase12_a2_evidence.db"
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        url = "sqlite+aiosqlite://" + url[len("sqlite://"):]
    return url


async def main() -> None:
    db_url = _get_db_url()
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        entry = LogEntry(
            component="test_smoke",
            level="INFO",
            message="phase1.2 A2 smoke test",
            event_type="SMOKE_TEST",
            payload={"ok": True},
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        row_id = entry.id

        result = await session.execute(select(LogEntry).where(LogEntry.id == row_id))
        row = result.scalar_one()

    print("--- phase1.2 A2 log smoke test: inserted and queried ---")
    print(f"id: {row.id}")
    print(f"created_at: {row.created_at}")
    print(f"component: {row.component}")
    print(f"level: {row.level}")
    print(f"message: {row.message}")
    print(f"event_type: {row.event_type}")
    print(f"payload: {row.payload}")
    print("--- end ---")


if __name__ == "__main__":
    asyncio.run(main())
