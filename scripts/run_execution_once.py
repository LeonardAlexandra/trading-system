"""
一次性执行：初始化 DB + 插入 RESERVED + 执行单次 worker 循环（用于验证 execution/worker 日志）
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# 确保项目根在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.app.dependencies import set_session_factory, get_db_session
import src.models
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.execution.execution_worker import run_once
from src.execution.worker_config import WorkerConfig
from src.utils.config import load_config
from src.utils.logging import setup_logging
from src.database.connection import init_session_factory


async def main():
    tmp_db = Path(os.environ.get("TMP_DB", "/tmp/run_execution_once.db"))
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_db}"
    os.environ.setdefault("LOG_LEVEL", "INFO")

    config = load_config()
    setup_logging(
        log_level=config.get("logging", {}).get("level", "INFO"),
        log_file=config.get("logging", {}).get("file"),
        log_to_database=config.get("logging", {}).get("database", False),
    )
    database_config = {"url": os.environ["DATABASE_URL"]}
    session_factory = await init_session_factory(database_config)
    set_session_factory(session_factory)

    sync_url = f"sqlite:///{tmp_db}"
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    async with get_db_session() as session:
        repo = DecisionOrderMapRepository(session)
        for i in range(3):
            await repo.create_reserved(
                decision_id=f"run-once-decision-00{i+1}",
                signal_id=f"sig-run-once-{i+1}",
                strategy_id="strat-run-once",
                symbol="BTCUSDT",
                side="BUY",
                created_at=datetime.now(timezone.utc),
                quantity=Decimal("1"),
            )

    config = WorkerConfig.from_env()
    n = await run_once(config)
    if n > 0:
        logger.info(
            "batch_processed processed_count=%s batch_size=%s",
            n,
            config.batch_size,
        )


if __name__ == "__main__":
    asyncio.run(main())
