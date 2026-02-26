"""
Phase1.1 C5：signal_rejection 表 Repository

因 PAUSED 拒绝信号时写入可审计记录，字段至少包含：策略 ID、signal_id、拒绝原因、时间戳。
"""
from datetime import datetime, timezone

from src.models.signal_rejection import SignalRejection, REASON_STRATEGY_PAUSED
from src.repositories.base import BaseRepository


class SignalRejectionRepository(BaseRepository[SignalRejection]):
    """signal_rejection 表访问；C5 信号拒绝可审计记录。"""

    async def create_rejection(
        self,
        strategy_id: str,
        reason: str,
        signal_id: str | None = None,
        created_at: datetime | None = None,
    ) -> SignalRejection:
        """写入一条因 PAUSED 拒绝信号的可审计记录。"""
        if created_at is None:
            created_at = datetime.now(timezone.utc)
        row = SignalRejection(
            strategy_id=strategy_id,
            signal_id=signal_id,
            reason=reason,
            created_at=created_at,
        )
        self.session.add(row)
        return row
