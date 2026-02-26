import logging
import os
import sys
import tempfile
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional

# 默认日志目录：优先 LOG_DIR 环境变量，否则使用项目内可写目录
def _resolve_log_dir() -> Path:
    """解析日志目录：LOG_DIR > ./var/log/trading_system；创建失败时降级并打 warning"""
    preferred = os.environ.get("LOG_DIR")
    if preferred:
        base = Path(preferred)
    else:
        base = Path.cwd() / "var" / "log" / "trading_system"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except PermissionError:
        pass
    fallback = Path.cwd() / "var" / "log" / "trading_system"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
        logging.getLogger(__name__).warning(
            "Could not create log directory %s, using fallback: %s", base, fallback
        )
        return fallback
    except Exception:
        temp_log_dir = Path(tempfile.gettempdir()) / "trading_system_logs"
        temp_log_dir.mkdir(parents=True, exist_ok=True)
        logging.getLogger(__name__).warning(
            "Could not create log directory %s, using temp: %s", base, temp_log_dir
        )
        return temp_log_dir


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    log_to_database: bool = False
) -> None:
    """设置日志配置。日志目录可配置：LOG_DIR 环境变量；未设置时默认 ./var/log/trading_system；创建失败时降级到可写目录并打 warning。"""
    # 根日志配置
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # 文件处理器（如果配置）：目录使用 LOG_DIR 或可写降级路径
    if log_file:
        log_dir = _resolve_log_dir()
        log_name = Path(log_file).name
        actual_log_file = log_dir / log_name
        file_handler = RotatingFileHandler(
            str(actual_log_file),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d"
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # 数据库日志（如果配置，由 LogRepository 处理）
    if log_to_database:
        # 数据库日志处理器将在 LogRepository 中实现
        pass
