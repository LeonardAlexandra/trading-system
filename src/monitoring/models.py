"""
Phase1.2 C4：监控与告警数据结构（蓝本 D.4）

HealthResult：至少 db_ok, exchange_ok, strategy_status
Alert：至少 alert_id, level, component, title, message, timestamp, details
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class HealthResult:
    """健康检查结果（蓝本 D.4）。"""
    db_ok: bool
    exchange_ok: bool
    strategy_status: Dict[str, Any]  # strategy_id -> status 或聚合信息


@dataclass
class Alert:
    """单条告警（蓝本 D.4；触发时写 log 且可选发邮件）。"""
    alert_id: str
    level: str  # CRITICAL | IMPORTANT | WARNING | INFO
    component: str
    title: str
    message: str
    timestamp: datetime
    details: Optional[Dict[str, Any]] = None
