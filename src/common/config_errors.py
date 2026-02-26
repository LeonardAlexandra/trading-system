"""
配置校验异常（PR10：统一 reason_code + message，供 webhook 返回 422）
"""
from typing import Optional


class ConfigValidationError(Exception):
    """配置校验失败，携带稳定 reason_code 与人类可读 message。"""

    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        self.message = message
        super().__init__(message)
