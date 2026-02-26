"""
Orders Repository（订单表）
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.order import Order
from src.repositories.base import BaseRepository


class OrdersRepository(BaseRepository[Order]):
    """订单表 Repository"""
    
    async def create(self, order: Order) -> Order:
        """
        创建订单记录
        
        Args:
            order: Order 对象
        
        Returns:
            Order 对象
        
        Note:
            - 不在这里 commit，由上层 session 生命周期管理
        """
        self.session.add(order)
        # 注意：不在这里 commit，由上层 session 生命周期管理
        return order

    async def update(self, order: Order) -> Order:
        """
        PR12：更新订单（如状态、filled_quantity）。由上层负责 commit。
        """
        self.session.add(order)
        return order

    async def get_by_local_order_id(self, local_order_id: str) -> Optional[Order]:
        """
        根据本地订单号查询订单
        
        Args:
            local_order_id: 本地订单号（对应 Order.order_id）
        
        Returns:
            Order 对象，如果不存在则返回 None
        """
        stmt = select(Order).where(Order.order_id == local_order_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def list_by_decision_id(self, decision_id: str) -> list[Order]:
        """
        根据 decision_id 查询订单列表
        
        Args:
            decision_id: 决策 ID
        
        Returns:
            Order 对象列表
        """
        stmt = select(Order).where(Order.decision_id == decision_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
