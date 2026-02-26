# Phase1.0 状态机不变量（State Machine Invariants）

**版本**: v1.0  
**创建日期**: 2026-02-03  
**目的**: 定义交易系统必须满足的状态不变量，确保系统正确性和一致性

---

## 不变量说明

本文档列出 Phase1.0 交易系统必须满足的状态不变量。每条不变量包括：
- **不变量描述**: 系统必须始终满足的条件
- **代码保障**: 由哪些代码/机制保证
- **测试验证**: 哪些测试在验证它
- **违反后果**: 如果违反会导致什么问题

---

## 一、信号去重不变量

### INV-1: 同一 signal_id 只能产生一次有效下单

**描述**: 
- 相同 `signal_id` 的信号只能被处理一次，产生一个 `decision_id` 和一次下单
- 重复信号必须被拒绝，不产生新的决策和订单

**代码保障**:
- `src/models/dedup_signal.py`: `signal_id` 为 PRIMARY KEY（唯一约束）
- `src/repositories/dedup_signal_repo.py:try_insert()`: 使用 `INSERT ... ON CONFLICT DO NOTHING` 或唯一约束检查
- `src/application/signal_service.py:handle_tradingview_signal()`: 去重检查返回 `duplicate_ignored`

**测试验证**:
- `tests/unit/repositories/test_dedup_signal_repo.py`: 测试 `try_insert()` 去重逻辑
- `tests/integration/test_tradingview_webhook.py`: 测试重复信号返回 `duplicate_ignored`

**违反后果**: 
- 重复信号可能导致重复下单，造成资金风险
- 系统无法正确追踪信号处理历史

---

### INV-2: signal_id 生成必须稳定可复现

**描述**:
- 相同 webhook payload 必须生成相同的 `signal_id`
- `signal_id` 生成算法必须确定性（不依赖时间戳、随机数等非确定性因素）

**代码保障**:
- `src/adapters/tradingview_adapter.py:parse_signal()`: 优先使用 payload 中的 `signal_id`，否则基于 payload 内容生成稳定哈希

**测试验证**:
- `tests/integration/test_tradingview_webhook.py`: 测试相同 payload 生成相同 `signal_id`

**违反后果**:
- 去重失效，相同事件被重复处理
- 无法正确追踪信号历史

---

## 二、决策订单映射不变量

### INV-3: 同一 decision_id 只能产生一次有效下单

**描述**:
- 相同 `decision_id` 的决策只能被下单一次
- 重复执行相同 `decision_id` 必须幂等返回，不产生重复订单

**代码保障**:
- `src/models/decision_order_map.py`: `decision_id` 为 PRIMARY KEY（唯一约束）
- `src/repositories/decision_order_map_repo.py:try_claim_reserved()`: 原子抢占，仅当 `status=RESERVED` 时更新为 `SUBMITTING`
- `src/execution/execution_engine.py:execute()`: 检查 `decision_id` 是否已存在，已存在则幂等返回

**测试验证**:
- `tests/unit/repositories/test_decision_order_map_repo.py`: 测试 `try_claim_reserved()` 原子抢占
- `tests/integration/test_execution_events.py`: 测试相同 `decision_id` 重复执行幂等返回

**违反后果**:
- 重复下单导致资金风险
- 系统无法正确追踪订单执行历史

---

### INV-4: DecisionOrderMap 状态转换必须遵循合法路径

**描述**:
- 状态转换路径: `RESERVED → SUBMITTING → (PLACED | FILLED | FAILED | TIMEOUT | UNKNOWN)`
- 不允许跳过中间状态（如 `RESERVED` 直接到 `FILLED`）
- 不允许反向转换（如 `FILLED` 回到 `RESERVED`）

**代码保障**:
- `src/models/decision_order_map_status.py`: 状态常量定义
- `src/repositories/decision_order_map_repo.py:try_claim_reserved()`: 仅当 `status=RESERVED` 时更新为 `SUBMITTING`
- `src/execution/execution_engine.py:execute()`: 状态更新逻辑遵循状态机

**测试验证**:
- `tests/integration/test_execution_events.py`: 测试状态转换路径
- `tests/unit/repositories/test_decision_order_map_repo.py`: 测试状态更新

**违反后果**:
- 状态不一致导致系统无法正确追踪订单状态
- 可能导致重复下单或订单丢失

---

### INV-5: FILLED 事件必须幂等

**描述**:
- 相同 `decision_id` 的 FILLED 事件只能被处理一次
- 重复处理 FILLED 事件必须幂等（不重复更新持仓、不重复记录交易）

**代码保障**:
- `src/execution/execution_engine.py:execute()`: 检查 `decision_id` 是否已为 `FILLED`，已 FILLED 则幂等返回
- `src/repositories/position_repository.py`: 持仓更新基于 `trade_id` 或 `decision_id` 去重

