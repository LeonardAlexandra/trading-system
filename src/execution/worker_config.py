"""
执行 Worker 配置（PR7：poll_interval、batch_size、max_concurrency、max_attempts、backoff_seconds）
"""
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class WorkerConfig:
    """Worker 与执行引擎重试相关配置，支持环境变量覆盖。"""
    poll_interval_seconds: float = 1.0
    batch_size: int = 10
    max_concurrency: int = 5
    max_attempts: int = 3
    backoff_seconds: List[int] = field(default_factory=lambda: [1, 5, 30])

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        """从环境变量读取，解析失败用默认值，不抛异常。"""
        def _float(key: str, default: float) -> float:
            try:
                return float(os.environ.get(key, default))
            except (TypeError, ValueError):
                return default

        def _int(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, default))
            except (TypeError, ValueError):
                return default

        def _backoff(key: str, default: List[int]) -> List[int]:
            raw = os.environ.get(key, "")
            if not raw:
                return default
            try:
                return [int(x.strip()) for x in raw.split(",") if x.strip()]
            except (TypeError, ValueError):
                return default

        return cls(
            poll_interval_seconds=_float("EXEC_POLL_INTERVAL", 1.0),
            batch_size=_int("EXEC_BATCH_SIZE", 10),
            max_concurrency=_int("EXEC_MAX_CONCURRENCY", 5),
            max_attempts=_int("EXEC_MAX_ATTEMPTS", 3),
            backoff_seconds=_backoff("EXEC_BACKOFF_SECONDS", [1, 5, 30]),
        )

    @classmethod
    def from_app_config(cls, app_config: "AppConfig") -> "WorkerConfig":
        """从 PR10 统一 AppConfig 构建（来源统一）。"""
        from src.config.app_config import AppConfig as AppConfigType
        ex = app_config.execution
        return cls(
            poll_interval_seconds=ex.poll_interval_seconds,
            batch_size=ex.batch_size,
            max_concurrency=ex.max_concurrency,
            max_attempts=ex.max_attempts,
            backoff_seconds=ex.backoff_seconds,
        )
