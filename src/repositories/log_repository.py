"""
Phase1.2 C3：审计/操作/错误日志 Repository（蓝本 C.3）

- write(level, component, message, event_type=None, payload=None)：写入前统一脱敏，落库 log 表。
- query(created_at_from=None, created_at_to=None, component=None, level=None, limit=100, offset=0)：分页查询，单次上限 1000。
- 不修改 A2 的 log 表结构；不与 perf_log 混合。
"""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.log_entry import LogEntry


# 单次查询上限（写死，蓝本 C.3）
QUERY_MAX_LIMIT = 1000

# 脱敏：敏感键名（payload 中这些 key 的值会被截断为 last4 或 ***）
_SENSITIVE_KEYS = frozenset(
    {"api_key", "apikey", "api-key", "token", "access_token", "bearer", "password", "secret", "authorization"}
)

# 脱敏：message 中匹配 键=值 或 键:值 的模式，值替换为 ***last4
_MESSAGE_SENSITIVE_PATTERN = re.compile(
    r"\b(api_key|apikey|api-key|token|access_token|password|secret|authorization)\s*[:=]\s*[\"']?([^\"'\s]{5,})[\"']?",
    re.IGNORECASE,
)


def _redact_value(value: Any) -> str:
    """单个值脱敏：超过 4 字符则 ***last4，否则 ***。"""
    if value is None:
        return "***"
    s = str(value).strip()
    if len(s) <= 4:
        return "***"
    return "***" + s[-4:]


def _desensitize_message(message: str) -> str:
    """对 message 字符串脱敏：敏感键=值 替换为 ***last4。"""
    if not message:
        return message

    def repl(m: re.Match) -> str:
        key, val = m.group(1), m.group(2)
        return f"{key}=***{val[-4:] if len(val) >= 4 else '***'}"

    return _MESSAGE_SENSITIVE_PATTERN.sub(repl, message)


def _desensitize_payload(obj: Any) -> Any:
    """对 payload（dict/list/值）递归脱敏；敏感键的值替换为 ***last4。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _desensitize_payload(v) if k.lower() not in _SENSITIVE_KEYS else _redact_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_desensitize_payload(x) for x in obj]
    return obj


class LogRepository:
    """
    审计/操作/错误日志仓储。写入前统一脱敏；查询分页，单次上限 QUERY_MAX_LIMIT。
    level 枚举：INFO, WARNING, ERROR, AUDIT（蓝本 C.3）。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(
        self,
        level: str,
        component: str,
        message: str,
        *,
        event_type: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        写入一条 log。写入前对 message 与 payload 统一脱敏（禁止完整 API Key/token/密码）。
        """
        msg_safe = _desensitize_message(message)
        payload_safe = _desensitize_payload(payload) if payload is not None else None
        entry = LogEntry(
            component=component,
            level=level,
            message=msg_safe,
            event_type=event_type,
            payload=payload_safe,
        )
        self.session.add(entry)
        await self.session.flush()

    async def query(
        self,
        *,
        created_at_from: Optional[datetime] = None,
        created_at_to: Optional[datetime] = None,
        component: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LogEntry]:
        """
        分页查询。limit 上限为 QUERY_MAX_LIMIT（1000），超过则截断。
        支持按 created_at 范围、component、level 过滤。
        """
        limit = min(limit, QUERY_MAX_LIMIT)
        stmt = select(LogEntry).order_by(LogEntry.created_at.desc())
        if created_at_from is not None:
            stmt = stmt.where(LogEntry.created_at >= created_at_from)
        if created_at_to is not None:
            stmt = stmt.where(LogEntry.created_at <= created_at_to)
        if component is not None:
            stmt = stmt.where(LogEntry.component == component)
        if level is not None:
            stmt = stmt.where(LogEntry.level == level)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