**测试验证**:
- `tests/integration/test_execution_events.py`: 测试 FILLED 事件幂等处理

**违反后果**:
- 重复更新持仓导致持仓数据错误
- 重复记录交易导致财务数据错误

---

### INV-6: 失败订单不得更新持仓

**描述**:
- 状态为 `FAILED`、`TIMEOUT`、`UNKNOWN` 的订单不得更新 `position_snapshot`
- 只有 `FILLED` 状态的订单才能更新持仓

**代码保障**:
- `src/execution/execution_engine.py:execute()`: 仅在订单 `FILLED` 时调用 `position_repo.update()`
- `src/repositories/position_repository.py`: 持仓更新逻辑检查订单状态

**测试验证**:
- `tests/integration/test_execution_events.py`: 测试失败订单不更新持仓
- `tests/integration/test_risk_manager.py`: 测试风控拒绝不更新持仓

**违反后果**:
- 持仓数据错误，导致风控判断错误
- 财务数据不一致

---

## 三、事务不变量

### INV-7: 两段式幂等流程必须原子性

**描述**:
- 事务A（占位）: `RESERVED` 状态创建必须原子性（PRIMARY KEY 唯一约束）
- 事务B（落库）: 订单、交易、持仓更新必须在同一事务中完成
- 交易所下单（不在事务内）: 下单失败不影响占位记录

**代码保障**:
- `src/application/signal_service.py:handle_tradingview_signal()`: 事务A 创建 `RESERVED` 记录
- `src/execution/execution_engine.py:execute()`: 事务B 更新状态、落库订单/交易/持仓
- `src/app/dependencies.py:get_db_session()`: `async with` 上下文管理器保证事务边界

**测试验证**:
- `tests/integration/test_execution_events.py`: 测试两段式幂等流程
- `tests/integration/test_execution_worker.py`: 测试事务边界

**违反后果**:
- 数据不一致（订单已下单但未落库，或订单已落库但未下单）
- 无法正确追踪订单执行状态

---

### INV-8: 异常状态必须落库（独立 session commit）

**描述**:
- 当标记 `decision_order_map.status` 为 `TIMEOUT`、`FAILED`、`UNKNOWN` 时，必须保证该更新不会被 request-level rollback 回滚
- 必须使用独立 session 小事务显式 commit，确保异常状态能够持久化

**代码保障**:
- `src/execution/execution_engine.py:execute()`: 异常分支使用独立 `get_db_session()` 显式 commit
- 异常状态更新不在主事务中，避免被 rollback

**测试验证**:
- `tests/integration/test_execution_events.py`: 测试异常状态落库
- `tests/integration/test_execution_worker.py`: 测试超时状态持久化

**违反后果**:
- 异常状态丢失，无法正确恢复
- 重试机制失效，订单状态无法追踪

---

## 四、风控不变量

### INV-9: 风控拒绝的决策不得下单

**描述**:
- `RiskManager.check()` 返回 `allowed=False` 的决策不得调用 `ExchangeAdapter.create_order()`
- 风控拒绝必须记录拒绝原因（`reason_code`）

**代码保障**:
- `src/execution/execution_engine.py:execute()`: 风控检查失败时直接返回，不调用 `exchange_adapter.create_order()`
- `src/repositories/execution_event_repository.py`: 记录 `RISK_REJECTED` 事件

**测试验证**:
- `tests/integration/test_risk_manager.py`: 测试风控拒绝不下单
- `tests/integration/test_execution_events.py`: 测试风控拒绝事件记录

**违反后果**:
- 违反风控规则，可能导致资金风险
- 无法追踪风控拒绝原因

---

### INV-10: 策略级仓位隔离

**描述**:
- 不同 `strategy_id` 的仓位必须隔离
- 策略A的仓位不得影响策略B的风控判断
- 持仓查询必须按 `strategy_id` 过滤

**代码保障**:
- `src/repositories/position_repository.py:get()`: 查询时按 `strategy_id` 过滤
- `src/models/position.py`: `position_snapshot` 表唯一约束包含 `strategy_id`
- `src/execution/risk_manager.py:check()`: 风控检查按 `strategy_id` 查询仓位

**测试验证**:
- `tests/integration/test_pr11_strategy_isolation.py`: 测试策略隔离

**违反后果**:
- 策略间相互影响，风控判断错误
- 无法正确追踪各策略的仓位和风险

---

## 五、执行不变量

### INV-11: Paper 模式下单即成交

**描述**:
- Phase1.0 Paper 模式下，`ExchangeAdapter.create_order()` 必须立即返回 `FILLED` 状态
- `create_order()` 返回的订单必须包含 `filled_trade` 信息
- 事务B 必须直接写入 `trade` 记录

