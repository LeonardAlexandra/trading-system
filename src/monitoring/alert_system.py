"""
Phase1.2 C4：AlertSystem（蓝本 D.4）

evaluate_rules() 基于 get_metrics 与 check_all 结果评估，返回 list[Alert]；
触发时写 log（C3 LogRepository）且可选发邮件；同类型 1 分钟冷却；SMTP 失败仅写 log。
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.monitoring.models import Alert, HealthResult
from src.repositories.log_repository import LogRepository

# 告警冷却时间（秒），写死
ALERT_COOLDOWN_SECONDS = 60


def _eval_condition(condition: str, metrics: Dict[str, Any], health: HealthResult) -> bool:
    """简单条件求值：支持 db_ok == false, error_rate > 0.1 等。"""
    try:
        # 安全子集：仅允许比较 metrics / health 字段
        local = {
            "db_ok": health.db_ok,
            "exchange_ok": health.exchange_ok,
            "signals_received_count": metrics.get("signals_received_count", 0),
            "orders_executed_count": metrics.get("orders_executed_count", 0),
            "error_count": metrics.get("error_count", 0),
            "error_rate": metrics.get("error_rate", 0.0),
        }
        # 只允许 True/False 或数值比较，禁止任意代码
        c = condition.strip().lower()
        if c == "db_ok == false" or c == "not db_ok":
            return not local["db_ok"]
        if c == "db_ok == true":
            return local["db_ok"]
        if c == "exchange_ok == false" or c == "not exchange_ok":
            return not local["exchange_ok"]
        if c == "exchange_ok == true":
            return local["exchange_ok"]
        if "error_rate" in c and ">" in c:
            parts = c.split(">")
            if len(parts) == 2:
                thresh = float(parts[1].strip())
                return local["error_rate"] > thresh
        if "error_count" in c and ">" in c:
            parts = c.split(">")
            if len(parts) == 2:
                thresh = int(parts[1].strip())
                return local["error_count"] > thresh
        return False
    except Exception:
        return False


class AlertSystem:
    """
    告警规则评估。规则可配置；触发时写 LogRepository + 可选邮件；同类型 1 分钟冷却；SMTP 失败仅写 log。
    """

    def __init__(
        self,
        rules: List[Dict[str, Any]],
        *,
        send_email: Optional[Callable[[str, str, str], Any]] = None,
    ):
        """
        rules: 列表，每项至少 rule_id, condition, level, component, title, message_template（可选 details）。
        send_email: 可选 (to, subject, body) -> None；失败时降级为仅写 log，不抛。
        """
        self._rules = rules
        self._send_email = send_email
        self._last_fired: Dict[str, float] = {}  # rule_id -> timestamp，用于冷却

    async def evaluate_rules(
        self,
        session: AsyncSession,
        metrics: Dict[str, Any],
        health: HealthResult,
        log_repo: LogRepository,
    ) -> List[Alert]:
        """
        基于 metrics 与 health 评估规则；触发的规则在通过冷却后写入 log 并可选发邮件。
        返回本次触发的 Alert 列表（已去重冷却）。
        """
        now_ts = datetime.now(timezone.utc).timestamp()
        alerts: List[Alert] = []
        for rule in self._rules:
            rule_id = rule.get("rule_id") or "unknown"
            condition = rule.get("condition") or ""
            if not _eval_condition(condition, metrics, health):
                continue
            # 冷却：同 rule_id 1 分钟内只告警一次
            last = self._last_fired.get(rule_id, 0)
            if now_ts - last < ALERT_COOLDOWN_SECONDS:
                continue
            self._last_fired[rule_id] = now_ts

            level = rule.get("level") or "WARNING"
            component = rule.get("component") or "alert_system"
            title = rule.get("title") or rule_id
            message_template = rule.get("message_template") or title
            message = message_template.format(
                error_rate=metrics.get("error_rate", 0),
                error_count=metrics.get("error_count", 0),
                db_ok=health.db_ok,
                exchange_ok=health.exchange_ok,
            ) if "{" in message_template else message_template

            alert = Alert(
                alert_id=str(uuid.uuid4()),
                level=level,
                component=component,
                title=title,
                message=message,
                timestamp=datetime.now(timezone.utc),
                details={"rule_id": rule_id, "condition": condition},
            )
            alerts.append(alert)

            log_level = "ERROR" if level in ("CRITICAL", "IMPORTANT") else "WARNING"
            await log_repo.write(
                log_level,
                component,
                f"[{level}] {title}: {message}",
                event_type="alert_triggered",
                payload={"alert_id": alert.alert_id, "rule_id": rule_id, "condition": condition},
            )

            if self._send_email:
                try:
                    self._send_email(
                        to=rule.get("email_to") or "",
                        subject=f"[{level}] {title}",
                        body=message,
                    )
                except Exception:
                    # SMTP 失败降级：仅写 log（已在上方写入），不抛
                    pass

        return alerts
