"""
数据库连接管理（SessionFactory 模式）
"""
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine, AsyncEngine
from sqlalchemy.orm import declarative_base
from sqlalchemy import event
from contextlib import asynccontextmanager

# SQLAlchemy Base（用于定义模型）
Base = declarative_base()

# 数据库引擎（模块级变量，用于在 shutdown 时释放连接池）
_engine: Optional[AsyncEngine] = None


def _install_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Apply conservative SQLite pragmas to reduce lock contention in tests/runtime."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            # WAL improves read/write concurrency for file-backed SQLite DBs.
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


async def init_session_factory(database_config: Dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """
    初始化 SessionFactory
    
    Args:
        database_config: 数据库配置字典，包含 url, pool_size, max_overflow, pool_recycle
    
    Returns:
        async_sessionmaker[AsyncSession]: 异步会话工厂
    """
    global _engine
    
    database_url = database_config.get("url")
    if not database_url:
        raise ValueError("database.url is required")
    
    # URL scheme 校验：Postgres 必须使用 asyncpg（项目使用 create_async_engine）
    if database_url.startswith("postgresql://") or database_url.startswith("postgresql+psycopg2://"):
        raise ValueError(
            "PostgreSQL 必须使用异步驱动。请将 DATABASE_URL 改为 postgresql+asyncpg://user:pass@host:5432/dbname"
        )
    
    # SQLite 必须使用 aiosqlite（create_async_engine 需要异步驱动）
    if database_url.startswith("sqlite://") and "+aiosqlite" not in database_url:
        database_url = "sqlite+aiosqlite://" + database_url[len("sqlite://"):]
    
    # 判断是否为 SQLite（SQLite 不支持连接池参数）
    is_sqlite = database_url.startswith("sqlite")
    
    # 创建异步引擎（保存为模块级变量）
    if is_sqlite:
        # SQLite 不需要连接池参数
        _engine = create_async_engine(
            database_url,
            connect_args={"timeout": 30},
            echo=False,  # 生产环境设为 False
        )
        _install_sqlite_pragmas(_engine)
    else:
        # PostgreSQL 等其他数据库使用连接池参数
        _engine = create_async_engine(
            database_url,
            pool_size=database_config.get("pool_size", 5),
            max_overflow=database_config.get("max_overflow", 10),
            pool_recycle=database_config.get("pool_recycle", 3600),
            echo=False,  # 生产环境设为 False
        )
    
    # 创建异步会话工厂
    session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    return session_factory


def get_engine() -> Optional[AsyncEngine]:
    """
    获取数据库引擎（用于在 shutdown 时释放连接池）
    
    Returns:
        Optional[AsyncEngine]: 数据库引擎，如果未初始化则返回 None
    """
    return _engine


async def dispose_engine() -> None:
    """
    释放数据库引擎连接池（在应用 shutdown 时调用）
    """
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
