"""
Phase1.2 C8：审计查询 CLI。与 Web 共用 src.services.audit_service。
命令：最近 N 条 ERROR/AUDIT 日志、按条件分页查日志、list_traces 回放（含 trace_status/missing_nodes）。
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.app.dependencies import get_db_session, set_session_factory
from src.database.connection import init_session_factory
from src.services import audit_service


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        url = "sqlite+aiosqlite:///./trading_system.db"
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        url = "sqlite+aiosqlite://" + url[len("sqlite://") :]
    return url


async def _run_recent_logs(n: int, levels: list) -> None:
    async with get_db_session() as session:
        items = await audit_service.recent_logs(session, n=n, levels=levels or ["ERROR", "AUDIT"])
    for row in items:
        print(json.dumps(row, ensure_ascii=False, default=str))


async def _run_query_logs(args) -> None:
    from_ts = args.from_ts
    to_ts = args.to_ts
    async with get_db_session() as session:
        items = await audit_service.query_logs(
            session,
            created_at_from=from_ts,
            created_at_to=to_ts,
            component=args.component,
            level=args.level,
            limit=min(args.limit, 1000),
            offset=args.offset,
        )
    for row in items:
        print(json.dumps(row, ensure_ascii=False, default=str))
    print(f"# count={len(items)}", file=sys.stderr)


async def _run_traces(args) -> None:
    from_ts = args.from_ts
    to_ts = args.to_ts
    async with get_db_session() as session:
        items = await audit_service.list_traces(
            session,
            from_ts=from_ts,
            to_ts=to_ts,
            strategy_id=args.strategy_id,
            limit=min(args.limit, 100),
            offset=args.offset,
        )
    for t in items:
        print(json.dumps(t.to_dict(), ensure_ascii=False, default=str))
    print(f"# count={len(items)} (trace_status/missing_nodes per item above)", file=sys.stderr)


def _parse_iso(s: str) -> datetime:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def main() -> None:
    parser = argparse.ArgumentParser(description="C8 审计查询 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # 最近 N 条 ERROR/AUDIT
    p_recent = sub.add_parser("recent-logs", help="最近 N 条 ERROR/AUDIT 日志")
    p_recent.add_argument("n", type=int, nargs="?", default=20, help="条数，默认 20")
    p_recent.add_argument("--level", type=str, default=None, help="ERROR | AUDIT | ERROR,AUDIT，默认 ERROR,AUDIT")

    # 按条件分页查日志
    p_logs = sub.add_parser("logs", help="按时间/组件/level 分页查日志")
    p_logs.add_argument("--from", dest="from_ts", type=str, default=None, help="ISO 时间")
    p_logs.add_argument("--to", dest="to_ts", type=str, default=None, help="ISO 时间")
    p_logs.add_argument("--component", type=str, default=None)
    p_logs.add_argument("--level", type=str, default=None)
    p_logs.add_argument("--limit", type=int, default=100)
    p_logs.add_argument("--offset", type=int, default=0)

    # list_traces
    p_traces = sub.add_parser("traces", help="list_traces 回放，输出含 trace_status/missing_nodes")
    p_traces.add_argument("--from", dest="from_ts", type=str, required=True, help="ISO 时间")
    p_traces.add_argument("--to", dest="to_ts", type=str, required=True, help="ISO 时间")
    p_traces.add_argument("--strategy-id", type=str, default=None)
    p_traces.add_argument("--limit", type=int, default=100)
    p_traces.add_argument("--offset", type=int, default=0)

    args = parser.parse_args()

    database_config = {"url": _db_url()}
    session_factory = await init_session_factory(database_config)
    set_session_factory(session_factory)

    if args.command == "recent-logs":
        levels = [x.strip() for x in (args.level or "ERROR,AUDIT").split(",")]
        await _run_recent_logs(args.n, levels)
    elif args.command == "logs":
        args.from_ts = _parse_iso(args.from_ts)
        args.to_ts = _parse_iso(args.to_ts)
        await _run_query_logs(args)
    elif args.command == "traces":
        args.from_ts = _parse_iso(args.from_ts)
        args.to_ts = _parse_iso(args.to_ts)
        if not args.from_ts or not args.to_ts:
            print("traces 需要 --from 与 --to（ISO 时间）", file=sys.stderr)
            sys.exit(1)
        await _run_traces(args)


if __name__ == "__main__":
    asyncio.run(main())
