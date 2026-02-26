"""
Phase1.1 A1：strategy_runtime_state 表 ORM 模型（互斥锁字段 + TTL 支撑）

仅提供字段定义与 C1 ReconcileLock 对接所需的结构。
锁是否有效由「当前时间与 locked_at + lock_ttl_seconds 比较」及「lock_holder_id 一致性」判定。
TTL 默认 30 秒；所有锁均可通过 TTL 过期或显式释放失效，无无限期锁。
本模块不实现任何加锁/解锁逻辑，由 C1 基于单条原子 UPDATE 实现。
"""
from sqlalchemy import Column, String, DateTime, Integer, text
from src.database.connection import Base

# C5：策略运行时状态枚举；PAUSED 仅能通过 B1 resume 恢复
STATUS_RUNNING = "RUNNING"
STATUS_PAUSED = "PAUSED"


class StrategyRuntimeState(Base):
    """
    策略运行时状态表（A1：锁与 TTL 字段；C5：status 挂起状态）。

    锁与 TTL 语义（Source of Truth）：
    - 锁过期条件：now() > locked_at + lock_ttl_seconds
    - 默认 TTL：30 秒（lock_ttl_seconds=30）
    - 锁归属与有效期仅由 DB 状态决定；崩溃恢复仅依赖 DB 与 TTL，无外部协调器
    - C5：status 为 PAUSED 时拒绝新信号，仅 B1 resume 可恢复为 RUNNING。
    """

    __tablename__ = "strategy_runtime_state"

    strategy_id = Column(String(100), primary_key=True)
    status = Column(
        String(20),
        nullable=False,
        server_default=text("'RUNNING'"),
        comment="C5：RUNNING/PAUSED；仅 B1 resume 可恢复为 RUNNING",
    )
    lock_holder_id = Column(
        String(200),
        nullable=True,
        comment="锁持有者标识；NULL 表示无锁",
    )
    locked_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="锁获取时间；过期判定：now() > locked_at + lock_ttl_seconds",
    )
    lock_ttl_seconds = Column(
        Integer,
        nullable=False,
        server_default=text("30"),
        comment="锁 TTL（秒），默认 30；超过 TTL 未续期视为失效",
    )
