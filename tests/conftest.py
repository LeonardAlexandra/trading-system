"""
Pytest 配置和共享 fixtures。
PR15a：注册 pytest.mark.external，默认不跑需外网的测试。
"""
import os
import pytest


def pytest_configure(config):
    """注册自定义 mark。"""
    config.addinivalue_line(
        "markers",
        "external: mark test as requiring external network (OKX demo); skip by default, run with RUN_EXTERNAL_OKX_TESTS=true",
    )


def pytest_collection_modifyitems(config, items):
    """PR15a：默认跳过 @pytest.mark.external 测试，除非 RUN_EXTERNAL_OKX_TESTS=true。"""
    run_external = config.getoption("run_external_okx_tests", False) or (
        (os.environ.get("RUN_EXTERNAL_OKX_TESTS") or "").strip().lower() == "true"
    )
    if run_external:
        return
    skip_external = pytest.mark.skip(reason="external OKX tests disabled; set RUN_EXTERNAL_OKX_TESTS=true to run")
    for item in items:
        if "external" in item.keywords:
            item.add_marker(skip_external)


def pytest_addoption(parser):
    parser.addoption(
        "--run-external-okx-tests",
        action="store_true",
        default=False,
        help="Run tests marked as external (OKX demo network)",
    )


import tempfile
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from src.database.connection import Base
from src.app.dependencies import set_session_factory


@pytest.fixture(scope="function")
async def db_session_factory():
    """
    创建测试数据库 SessionFactory（每个测试函数一个独立的数据库）
    
    使用 SQLite 内存数据库，测试结束后自动清理
    """
    # 创建临时 SQLite 数据库文件（或使用内存数据库）
    # 使用内存数据库更快速，但每个测试独立
    database_url = "sqlite+aiosqlite:///:memory:"
    
    # 创建异步引擎
    engine = create_async_engine(
        database_url,
        echo=False,
        poolclass=StaticPool,  # SQLite 内存数据库使用静态连接池
        connect_args={"check_same_thread": False},  # SQLite 允许多线程
    )
    
    # 创建所有表（使用 Base.metadata.create_all）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # 创建会话工厂
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    # 设置到 dependencies 模块（供 get_db_session 使用）
    set_session_factory(session_factory)
    
    yield session_factory
    
    # 清理：删除所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    # 释放引擎
    await engine.dispose()


@pytest.fixture
async def db_session(db_session_factory):
    """
    提供测试用的数据库 session（使用 get_db_session 模式）
    
    注意：这个 fixture 不直接返回 session，而是提供一个可以使用的 session 上下文
    测试中应该使用 async with get_db_session() as session: 模式
    """
    from src.app.dependencies import get_db_session
    
    async with get_db_session() as session:
        yield session
