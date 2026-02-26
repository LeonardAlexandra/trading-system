"""
DecisionOrderMap 状态常量定义

状态流转语义（PR6 最小状态机 + Phase1.1 C2 两阶段）：
- RESERVED: 已占位，等待拉取执行
- SUBMITTING: 已被 worker 抢占，正在调用交易所（事务A 后）
- PENDING_EXCHANGE: Phase1.1 C2 阶段1 持锁写入，表示「待下单/交易所请求进行中」；对账/恢复可据此识别未落库意图
- PLACED: 已提交到交易所，等待成交（交易所下单成功，但未成交）
- FILLED: 已成交
- FAILED: 下单失败或风控拒绝
- TIMEOUT: 交易所超时
- UNKNOWN: 未知状态
"""

# DecisionOrderMap 状态枚举值
RESERVED = "RESERVED"  # 已占位，等待下单
SUBMITTING = "SUBMITTING"  # 已抢占，正在提交交易所（PR6）
PENDING_EXCHANGE = "PENDING_EXCHANGE"  # C2 阶段1：持锁写入，交易所请求进行中/待落库，可被对账识别
PLACED = "PLACED"  # 已提交到交易所，等待成交
FILLED = "FILLED"  # 已成交
FAILED = "FAILED"  # 下单失败
TIMEOUT = "TIMEOUT"  # 交易所超时
UNKNOWN = "UNKNOWN"  # 未知状态

# 所有有效状态列表
ALL_STATUSES = [RESERVED, SUBMITTING, PENDING_EXCHANGE, PLACED, FILLED, FAILED, TIMEOUT, UNKNOWN]

# 默认状态
DEFAULT_STATUS = RESERVED
