"""
Phase1.1 D4：强校验必然失败场景 fixture（B1 负向测试）

构造「不可恢复」状态，使 POST /strategy/{id}/resume 强校验必然不通过；
不依赖生产数据，用于断言 400 + 标准 diff。
"""
from src.models.strategy_runtime_state import STATUS_RUNNING

# 策略为 RUNNING 时，强校验项 state_is_paused 必然失败（期望 PAUSED，实际 RUNNING）
D4_STRATEGY_ID_CHECK_FAIL = "D4_RESUME_FAIL_STRAT"


def strategy_id_for_resume_fail() -> str:
    return D4_STRATEGY_ID_CHECK_FAIL


def status_that_fails_resume_check() -> str:
    """返回使 state_is_paused 校验失败的状态（非 PAUSED）。"""
    return STATUS_RUNNING
