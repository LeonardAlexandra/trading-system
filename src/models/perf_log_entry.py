"""
Phase1.2 A3：perf_log 表（性能日志，1.2b）

仅结构定义，用于 ORM/只读层。蓝本 C.1。
- 与 log 表语义分离：perf_log 仅性能指标，log 为审计/操作/错误。
- 写入、查询、统计/聚合由 C7 实现，本模块不实现。
"""
from sqlalchemy import Column, DateTime, Integer, JSON, Numeric, String
from sqlalchemy.sql import func

from src.database.connection import Base


class PerfLogEntry(Base):
    """
    性能日志表（Phase1.2 蓝本 C.1）。仅性能指标（如 latency_ms, throughput_count）。
    与 log 表同库不同表，语义分离；查询须分页，单次上限由接口约定。
    """
    __tablename__ = "perf_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    component = Column(String(64), nullable=False)
    metric = Column(String(64), nullable=False)
    value = Column(Numeric(18, 6), nullable=False)
    tags = Column(JSON(), nullable=True)