**代码保障**:
- `src/execution/exchange_adapter.py:PaperExchangeAdapter.__init__(filled=True)`: Paper 模式立即成交
- `src/execution/execution_engine.py:execute()`: 事务B 直接写入 `trade` 记录

**测试验证**:
- `tests/integration/test_execution_events.py`: 测试 Paper 模式立即成交
- `tests/unit/execution/test_okx_adapter.py`: 测试 Paper 模式实现

**违反后果**:
- 订单状态不一致，系统无法正确追踪订单执行
- 持仓更新延迟，风控判断错误

---

### INV-12: client_order_id 必须等于 decision_id

**描述**:
- 交易所下单时，`client_order_id` 必须等于 `decision_id`
- 这保证了交易所层面的幂等性（相同 `client_order_id` 不会重复下单）

**代码保障**:
- `src/execution/execution_engine.py:execute()`: 调用 `exchange_adapter.create_order(client_order_id=decision_id)`
- `src/execution/exchange_adapter.py:create_order()`: 使用 `client_order_id` 参数

**测试验证**:
- `tests/integration/test_execution_events.py`: 测试 `client_order_id=decision_id`
- `tests/unit/execution/test_okx_adapter.py`: 测试 `client_order_id` 传递

**违反后果**:
- 交易所层面无法保证幂等性，可能导致重复下单
- 无法正确追踪订单与决策的映射关系

---

## 六、Session 管理不变量

### INV-13: 每请求必须创建新的 session

**描述**:
- 每个 HTTP 请求必须创建新的数据库 session
- 不得在全局常驻单个 session
- Session 必须在请求结束时自动关闭

**代码保障**:
- `src/app/dependencies.py:get_db_session()`: `@asynccontextmanager` 异步上下文管理器
- `src/app/routers/signal_receiver.py:143`: 使用 `async with get_db_session() as session:`
- `src/app/main.py:lifespan()`: SessionFactory 初始化，不创建全局 session

**测试验证**:
- `tests/integration/test_app_startup_config_injection.py`: 测试 SessionFactory 初始化
- `tests/integration/test_tradingview_webhook.py`: 测试每请求创建 session

**违反后果**:
- Session 泄漏，数据库连接耗尽
- 事务边界混乱，数据不一致

---

## 七、不变量验证总结

### 7.1 不变量分类

| 类别 | 不变量数量 | 关键不变量 |
|------|----------|-----------|
| 信号去重 | 2 | INV-1, INV-2 |
| 决策订单映射 | 4 | INV-3, INV-4, INV-5, INV-6 |
| 事务 | 2 | INV-7, INV-8 |
| 风控 | 2 | INV-9, INV-10 |
| 执行 | 2 | INV-11, INV-12 |
| Session 管理 | 1 | INV-13 |
| **总计** | **13** | - |

### 7.2 代码保障机制

1. **数据库唯一约束**: `signal_id`、`decision_id` PRIMARY KEY 保证幂等性
2. **原子操作**: `try_claim_reserved()` 原子抢占保证状态转换
3. **事务边界**: `async with get_db_session()` 保证事务原子性
4. **状态机**: 状态转换遵循合法路径
5. **独立 session**: 异常状态使用独立 session commit 保证持久化

### 7.3 测试验证覆盖

- ✅ **单元测试**: Repository 层测试验证数据库约束和原子操作
- ✅ **集成测试**: ExecutionEngine 测试验证状态转换和事务边界
- ✅ **端到端测试**: Webhook 测试验证完整流程不变量

### 7.4 违反后果严重性

| 严重性 | 不变量 | 后果 |
|--------|--------|------|
| **严重** | INV-1, INV-3, INV-9 | 重复下单、资金风险 |
| **高** | INV-4, INV-6, INV-7 | 数据不一致、状态混乱 |
| **中** | INV-2, INV-5, INV-10 | 去重失效、策略隔离失效 |
| **低** | INV-8, INV-11, INV-12, INV-13 | 恢复困难、性能问题 |

---

## 八、不变量维护建议

### 8.1 代码审查检查点

1. **新增状态转换**: 必须遵循合法路径（INV-4）
2. **新增下单逻辑**: 必须检查 `decision_id` 幂等性（INV-3）
3. **新增异常处理**: 必须使用独立 session commit（INV-8）
4. **新增风控规则**: 必须保证拒绝不下单（INV-9）

### 8.2 测试补充建议

1. **并发测试**: 测试多信号并发处理时的不变量保持
2. **压力测试**: 测试高负载下的不变量保持
3. **故障注入**: 测试数据库故障、网络故障时的不变量保持

### 8.3 监控告警建议

1. **重复下单告警**: 监控相同 `decision_id` 重复下单
2. **状态异常告警**: 监控非法状态转换
3. **风控绕过告警**: 监控风控拒绝后仍下单的情况

---

**文档版本**: v1.0  
**最后更新**: 2026-02-03
