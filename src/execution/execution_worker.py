"""
执行 Worker（PR6 拉取执行 + PR7 配置化、结构化日志）
C7：执行提交入口打点 latency_ms（execution_engine）。
"""
import asyncio
import logging
import os
import sys

from src.app.dependencies import get_db_session, set_session_factory
from src.database.connection import init_session_factory
from src.config.app_config import load_app_config
from src.utils.logging import setup_logging
from src.repositories.decision_order_map_repo import DecisionOrderMapRepository
from src.repositories.rate_limit_repository import RateLimitRepository
from src.repositories.circuit_breaker_repository import CircuitBreakerRepository
from src.repositories.balance_repository import BalanceRepository
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository
from src.repositories.log_repository import LogRepository
from src.repositories.perf_log_repository import PerfLogWriter
from src.repositories.trade_repo import TradeRepository
from src.adapters.market_data import MarketDataAdapter
from src.account.manager import AccountManager
from src.execution.execution_engine import ExecutionEngine
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.execution.risk_manager import RiskManager
from src.execution.risk_config import RiskConfig
from src.execution.worker_config import WorkerConfig

logger = logging.getLogger(__name__)

# 日志中最多展示的 decision_id 个数，避免 batch 过大时日志过长
MAX_LOG_IDS = 5


def _exchange_config_from_app_config(app_config):
    """PR15c：从 AppConfig 得到 paper 价格等，供 MarketDataAdapter。无则返回空 dict。"""
    if app_config is None:
        return {}
    return getattr(app_config, "_raw_config", {}) or {}


async def run_once(config: WorkerConfig, app_config=None) -> int:
    """单次轮询：拉取一批 RESERVED，并发执行（限制并发数），返回处理数量。app_config 可选，用于 CONFIG_SNAPSHOT 与 RiskConfig。PR15c：每任务内创建 account_manager/market_data_adapter 并注入 RiskManager。"""
    sem = asyncio.Semaphore(config.max_concurrency)
    exchange = PaperExchangeAdapter(filled=True)
    risk_config = RiskConfig.from_app_config(app_config) if app_config else None
    exchange_config = _exchange_config_from_app_config(app_config)

    try:
        async with get_db_session() as session:
            dom_repo = DecisionOrderMapRepository(session)
            rows = await dom_repo.list_reserved_ready(limit=config.batch_size)
            decision_ids = [r.decision_id for r in rows]
    except Exception as e:
        logger.exception("run_once_list_reserved_ready_failed")
        try:
            async with get_db_session() as err_session:
                log_repo = LogRepository(err_session)
                await log_repo.write(
                    "ERROR",
                    "execution_worker",
                    f"list_reserved_ready_failed: {type(e).__name__}: {str(e)[:500]}",
                    event_type="run_once_db_transient",
                    payload={"error_type": type(e).__name__},
                )
                await err_session.commit()
        except Exception:
            logger.exception("run_once_failed_to_log_db_error")
        return 0

    if not decision_ids:
        return 0

    decision_ids_sample = decision_ids[:MAX_LOG_IDS]
    total_count = len(decision_ids)
    logger.info(
        "batch_fetched sampled_decision_ids=%s total_count=%s batch_size=%s",
        decision_ids_sample,
        total_count,
        config.batch_size,
    )

    async def run_one(decision_id: str):
        async with sem:
            async with get_db_session() as session:
                dom_repo = DecisionOrderMapRepository(session)
                rate_limit_repo = RateLimitRepository(session)
                circuit_breaker_repo = CircuitBreakerRepository(session)
                balance_repo = BalanceRepository(session)
                market_data_adapter = MarketDataAdapter(
                    exchange_config=exchange_config,
                    exchange_adapter=exchange,
                    timeout_seconds=3.0,
                )
                account_manager = AccountManager(
                    exchange_adapter=exchange,
                    balance_repo=balance_repo,
                )
                risk = RiskManager(
                    risk_config=risk_config,
                    account_manager=account_manager,
                    market_data_adapter=market_data_adapter,
                )
                snapshot_repo = DecisionSnapshotRepository(session)
                log_repo = LogRepository(session)
                trade_repo = TradeRepository(session)
                def _alert_snapshot_failed(decision_id: str, strategy_id: str, reason: str) -> None:
                    logger.error(
                        "decision_snapshot_save_failed decision_id=%s strategy_id=%s reason=%s",
                        decision_id, strategy_id, reason,
                    )
                perf_writer = PerfLogWriter(get_db_session)
                engine = ExecutionEngine(
                    dom_repo,
                    exchange,
                    risk,
                    config=config,
                    app_config=app_config,
                    rate_limit_repo=rate_limit_repo,
                    circuit_breaker_repo=circuit_breaker_repo,
                    market_data_adapter=market_data_adapter,
                    snapshot_repo=snapshot_repo,
                    alert_callback=_alert_snapshot_failed,
                    log_repo=log_repo,
                    perf_writer=perf_writer,
                    trade_repo=trade_repo,
                )
                return await engine.execute_one(decision_id)

    results = await asyncio.gather(*[run_one(did) for did in decision_ids])
    done = sum(1 for r in results if r.get("status") not in ("skipped",))
    return done


async def main_loop() -> None:
    """主循环：每隔 poll_interval 拉取并执行。PR10：使用 load_app_config 并校验。"""
    app_config = load_app_config()
    setup_logging(
        log_level=app_config.logging.level,
        log_file=app_config.logging.file,
        log_to_database=app_config.logging.database,
    )
    database_config = {"url": app_config.database.url or "sqlite+aiosqlite:///./trading_system.db"}
    session_factory = await init_session_factory(database_config)
    set_session_factory(session_factory)

    config = WorkerConfig.from_app_config(app_config)
    logger.info(
        "worker_started poll_interval_seconds=%s batch_size=%s max_concurrency=%s max_attempts=%s backoff_seconds=%s",
        config.poll_interval_seconds,
        config.batch_size,
        config.max_concurrency,
        config.max_attempts,
        config.backoff_seconds,
    )

    while True:
        try:
            n = await run_once(config, app_config)
            if n > 0:
                logger.info(
                    "batch_processed processed_count=%s batch_size=%s",
                    n,
                    config.batch_size,
                )
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("worker_loop_error")
        await asyncio.sleep(config.poll_interval_seconds)


def main() -> None:
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
