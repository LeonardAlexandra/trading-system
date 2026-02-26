"""
依赖注入（最小实现，Repo 留空壳；PR15c 补齐 market_data_adapter / account_manager）
"""
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager

from src.adapters.market_data import MarketDataAdapter
from src.account.manager import AccountManager
from src.execution.exchange_adapter import PaperExchangeAdapter
from src.repositories.balance_repository import BalanceRepository

# SessionFactory（全局单例，在应用启动时通过 set_session_factory 设置）
AsyncSessionFactory: Optional[async_sessionmaker[AsyncSession]] = None


def set_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    """
    设置 SessionFactory（由 lifespan 调用，单一权威实现）
    
    Args:
        factory: 异步会话工厂
    """
    global AsyncSessionFactory
    AsyncSessionFactory = factory


@asynccontextmanager
async def get_db_session() -> AsyncSession:
    """
    每请求/每任务创建 session（异步上下文管理器，单一权威实现）
    
    使用方式：
        async with get_db_session() as session:
            # 使用 session
            ...
        # async with 自动负责 session 的关闭与回收，无需手动调用 close()
    
    注意：
        - 这是 @asynccontextmanager 装饰的异步上下文管理器，不是 FastAPI Depends 的 yield dependency
        - 不能作为 FastAPI Depends 使用，必须在代码中显式使用 async with 语法
        - SessionFactory 必须在应用启动时通过 set_session_factory() 初始化
        - 禁止使用 db_session = await get_db_session() 这种写法；只能 async with get_db_session() as session:
    """
    assert AsyncSessionFactory is not None, "SessionFactory not initialized. Call set_session_factory() in lifespan."
    
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        # 注意：async with AsyncSessionFactory() 已负责 session 的关闭与回收，无需额外调用 session.close()


class Dependencies:
    """依赖容器（所有字段显式声明，最小实现）"""
    
    def __init__(self):
        # Repository（显式声明，Phase 1.0 PR1 阶段留空壳）
        # 这些将在后续 PR 中实现
        self.dedup_signal_repo = None
        self.decision_order_map_repo = None
        self.trade_repo = None
        self.order_repo = None
        self.position_snapshot_repo = None
        self.log_repo = None
        
        # 其他依赖（Phase 1.0 PR1 阶段留空）
        # 这些将在后续 PR 中实现
        self.signal_receiver = None
        self.signal_parser = None
        self.strategy_executor = None
        self.risk_manager = None
        self.execution_engine = None
        self.order_manager = None
        self.position_manager = None
        self.account_manager = None
        self.market_data_adapter = None
        self.exchange_adapter = None


async def get_dependencies_with_session(config: Dict[str, Any], db_session: AsyncSession) -> Dependencies:
    """
    初始化依赖（使用传入的 session，最小实现）
    
    Args:
        config: 配置字典
        db_session: 数据库会话
    
    Returns:
        Dependencies: 依赖容器
    """
    deps = Dependencies()
    
    # Phase 1.0 PR1 阶段：Repository 留空壳，结构要有
    # 这些将在后续 PR 中实现
    # deps.dedup_signal_repo = DedupSignalRepository(db_session)
    # deps.decision_order_map_repo = DecisionOrderMapRepository(db_session)
    # deps.trade_repo = TradeRepository(db_session)
    # deps.order_repo = OrderRepository(db_session)
    # deps.position_snapshot_repo = PositionSnapshotRepository(db_session)
    # deps.log_repo = LogRepository(db_session)

    # PR15c：market_data_adapter / account_manager 必须非 None，可被独立调用与测试
    deps.exchange_adapter = PaperExchangeAdapter(filled=True)
    deps.market_data_adapter = MarketDataAdapter(
        exchange_config=config if isinstance(config, dict) else {},
        exchange_adapter=deps.exchange_adapter,
        timeout_seconds=3.0,
    )
    balance_repo = BalanceRepository(db_session)
    deps.account_manager = AccountManager(
        exchange_adapter=deps.exchange_adapter,
        balance_repo=balance_repo,
    )
    
    return deps
