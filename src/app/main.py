"""
FastAPI 应用入口（最小可运行版本）
"""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from contextlib import asynccontextmanager
import logging

from src.app.dependencies import set_session_factory
from src.app.routers import signal_receiver, resume, trace, health, dashboard, dashboard_page, audit, audit_page
from src.database.connection import init_session_factory, dispose_engine
from src.utils.logging import setup_logging
from src.config.app_config import load_app_config, app_config_to_legacy_dict

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    
    - 启动时：加载配置（PR10 统一 AppConfig + 校验）、初始化日志、初始化 SessionFactory
    - 关闭时：释放资源
    - Fail-fast：load_app_config() 校验失败会抛出 ConfigValidationError，不捕获，导致应用启动失败
    """
    # PR10 / Fail-fast：加载并校验配置，校验失败直接 raise，应用不启动
    app_config = load_app_config()
    config = app_config_to_legacy_dict(app_config)

    setup_logging(
        log_level=app_config.logging.level,
        log_file=app_config.logging.file,
        log_to_database=app_config.logging.database,
    )

    database_config = {"url": app_config.database.url}
    if not database_config.get("url"):
        database_config["url"] = "sqlite+aiosqlite:///./trading_system.db"
        logger.warning("No database.url configured, using default SQLite")

    session_factory = await init_session_factory(database_config)
    set_session_factory(session_factory)

    app.state.app_config = app_config
    app.state.config = config
    logger.info("Application started")
    
    yield
    
    # 关闭时清理
    logger.info("Application shutdown")
    # 释放数据库连接池
    await dispose_engine()
    logger.info("Database engine disposed")


def create_app() -> FastAPI:
    """
    应用工厂函数（支持测试环境配置注入）
    
    使用方式：
    - 生产环境：app = create_app()
    - 测试环境：在 monkeypatch.setenv(...) 后调用 create_app()
    
    约束：所有测试配置注入（TV_WEBHOOK_SECRET、DATABASE_URL 等）必须发生在 app/lifespan 初始化之前
    """
    app = FastAPI(
        title="Trading System API",
        version="0.1.0",
        lifespan=lifespan
    )
    
    # 根路径重定向到最小 Dashboard（Phase1.2 B2）
    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/dashboard", status_code=302)

    # 避免浏览器请求 /favicon.ico 时返回 404
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    # 健康检查路由
    @app.get("/healthz")
    async def health_check():
        """健康检查端点"""
        return {"status": "ok"}
    
    # Webhook 路由（PR4：验签 + 解析，不落库）
    app.include_router(signal_receiver.router)
    # B1：强校验恢复
    app.include_router(resume.router)
    # C2：全链路追溯
    app.include_router(trace.router)
    # C5/D8：健康仪表板与结构化健康观测
    app.include_router(health.router)
    app.include_router(health.metrics_router)
    # B1：最小 Dashboard API
    app.include_router(dashboard.router)
    # B2：最小 Dashboard 页面
    app.include_router(dashboard_page.router)
    # C8：审计查询（list_traces + 日志）
    app.include_router(audit.router)
    app.include_router(audit_page.router)

    return app


# 生产环境直接创建应用
app = create_app()
