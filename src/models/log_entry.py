"""
Phase1.2 A2：log 表（审计/操作/错误日志）

仅结构定义，用于 ORM/只读层。蓝本 C.1。
- level 仅允许：INFO, WARNING, ERROR, AUDIT（C.3）
- 脱敏、LogRepository、写入与查询由 C3 实现，本模块不实现。
"""
from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.sql import func

from src.database.connection import Base


class LogEntry(Base):
    """
    审计/操作/错误日志表（Phase1.2 蓝本 C.1）。
    level 枚举：INFO, WARNING, ERROR, AUDIT。分页查询须带 limit/offset，单次上限由接口约定（如 1000 条）。
    """
    __tablename__ = "log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    component = Column(String(64), nullable=False)
    level = Column(String(16), nullable=False)  # INFO | WARNING | ERROR | AUDIT
    message = Column(Text(), nullable=False)
    event_type = Column(String(32), nullable=True)
    payload = Column(JSON(), nullable=True)
