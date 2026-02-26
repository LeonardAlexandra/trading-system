"""
Phase1.2 C4：HealthChecker（蓝本 D.4）

check_all() 返回 HealthResult：至少 db_ok, exchange_ok, strategy_status。
db_ok：真实 DB 连通性（如 SELECT 1）；exchange_ok：真实调用 ExchangeAdapter 可达性；不修改业务逻辑。
"""
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.execution.exchange_adapter import ExchangeAdapter
from src.models.strategy_runtime_state import StrategyRuntimeState
from src.monitoring.models import HealthResult


class HealthChecker:
    """
    组件健康检查。仅做只读检查，不修改业务/风控/执行逻辑。
    """

    async def check_all(
        self,
        session: AsyncSession,
        exchange_adapter: ExchangeAdapter,
    ) -> HealthResult:
        """
        db_ok：执行简单查询验证连通性；exchange_ok：调用 adapter.get_account_info() 验证可达性；
        strategy_status：从 strategy_runtime_state 表读取各策略状态。
        """
        db_ok = await self._check_db(session)
        exchange_ok = await self._check_exchange(exchange_adapter)
        strategy_status = await self._get_strategy_status(session)
        return HealthResult(db_ok=db_ok, exchange_ok=exchange_ok, strategy_status=strategy_status)

    async def _check_db(self, session: AsyncSession) -> bool:
        """真实 DB 连通性：执行 SELECT 1（或等价）。"""
        try:
            await session.execute(text("SELECT 1"))
            await session.flush()
            return True
        except Exception:
            return False

    async def _check_exchange(self, adapter: ExchangeAdapter) -> bool:
        """真实交易所/适配器可达性：调用 get_account_info()，异常则 False。"""
        try:
            await adapter.get_account_info()
            return True
        except Exception:
            return False

    async def _get_strategy_status(self, session: AsyncSession) -> Dict[str, Any]:
        """从 strategy_runtime_state 表读取 strategy_id -> status，表达「当前策略是否正常运行」。"""
        from sqlalchemy import select
        stmt = select(StrategyRuntimeState.strategy_id, StrategyRuntimeState.status)
        result = await session.execute(stmt)
        rows = result.all()
        by_id = {str(r.strategy_id): r.status for r in rows}
        return {
            "strategies": by_id,
            "summary": "ok" if by_id else "no_strategies",
        }
