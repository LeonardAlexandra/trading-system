"""
Repository 基础抽象类（仅统一 CRUD 接口，不引入业务逻辑）
"""
from typing import Optional, TypeVar, Generic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase

T = TypeVar("T", bound=DeclarativeBase)


class BaseRepository(Generic[T]):
    """
    Repository 基础抽象类（统一为 async 风格）
    
    注意：
    - 所有方法均为 async 方法
    - 只提供基础 CRUD 操作，不包含业务逻辑
    - Repo 不管理 session 生命周期，由上层调用方负责
    """
    
    def __init__(self, session: AsyncSession):
        """
        初始化 Repository
        
        Args:
            session: 数据库会话（由上层传入，Repo 不管理生命周期）
        """
        self.session = session
    
    async def get_by_id(self, id: str) -> Optional[T]:
        """
        根据主键 ID 查询实体
        
        Args:
            id: 主键 ID
        
        Returns:
            实体对象，如果不存在则返回 None
        """
        # 子类需要实现具体的查询逻辑
        raise NotImplementedError("Subclass must implement get_by_id")
