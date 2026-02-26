#!/usr/bin/env python3
"""
Phase1.2 A3 系统级最小可用性验证：向 perf_log 表写入 1 条记录并查询回显。
临时验证脚本，不实现 PerfLogRepository；仅证明 perf_log 表可被系统写入与读取。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.models.perf_log_entry import PerfLogEntry


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        url = "sqlite+aiosqlite:///./phase12_a3_evidence.db"
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
        entry = PerfLogEntry(
            component="test_smoke",
            metric="latency_ms",
            value=Decimal("12.345678"),
            tags={"ok": True, "note": "phase1.2 A3 smoke test"},
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        row_id = entry.id

        result = await session.execute(select(PerfLogEntry).where(PerfLogEntry.id == row_id))
        row = result.scalar_one()

    print("--- phase1.2 A3 perf_log smoke test: inserted and queried ---")
    print(f"id: {row.id}")
    print(f"created_at: {row.created_at}")
    print(f"component: {row.component}")
    print(f"metric: {row.metric}")
    print(f"value: {row.value}")
    print(f"tags: {row.tags}")
    print("--- end ---")


if __name__ == "__main__":
    asyncio.run(main())
