"""
Alembic 环境配置（支持异步 SQLAlchemy）
"""
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# 导入配置
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（从项目根目录加载）
project_root = Path(__file__).parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(project_root))

# 导入 Base 和所有模型（确保 Alembic 能够检测到表结构）
from src.database.connection import Base
from src.models import DedupSignal, DecisionOrderMap, Order  # 只导入 PR2 要求的三个模型

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从环境变量或配置文件中获取数据库 URL
database_url = os.getenv("DATABASE_URL")
if database_url:
    # sqlite+aiosqlite 需转为 sqlite:// 以兼容部分 Alembic 操作；postgresql+asyncpg 保留以使用 async 迁移
    if database_url.startswith("sqlite+aiosqlite"):
        database_url = database_url.replace("sqlite+aiosqlite://", "sqlite:///")
    config.set_main_option("sqlalchemy.url", database_url)
else:
    # 如果环境变量不存在，检查 alembic.ini 中的 URL 是否为占位符
    current_url = config.get_main_option("sqlalchemy.url", "")
    if current_url == "driver://user:pass@localhost/dbname" or not current_url:
        raise ValueError(
            "DATABASE_URL 环境变量未设置。请创建 .env 文件并设置 DATABASE_URL，"
            "例如：DATABASE_URL=sqlite:///./trading_system.db"
        )

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # 对于异步数据库，使用异步迁移
    database_url = config.get_main_option("sqlalchemy.url", "")
    if database_url.startswith("sqlite+aiosqlite") or database_url.startswith("postgresql+asyncpg"):
        import asyncio
        asyncio.run(run_async_migrations())
    else:
        # 同步数据库使用传统方式
        connectable = config.attributes.get("connection", None)
        if connectable is None:
            from sqlalchemy import engine_from_config
            connectable = engine_from_config(
                config.get_section(config.config_ini_section, {}),
                prefix="sqlalchemy.",
                poolclass=pool.NullPool,
            )

        with connectable.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata
            )

            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
