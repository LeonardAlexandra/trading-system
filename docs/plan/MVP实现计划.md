# MVP 实现计划（Minimum Viable Product）

## 文档说明

本文档定义了系统的 MVP 版本范围、实现顺序和里程碑，目标是构建一个**安全、可扩展、不会推翻重来**的实盘基础系统。

**版本**: v1.2.5  
**创建日期**: 2026-01-26  
**最后修订**: 2026-01-26  
**基于文档**: 模块接口与边界说明书.md

---

## 一、MVP 版本定义

### 1.1 MVP 核心目标

MVP 的目标是构建一个**能够安全运行实盘交易的基础系统**，具备：

1. ✅ 接收 TradingView 信号并执行交易
2. ✅ 策略逻辑在 Python 中实现（唯一真理版本）
3. ✅ 基础风控保护
4. ✅ 完整的交易记录和可追溯性
5. ✅ 系统状态管理和持久化

### 1.2 MVP 必须包含的模块（核心路径）

#### 信号处理层（必须）
- ✅ **SignalReceiver** - HTTP Webhook 服务器入口（FastAPI 路由）
  - 职责：接收 HTTP 请求、路由处理、错误处理
  - 依赖 TradingViewAdapter 进行签名验证和数据转换
- ✅ **SignalParser** - 解析和标准化信号
- ✅ **TradingViewAdapter** - TradingView Webhook 适配器库
  - 职责：Webhook 签名验证、数据格式转换、错误处理
  - 作为库被 SignalReceiver 调用，不直接处理 HTTP

#### 策略管理层（简化版）
- ✅ **StrategyManager** - 简化版，只支持单个 Active Strategy
  - 不支持多策略并发
  - 不支持策略切换
  - 不支持 Shadow/Candidate 策略
- ⚠️ **StrategyVersionManager** - 简化版（仅配置管理，无版本切换）
- ❌ **StrategyStateMachine** - 暂不实现（MVP 中策略状态固定为 Active）

#### 策略执行层（核心）
- ✅ **StrategyExecutor** - **唯一真理版本，必须完整实现**
- ❌ **ShadowExecutor** - 暂不实现（MVP 不需要）
- ❌ **MarketSimulator** - 暂不实现（MVP 不需要）

#### 风控层（必须）
- ✅ **RiskManager** - 基础风控（单笔风险、账户风险）
- ✅ **PositionManager** - 持仓管理（持仓一致性方案见下文）
- ✅ **AccountManager** - 账户信息管理

#### 执行层（必须）
- ✅ **ExecutionEngine** - 订单执行引擎
- ✅ **OrderManager** - MVP 版（支持查询、取消、状态同步；改价延后）

#### 数据持久化层（必须）
- ✅ **StrategyRepository** - 策略配置存储（简化版）
- ✅ **TradeRepository** - 交易记录存储（必须完整）
- ⚠️ **LogRepository** - 简化版（基础日志，无高级分析）
- ❌ **MetricsRepository** - 暂不实现（MVP 不需要指标历史）

#### 外部接口层（必须）
- ✅ **TradingViewAdapter** - TradingView Webhook 适配器库（见信号处理层说明）
- ✅ **ExchangeAdapter** - 交易所 API 适配器（支持真实和 Paper Trading）
- ✅ **MarketDataAdapter** - 市场数据适配器

#### 评估与优化层（全部延后）
- ❌ **Evaluator** - 暂不实现
- ❌ **MetricsCalculator** - 暂不实现
- ❌ **PromotionEngine** - 暂不实现
- ❌ **EliminationEngine** - 暂不实现
- ❌ **Optimizer** - 暂不实现

#### 监控与告警层（简化版）
- ⚠️ **SystemMonitor** - 简化版（仅基础健康检查）
- ⚠️ **HealthChecker** - 简化版（仅 API 连接检查）
- ⚠️ **AlertSystem** - 简化版（仅邮件/日志告警，无短信/电话）

### 1.3 模块实现状态汇总

| 模块 | MVP 状态 | 说明 |
|------|---------|------|
| SignalReceiver | ✅ 完整实现 | HTTP 入口，依赖 TradingViewAdapter |
| SignalParser | ✅ 完整实现 | 必须 |
| TradingViewAdapter | ✅ 完整实现 | 库，被 SignalReceiver 调用 |
| StrategyManager | ✅ 简化实现 | 仅单策略支持 |
| StrategyVersionManager | ⚠️ 简化实现 | 仅配置管理 |
| StrategyStateMachine | ❌ 暂不实现 | MVP 不需要状态切换 |
| StrategyExecutor | ✅ 完整实现 | **核心，唯一真理版本** |
| ShadowExecutor | ❌ 暂不实现 | MVP 不需要 |
| MarketSimulator | ❌ 暂不实现 | MVP 不需要 |
| RiskManager | ✅ 完整实现 | 必须 |
| PositionManager | ✅ 完整实现 | 必须 |
| AccountManager | ✅ 完整实现 | 必须 |
| ExecutionEngine | ✅ 完整实现 | 必须 |
| OrderManager | ✅ MVP 实现 | 支持查询、取消、状态同步；改价延后 |
| StrategyRepository | ✅ 简化实现 | 基础配置存储 |
| TradeRepository | ✅ 完整实现 | 必须 |
| MetricsRepository | ❌ 暂不实现 | MVP 不需要 |
| LogRepository | ⚠️ 简化实现 | 基础日志 |
| ExchangeAdapter | ✅ 完整实现 | 必须 |
| MarketDataAdapter | ✅ 完整实现 | 必须 |
| Evaluator | ❌ 暂不实现 | 延后 |
| MetricsCalculator | ❌ 暂不实现 | 延后 |
| PromotionEngine | ❌ 暂不实现 | 延后 |
| EliminationEngine | ❌ 暂不实现 | 延后 |
| Optimizer | ❌ 暂不实现 | 延后 |
| SystemMonitor | ⚠️ 简化实现 | 基础监控 |
| HealthChecker | ⚠️ 简化实现 | 基础检查 |
| AlertSystem | ⚠️ 简化实现 | 基础告警 |

**总计**: 28 个模块
- ✅ 完整实现: 14 个
- ✅ MVP 实现: 1 个（OrderManager）
- ⚠️ 简化实现: 5 个
- ❌ 暂不实现: 8 个

### 1.4 开发前置约束（不可变基线）

以下约束在 Phase 1.0 阶段为**硬约束**，不可变更，确保系统基础架构的稳定性和可预测性。

#### 约束 1：交易所与产品形态固定

**硬约束**：Phase 1.0 固定支持 **1 家交易所 + 1 种产品形态**（spot/perp 二选一），禁止扩展。

**配置字段**：
```yaml
exchange:
  name: "binance"  # 固定 1 家交易所，如 "binance" | "okx" | "bybit"
  sandbox: true    # true=Paper Trading, false=实盘
  api_key: "${EXCHANGE_API_KEY}"
  api_secret: "${EXCHANGE_API_SECRET}"

product_type: "spot"  # 固定 1 种产品形态，"spot" | "perp" 二选一
```

**约束说明**：
- Phase 1.0 启动时从配置文件读取 `exchange.name` 和 `product_type`
- 系统运行期间不允许动态切换交易所或产品形态
- 如需切换，必须修改配置文件并重启系统
- ExchangeAdapter 实现时仅需支持配置中指定的交易所和产品形态
- 多交易所/多产品形态支持延后至 Phase 2.0+

**违反后果**：
- 如果在 Phase 1.0 代码中硬编码多交易所或多产品形态逻辑，将导致架构重构
- 违反此约束的代码变更将被拒绝

#### 约束 2：下单幂等强制规范

**硬约束**：ExecutionEngine 必须保证相同 `decision_id` 不会重复下单，这是系统安全性的基础保障。

**实现方案（按优先级）**：

**方案 A（推荐）：使用 client_order_id**
- 将 `decision_id` 作为交易所的 `client_order_id`（客户端订单 ID）
- 交易所保证相同 `client_order_id` 不会重复下单
- 如果下单失败需要重试，使用相同的 `client_order_id` 重试
- 交易所返回已存在的订单信息，不会创建新订单

**方案 B（备选）：持久化映射表**
- 如果交易所不支持 `client_order_id` 或 `client_order_id` 格式限制
- 在数据库中维护 `decision_id → order_id` 映射表
- 下单前查询映射表：
  - 如果 `decision_id` 已存在 → 返回已存在的 `order_id`，不重复下单
  - 如果 `decision_id` 不存在 → 执行下单，成功后保存映射关系
- 重试前必须查询映射表，避免重复下单

**实现要求**：
```python
class ExecutionEngine:
    def execute_order(self, decision: TradingDecision) -> ExecutionResult:
        # 方案 A：使用 client_order_id
        if self.exchange_supports_client_order_id:
            order_id = self.exchange.create_order(
                symbol=decision.symbol,
                side=decision.side,
                amount=decision.quantity,
                client_order_id=decision.decision_id  # 使用 decision_id
            )
        else:
            # 方案 B：查询映射表
            existing_order = self.decision_order_mapping.get(decision.decision_id)
            if existing_order:
                return ExecutionResult(
                    order_id=existing_order.order_id,
                    status="EXISTS",
                    message="Order already exists for this decision_id"
                )
            
            # 执行下单
            order_id = self.exchange.create_order(...)
            
            # 保存映射关系
            self.decision_order_mapping.save(decision.decision_id, order_id)
        
        return ExecutionResult(order_id=order_id, ...)
```

**约束说明**：
- 所有下单操作必须通过 ExecutionEngine，禁止绕过此机制
- 重试机制必须遵守幂等性约束
- 映射表必须持久化到数据库，系统重启后能够恢复
- 如果检测到重复下单尝试，必须记录 CRITICAL 级别日志并告警

**违反后果**：
- 重复下单可能导致资金损失或仓位错误
- 违反此约束将被视为严重安全漏洞

#### 约束 3：单实例运行（Phase 1.0）

**硬约束**：Phase 1.0 必须单实例运行，禁止多进程/多实例部署。

**实现要求**：
- **Web 服务器配置**：`uvicorn workers=1`（单进程模式）
- **禁止多进程**：不允许使用 `workers > 1` 或 `--workers` 参数
- **禁止多实例**：不允许在同一数据库上运行多个系统实例
- **进程内调度**：所有定时任务必须在同一进程内执行

**扩展路径（Phase 2+）**：
- 如需支持多实例/多进程，必须先实现：
  1. **数据库唯一约束**：所有关键操作的表必须有唯一约束（如 `signal_id`、`decision_id`）
  2. **幂等事务**：所有写操作必须支持幂等性，通过数据库约束保证
  3. **分布式锁**：关键操作使用分布式锁（如数据库锁或 Redis 锁）
- 多实例支持延后至 Phase 2.0+

**约束说明**：
- Phase 1.0 的单实例设计简化了系统复杂度，避免了并发冲突
- 单实例运行保证了信号处理、订单执行的一致性
- 如果违反此约束（如误配置多 workers），可能导致重复下单或状态不一致

**违反后果**：
- 多实例运行可能导致信号重复处理、订单重复提交
- 违反此约束将导致系统行为不可预测

#### 约束 4：去重与幂等的数据库事实化

**硬约束**：去重和幂等必须通过数据库唯一约束实现，确保数据层面的强一致性。

**实现要求**：

**1. 信号去重表（dedup_signal）**
```sql
CREATE TABLE dedup_signal (
    signal_id VARCHAR(100) PRIMARY KEY,  -- 唯一键
    first_seen_at TIMESTAMP NOT NULL,    -- 首次接收时间
    received_at TIMESTAMP NOT NULL,      -- 当前接收时间
    processed BOOLEAN DEFAULT FALSE,     -- 是否已处理
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 唯一约束：signal_id 为 PRIMARY KEY
-- 插入冲突即判定重复
```

**去重逻辑**：
- 使用 `INSERT ... ON CONFLICT` 或 `INSERT IGNORE` 机制
- `signal_id` 视为事件唯一 ID，数据库唯一键保证**只处理一次（永久）**
- 如果 `signal_id` 插入冲突 → 判定为重复信号，直接返回，**不再处理**
- `first_seen_at` 和 `received_at` 仅用于记录和审计，不影响去重判断

**2. 决策订单映射表（decision_order_map）**
```sql
CREATE TABLE decision_order_map (
    decision_id VARCHAR(100) PRIMARY KEY,  -- 唯一键
    order_id VARCHAR(100) NOT NULL,        -- 交易所订单 ID
    exchange_order_id VARCHAR(100),        -- 交易所原始订单 ID
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 唯一约束：decision_id 为 PRIMARY KEY
-- 保证重试不重复下单
```

**幂等逻辑**：
- 下单前查询 `decision_order_map`：
  - 如果 `decision_id` 已存在 → 返回已存在的 `order_id`，不重复下单
  - 如果 `decision_id` 不存在 → 执行下单，成功后插入映射关系
- 使用数据库事务保证原子性：
  ```python
  with db.transaction():
      existing = decision_order_map.get(decision_id)
      if existing:
          return existing.order_id
      
      order_id = exchange.create_order(...)
      decision_order_map.insert(decision_id, order_id)
  ```

**约束说明**：
- 数据库唯一约束是去重和幂等的**事实化保证**，不依赖应用层逻辑
- 即使应用层逻辑有 bug，数据库约束也能防止重复
- 系统重启后，数据库中的去重记录和映射关系仍然有效

**违反后果**：
- 如果不在数据库层面实现唯一约束，可能导致重复处理
- 违反此约束将导致数据不一致和资金风险

#### 约束 5：工程收敛（禁止引入复杂基础设施）

**硬约束**：Phase 1.x（含 1.0/1.1/1.2）全部禁止引入 Celery/Redis/消息队列/微服务等复杂基础设施。

**禁止的技术栈**：
- ❌ **Celery**：分布式任务队列
- ❌ **Redis**：缓存/消息队列
- ❌ **RabbitMQ/Kafka**：消息队列
- ❌ **微服务架构**：服务拆分
- ❌ **Kubernetes**：容器编排（禁止）
- ✅ **Docker Compose**：允许，但仅用于单机/单实例部署（1 app + 1 DB），禁止扩容与多实例

**允许的技术栈**：
- ✅ **进程内调度**：使用 APScheduler 或 asyncio task
- ✅ **单进程 Web 服务器**：FastAPI + uvicorn (workers=1)
- ✅ **关系型数据库**：PostgreSQL/SQLite（用于持久化）
- ✅ **文件日志**：Python logging

**定时任务实现**：
```python
# 使用 APScheduler（推荐）
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
scheduler.add_job(
    position_manager.reconcile_with_exchange,
    'interval',
    minutes=5
)
scheduler.start()

# 或使用 asyncio task
async def reconcile_task():
    while True:
        await position_manager.reconcile_with_exchange()
        await asyncio.sleep(300)  # 5 分钟

asyncio.create_task(reconcile_task())
```

**约束说明**：
- Phase 1.x（含 1.0/1.1/1.2）的目标是快速验证核心功能，不需要复杂的分布式架构
- 进程内调度足够满足单实例的定时任务需求
- 引入复杂基础设施会增加系统复杂度、部署难度和故障点
- 如果未来需要扩展（Phase 2+），可以逐步引入 Redis/Celery 等

**扩展路径（Phase 2+）**：
- 如果定时任务需要分布式执行 → 引入 Celery + Redis
- 如果需要缓存 → 引入 Redis
- 如果需要消息队列 → 引入 RabbitMQ/Kafka
- 如果需要微服务 → 进行服务拆分

**违反后果**：
- 过早引入复杂基础设施会增加开发和维护成本
- 违反此约束将导致系统过度设计，影响开发效率

---

## 二、严格实现顺序

### Phase 1.0: 能跑通一笔真实交易

**目标**: 从 TradingView 信号到交易所下单的完整流程打通

#### 涉及的模块（按实现顺序）

1. **数据持久化基础**
   - TradeRepository（SQLite/PostgreSQL）
   - LogRepository（文件日志 + 数据库日志）

2. **外部接口层**
   - MarketDataAdapter（交易所市场数据 API）
   - ExchangeAdapter（交易所交易 API）
   - TradingViewAdapter（Webhook 适配器库：签名验证、数据转换）

3. **信号处理层**
   - SignalReceiver（HTTP Webhook 服务器，FastAPI 路由）
   - SignalParser（信号解析和标准化）

4. **账户和持仓管理**
   - AccountManager（查询账户信息）
   - PositionManager（持仓管理，使用 position_snapshot 投影表）

5. **策略执行层（核心）**
   - StrategyExecutor（实现策略逻辑，唯一真理版本）
   - StrategyManager（简化版，单策略管理）

6. **风控层**
   - RiskManager（基础风控检查）

7. **执行层**
   - ExecutionEngine（订单执行）
   - OrderManager（查询 + 取消 + 状态同步（基础版）；改价/replace 延后）

#### 是否需要真实交易所

**选项 A（推荐）: Paper Trading（模拟交易）**
- ✅ 使用交易所的 Paper Trading API（如币安测试网）
- ✅ 使用真实市场数据，但不下真实订单
- ✅ 可以完整测试所有流程，无资金风险
- ✅ 适合 Phase 1.0 验证

**选项 B: 真实交易所（小额测试）**
- ⚠️ 使用真实交易所 API，但用最小资金测试
- ⚠️ 需要完整的错误处理和风控
- ⚠️ 风险：可能产生真实亏损

**MVP 建议**: Phase 1.0 使用 **Paper Trading**，验证完整流程后再考虑真实交易。

#### Mock 策略

- **StrategyExecutor**: 实现一个最简单的策略逻辑
  - 示例：收到 BUY 信号 → 买入固定数量
  - 收到 SELL 信号 → 平仓
  - 不涉及复杂的技术分析逻辑

#### Phase 1.0 验收标准

- [ ] 能够接收 TradingView Webhook 信号（SignalReceiver + TradingViewAdapter）
- [ ] 能够验证 Webhook 签名（TradingViewAdapter）
- [ ] 能够解析信号并路由到策略
- [ ] 策略能够生成交易决策
- [ ] 风控检查能够通过/拒绝决策
- [ ] 能够提交订单到交易所（Paper Trading）
- [ ] 能够记录交易到数据库
- [ ] 能够查询持仓（基于 position_snapshot 投影表）
- [ ] 能够查询账户信息
- [ ] 能够查看基础日志

#### Phase 1.0 技术栈

- **Web 框架**: FastAPI（Webhook 接收）
- **数据库**: SQLite（开发）或 PostgreSQL（生产）
- **交易所 API**: ccxt 库（统一交易所接口）
- **日志**: Python logging + 数据库存储

---

### Phase 1.1: 补齐风控与状态

**目标**: 完善风控系统，建立完整的系统状态管理

#### 涉及的模块（在 Phase 1.0 基础上）

1. **风控层增强**
   - RiskManager（完善所有风控规则）
     - 单笔交易风险检查
     - 账户级风险检查（VaR、集中度）
     - 策略级风险检查（连续亏损、回撤）
     - 动态仓位调整

2. **状态管理**
   - StrategyRepository（策略配置持久化）
   - StrategyVersionManager（策略配置版本管理，简化版）
   - PositionManager（完善持仓一致性：成交驱动更新 + 定期 reconcile）

3. **订单管理**
   - OrderManager（订单查询、取消、状态同步；改价功能延后）
   - ExecutionEngine（订单状态监控和更新）

4. **账户管理增强**
   - AccountManager（账户快照、历史查询）

#### 是否需要真实交易所

**建议**: 继续使用 **Paper Trading**，但可以开始准备真实交易所的配置。

#### Phase 1.1 验收标准

- [ ] 所有风控规则完整实现
- [ ] 策略配置可以持久化和版本管理
- [ ] 订单状态能够实时同步（OrderManager）
- [ ] 订单可以取消（OrderManager）
- [ ] 持仓通过 position_snapshot 投影表管理（运行时真理源）
- [ ] 持仓在成交时自动更新（成交驱动，更新 position_snapshot）
- [ ] 持仓定期与交易所 reconcile（定时任务，每 5 分钟，仅用于校验）
- [ ] 轻微不一致（< 1%）仅记录日志，不覆盖 position_snapshot
- [ ] 中等不一致（1-5%）触发报警，不覆盖 position_snapshot
- [ ] 严重不一致（> 5%）或持续不一致时覆盖 position_snapshot 并进入安全模式
- [ ] 账户信息能够实时查询和快照
- [ ] 风控拒绝的交易有完整记录和原因
- [ ] 系统状态可以持久化和恢复

#### Phase 1.1 新增功能

- 风控规则配置化（JSON/YAML 配置文件）
- 策略配置管理界面（CLI 或简单 Web 界面）
- 订单状态自动同步（定时任务）
- 订单取消功能（OrderManager）
- 持仓一致性机制（position_snapshot + 成交驱动更新 + 定期 reconcile）
- 持仓不一致报警和自动修复
- 账户快照功能（每日自动快照）

---

### Phase 1.2: 补齐日志与可追溯

**目标**: 建立完整的审计日志和可追溯性系统

#### 涉及的模块（在 Phase 1.1 基础上）

1. **日志系统完善**
   - LogRepository（完整实现）
     - 操作日志（所有关键操作）
     - 审计日志（交易决策、风控检查、订单执行）
     - 错误日志（异常和错误）
     - 性能日志（延迟、吞吐量）

2. **可追溯性**
   - 信号追踪（Signal ID → Decision ID → Execution ID → Trade ID）
   - 决策追踪（决策原因、策略状态快照）
   - 风控追踪（风控检查结果、拒绝原因）
   - 执行追踪（订单提交、成交、滑点）

3. **监控和告警增强**
   - SystemMonitor（系统健康监控）
   - HealthChecker（组件健康检查）
   - AlertSystem（告警通知，邮件/日志）

#### 是否需要真实交易所

**建议**: 可以开始**小额真实交易测试**（如 100 USDT），但保持 Paper Trading 并行运行。

#### Phase 1.2 验收标准

- [ ] 所有关键操作都有审计日志
- [ ] 每笔交易可以完整追溯（信号 → 决策 → 执行 → 成交）
- [ ] 可以查询任意时间点的系统状态
- [ ] 可以回放历史交易流程
- [ ] 系统健康监控正常工作
- [ ] 告警系统能够及时通知
- [ ] 日志可以按时间、组件、级别查询

#### Phase 1.2 新增功能

- 审计日志查询界面（CLI 或 Web）
- 交易追溯工具（查询完整链路）
- 系统健康仪表板（简单 Web 界面）
- 告警规则配置（邮件通知规则）

---

## 三、第一个"可上线运行"的里程碑

### 3.1 里程碑定义：MVP v1.0 生产就绪版

**里程碑名称**: **MVP v1.0 - 安全实盘基础系统**

**完成条件**: Phase 1.2 全部完成 + 以下额外要求

### 3.2 必须满足的条件

#### 功能完整性
- ✅ 完整的信号接收和处理流程
- ✅ 策略逻辑在 Python 中实现（唯一真理版本）
- ✅ 完整的风控系统（单笔、账户、策略级）
- ✅ 完整的交易执行流程
- ✅ 完整的交易记录和审计日志
- ✅ 系统状态持久化和恢复

#### 安全性
- ✅ 所有交易必须通过风控检查
- ✅ 风控规则不可绕过
- ✅ 所有操作都有审计日志
- ✅ 敏感信息（API Key）加密存储
- ✅ Webhook 签名验证
- ✅ 错误处理和异常恢复

#### 可追溯性
- ✅ 每笔交易可以完整追溯（信号 → 决策 → 执行 → 成交）
- ✅ 所有决策都有原因记录
- ✅ 所有风控检查都有结果记录
- ✅ 系统状态变更都有日志

#### 可维护性
- ✅ 代码结构清晰，模块解耦
- ✅ 配置与代码分离
- ✅ 日志完整，便于调试
- ✅ 错误信息明确，便于排查

#### 稳定性
- ✅ 系统可以 7x24 小时运行
- ✅ 网络中断后可以自动恢复
- ✅ API 错误有重试机制
- ✅ 数据库连接有连接池和重连机制

#### 监控和告警
- ✅ 系统健康监控
- ✅ 关键指标监控（信号接收、订单执行、错误率）
- ✅ 告警通知（邮件）
- ✅ 日志查询和分析

### 3.3 系统形态

#### 架构
```
TradingView Webhook
    ↓
FastAPI Web Server (SignalReceiver + SignalParser)
    ↓
StrategyManager → StrategyExecutor (唯一真理版本)
    ↓
RiskManager (风控检查)
    ↓
ExecutionEngine → ExchangeAdapter (交易所 API)
    ↓
TradeRepository (交易记录)
LogRepository (审计日志)
```

#### 数据流
```
信号 → 解析 → 策略决策 → 风控检查 → 订单执行 → 交易记录
         ↓           ↓          ↓           ↓
      日志记录    日志记录    日志记录    日志记录
```

#### 部署形态
- **单机部署**: 所有组件运行在一台服务器上
- **数据库**: PostgreSQL（生产）或 SQLite（开发）
- **进程管理**: systemd 或 supervisor
- **日志**: 文件日志 + 数据库日志
- **配置**: 环境变量 + 配置文件（YAML/JSON）

---

## 三、关键设计说明（v1.1 新增）

### 3.1 TradingViewAdapter 与 SignalReceiver 职责边界

#### 推荐方案：Adapter 为库，Receiver 为 HTTP 入口

**TradingViewAdapter（适配器库）**
- **职责**：
  - Webhook 签名验证（HMAC-SHA256）
  - 原始 Webhook 数据解析和验证
  - 数据格式转换（Webhook JSON → 内部 RawSignal 格式）
  - 错误处理和异常转换
- **不负责**：
  - HTTP 请求接收（由 SignalReceiver 负责）
  - HTTP 响应生成（由 SignalReceiver 负责）
  - 路由处理（由 SignalReceiver 负责）

**SignalReceiver（HTTP 入口）**
- **职责**：
  - 接收 HTTP POST 请求（FastAPI 路由）
  - 调用 TradingViewAdapter 进行签名验证和数据转换
  - 处理 HTTP 错误和异常
  - 生成 HTTP 响应
  - 将转换后的信号传递给 SignalParser
- **不负责**：
  - Webhook 签名验证逻辑（由 TradingViewAdapter 负责）
  - 数据格式转换逻辑（由 TradingViewAdapter 负责）

#### 调用关系
```
HTTP Request
    ↓
SignalReceiver (FastAPI route)
    ↓
TradingViewAdapter.validate_and_convert(webhook_data)
    ↓
RawSignal
    ↓
SignalParser
```

#### 实现示例（伪代码）
```python
# TradingViewAdapter (库)
class TradingViewAdapter:
    @staticmethod
    def validate_signature(payload: bytes, signature: str, secret: str) -> bool:
        # HMAC-SHA256 签名验证
        ...
    
    @staticmethod
    def parse_webhook(webhook_data: dict) -> RawSignal:
        # 数据格式转换
        ...

# SignalReceiver (HTTP 入口)
@app.post("/webhook/tradingview")
async def receive_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("X-TradingView-Signature")
    
    # 调用 Adapter 进行验证和转换
    if not TradingViewAdapter.validate_signature(payload, signature, secret):
        raise HTTPException(401, "Invalid signature")
    
    webhook_data = await request.json()
    raw_signal = TradingViewAdapter.parse_webhook(webhook_data)
    
    # 传递给 SignalParser
    await signal_parser.process(raw_signal)
    
    return {"status": "ok"}
```

### 3.2 OrderManager MVP 能力

#### 必须支持的功能
1. **订单查询**
   - 按订单 ID 查询
   - 按策略 ID 查询
   - 按状态查询（PENDING、FILLED、CANCELLED 等）
   - 按交易对查询

2. **订单取消**
   - 取消未成交订单
   - 取消原因记录
   - 取消结果反馈

3. **订单状态同步**
   - 定时同步订单状态（从交易所 API）
   - 订单状态变更通知
   - 状态不一致检测和修复

#### 延后的功能
- ❌ **订单改价**（限价单价格修改）
  - 原因：MVP 阶段主要使用市价单，改价需求较低
  - 计划：Phase 2.0 实现

#### 实现要点
- 订单状态缓存（减少 API 调用）
- 状态同步定时任务（每 30 秒或 1 分钟）
- 状态不一致时自动修复（重新查询交易所）

### 3.3 PositionManager 持仓一致性方案

#### 设计原则
- **运行时真理源**: **position_snapshot 投影表为运行时真理源**，所有策略决策和风控检查基于 position_snapshot
- **交易所持仓作用**: 交易所持仓仅用于 reconcile 校验，不作为运行时数据源
- **性能优化**: 使用投影表（position_snapshot）提供快速查询，避免实时计算
- **一致性保证**: 成交驱动更新 + 定期 reconcile 校验

#### 方案设计

**1. position_snapshot 投影表（运行时真理源）**
```sql
CREATE TABLE position_snapshot (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,  -- 'long' or 'short'
    quantity DECIMAL(20, 8) NOT NULL,
    entry_price DECIMAL(20, 8) NOT NULL,
    current_price DECIMAL(20, 8),
    unrealized_pnl DECIMAL(20, 8),
    last_trade_id VARCHAR(50),  -- 最后更新的交易 ID
    updated_at TIMESTAMP NOT NULL,
    reconcile_status VARCHAR(20) DEFAULT 'OK',  -- 'OK' | 'WARNING' | 'CRITICAL'
    reconcile_last_check TIMESTAMP,
    UNIQUE(strategy_id, symbol, side)
);
```

**2. 成交驱动更新（主要更新路径）**
- 当 ExecutionEngine 收到订单成交通知时：
  1. 更新 TradeRepository（记录交易）
  2. 触发 PositionManager.update_from_trade(trade)
  3. PositionManager 更新 position_snapshot（**这是运行时数据源**）
  4. 记录更新日志
  5. 标记 reconcile_status = 'OK'

**3. 定期 Reconcile（对账校验，不直接覆盖）**
- **频率**: 每 5 分钟（可配置）
- **流程**:
  1. 从 ExchangeAdapter 查询交易所持仓（**仅用于校验**）
  2. 与 position_snapshot 对比（**position_snapshot 为基准**）
  3. 计算不一致程度（数量差异、价格差异）
  4. 根据不一致程度执行相应策略（见下文）

**4. 不一致处理策略（分层处理）**

**轻微不一致（< 1%）**
- **触发条件**: 数量差异 < 1% 且价格差异 < 1%
- **处理**:
  - 记录 WARNING 级别日志
  - 更新 reconcile_status = 'WARNING'
  - 更新 reconcile_last_check
  - **不覆盖 position_snapshot**，继续使用 position_snapshot 作为真理源
  - 不触发告警

**中等不一致（1-5%）**
- **触发条件**: 数量差异 1-5% 或价格差异 1-5%
- **处理**:
  - 记录 IMPORTANT 级别日志
  - 更新 reconcile_status = 'WARNING'
  - 更新 reconcile_last_check
  - **不覆盖 position_snapshot**，继续使用 position_snapshot 作为真理源
  - 触发 IMPORTANT 级别告警（邮件通知）
  - 记录不一致详情到审计日志

**严重不一致（> 5%）或持续不一致**
- **触发条件（满足任一）**:
  1. 数量差异 > 5% 或价格差异 > 5%
  2. 中等不一致持续 > 3 个 reconcile 周期（15 分钟）
  3. 轻微不一致持续 > 6 个 reconcile 周期（30 分钟）
- **处理流程**:
  1. 记录 CRITICAL 级别日志
  2. 更新 reconcile_status = 'CRITICAL'
  3. 更新 reconcile_last_check
  4. **触发覆盖操作**:
     - 记录覆盖前状态（审计日志，包含 position_snapshot 和交易所持仓的完整对比）
     - 用交易所持仓数据覆盖 position_snapshot（**仅在此情况下允许覆盖**）
     - 记录覆盖后状态
     - 更新 reconcile_status = 'OK'
  5. **进入安全模式**:
     - 暂停新订单提交（ExecutionEngine 拒绝新订单）
     - 发送 CRITICAL 级别告警（邮件 + 系统状态通知）
     - 记录安全模式进入日志
  6. **安全模式退出条件**:
     - 人工确认后手动退出
     - 或连续 2 个 reconcile 周期（10 分钟）无严重不一致后自动退出

**5. 实现要点**
```python
class PositionManager:
    def get_position(self, strategy_id: str, symbol: str, side: str) -> Position:
        """查询持仓（从 position_snapshot，运行时真理源）"""
        # 直接从 position_snapshot 查询，不查询交易所
        return self._get_from_snapshot(strategy_id, symbol, side)
    
    def update_from_trade(self, trade: Trade):
        """成交驱动更新（主要更新路径）"""
        # 更新 position_snapshot（运行时真理源）
        self._update_snapshot(trade)
        # 标记 reconcile_status = 'OK'
        self._update_reconcile_status(trade.symbol, trade.side, 'OK')
        # 记录更新日志
        self.logger.info(f"Position updated from trade: {trade.trade_id}")
    
    def reconcile_with_exchange(self):
        """定期对账（校验，不直接覆盖）"""
        exchange_positions = self.exchange_adapter.get_positions()
        snapshot_positions = self._get_all_snapshots()
        
        for (symbol, side), snapshot_pos in snapshot_positions.items():
            exchange_pos = exchange_positions.get((symbol, side))
            
            if exchange_pos is None:
                # 交易所无持仓，但 snapshot 有持仓
                self._handle_missing_exchange_position(snapshot_pos)
                continue
            
            # 计算不一致程度
            qty_diff_pct = self._calculate_qty_diff_pct(exchange_pos, snapshot_pos)
            price_diff_pct = self._calculate_price_diff_pct(exchange_pos, snapshot_pos)
            
            # 根据不一致程度处理
            if qty_diff_pct > 0.05 or price_diff_pct > 0.05:
                # 严重不一致：覆盖 + 安全模式
                self._handle_critical_inconsistency(exchange_pos, snapshot_pos)
            elif qty_diff_pct > 0.01 or price_diff_pct > 0.01:
                # 中等不一致：报警，不覆盖
                self._handle_medium_inconsistency(exchange_pos, snapshot_pos)
            elif qty_diff_pct > 0.001 or price_diff_pct > 0.01:
                # 轻微不一致：仅记录日志
                self._handle_minor_inconsistency(exchange_pos, snapshot_pos)
            else:
                # 一致：更新状态
                self._update_reconcile_status(symbol, side, 'OK')
    
    def _handle_critical_inconsistency(self, exchange_pos, snapshot_pos):
        """处理严重不一致：覆盖 + 安全模式"""
        # 记录覆盖前状态
        self.logger.critical(
            f"Critical position inconsistency detected. "
            f"Snapshot: {snapshot_pos}, Exchange: {exchange_pos}"
        )
        
        # 覆盖 position_snapshot（仅此情况允许覆盖）
        self._overwrite_snapshot(exchange_pos)
        
        # 进入安全模式
        self._enter_safe_mode()
        
        # 发送告警
        self.alert_system.send_critical(
            f"Position critical inconsistency: {exchange_pos.symbol} {exchange_pos.side}"
        )
    
    def _handle_medium_inconsistency(self, exchange_pos, snapshot_pos):
        """处理中等不一致：报警，不覆盖"""
        self.logger.warning(
            f"Medium position inconsistency: {self._calculate_diff(exchange_pos, snapshot_pos)}%"
        )
        self._update_reconcile_status(snapshot_pos.symbol, snapshot_pos.side, 'WARNING')
        self.alert_system.send_important(
            f"Position medium inconsistency: {snapshot_pos.symbol} {snapshot_pos.side}"
        )
        # 不覆盖 position_snapshot，继续使用
    
    def _handle_minor_inconsistency(self, exchange_pos, snapshot_pos):
        """处理轻微不一致：仅记录日志"""
        self.logger.info(
            f"Minor position inconsistency: {self._calculate_diff(exchange_pos, snapshot_pos)}%"
        )
        self._update_reconcile_status(snapshot_pos.symbol, snapshot_pos.side, 'WARNING')
        # 不覆盖 position_snapshot，继续使用
    
    def _enter_safe_mode(self):
        """进入安全模式"""
        self.safe_mode = True
        self.logger.critical("Entering safe mode: new orders will be rejected")
        # 通知 ExecutionEngine 拒绝新订单
        self.execution_engine.set_safe_mode(True)
```

#### 数据流
```
运行时查询持仓
    ↓
PositionManager.get_position()
    ↓
从 position_snapshot 查询（运行时真理源）
    ↓
返回持仓数据

订单成交
    ↓
ExecutionEngine 通知
    ↓
PositionManager.update_from_trade()
    ↓
更新 position_snapshot（运行时真理源）
    ↓
记录更新日志

定时任务（每 5 分钟）
    ↓
PositionManager.reconcile_with_exchange()
    ↓
查询交易所持仓（仅用于校验）
    ↓
对比 position_snapshot（position_snapshot 为基准）
    ↓
不一致？
    ├─ 严重不一致 → 覆盖 position_snapshot + 进入安全模式
    ├─ 中等不一致 → 报警，不覆盖
    ├─ 轻微不一致 → 仅记录日志，不覆盖
    └─ 一致 → 更新状态为 OK
```

#### 关键原则
- **运行时真理源**: position_snapshot 是运行时唯一真理源，所有策略决策和风控检查基于此
- **交易所持仓作用**: 仅用于 reconcile 校验，不作为运行时数据源
- **覆盖条件严格**: 只有严重不一致（> 5%）或持续不一致才允许覆盖
- **安全模式保护**: 覆盖后自动进入安全模式，暂停新订单，等待人工确认
- **可追溯性**: 所有覆盖操作都有完整的审计日志

### 3.4 不支持的功能（明确说明）

- ❌ 多策略并发运行
- ❌ 策略自动切换
- ❌ Shadow Strategy 影子交易
- ❌ 策略性能评估和优化
- ❌ 策略自动晋升/淘汰
- ❌ 复杂的监控仪表板
- ❌ 短信/电话告警（仅邮件）

### 3.5 上线检查清单

#### 代码质量
- [ ] 所有核心模块实现完成
- [ ] 单元测试覆盖核心逻辑（> 80%）
- [ ] 集成测试覆盖完整流程
- [ ] 代码审查通过
- [ ] 文档完整（API 文档、部署文档、运维文档）

#### 配置和部署
- [ ] 配置文件模板准备
- [ ] 环境变量文档
- [ ] 部署脚本准备
- [ ] 数据库迁移脚本
- [ ] 备份和恢复流程

#### 安全
- [ ] API Key 加密存储
- [ ] Webhook 签名验证
- [ ] 数据库连接加密
- [ ] 日志不包含敏感信息
- [ ] 访问控制（如果需要）

#### 监控和运维
- [ ] 系统监控配置
- [ ] 告警规则配置
- [ ] 日志轮转配置
- [ ] 数据库备份配置
- [ ] 故障恢复流程

#### 测试
- [ ] Paper Trading 测试通过（至少 100 笔交易）
- [ ] 小额真实交易测试通过（至少 10 笔交易）
- [ ] 压力测试（信号并发、API 限流）
- [ ] 故障恢复测试（网络中断、API 错误）

### 3.6 上线后的运行模式

#### 初期运行（1-2 周）
- 使用 Paper Trading 或最小资金（如 100 USDT）
- 密切监控所有交易和系统状态
- 每天检查日志和告警
- 收集问题和优化建议

#### 稳定运行（2 周后）
- 逐步增加资金（如果表现良好）
- 定期检查系统健康
- 每周回顾交易记录和日志
- 准备 Phase 2.0（评估和优化系统）

---

## 四、技术实现建议

### 4.1 技术栈选择

#### 后端框架
- **FastAPI**: Web 框架（Webhook 接收、API 服务）
- **Python 3.10+**: 编程语言

#### 数据库
- **PostgreSQL**: 生产环境（推荐）
- **SQLite**: 开发环境（可选）

#### 交易所接口
- **ccxt**: 统一交易所 API 库
- 支持币安、OKX 等主流交易所

#### 任务队列（Phase 1.x 全部禁止 Celery/Redis/队列；如需引入，推迟到 Phase 2+（系统扩展阶段））
- ❌ **Celery + Redis**: Phase 1.x 禁止使用
- ✅ **进程内调度**: 使用 APScheduler 或 asyncio task（见约束 5）

#### 日志
- **Python logging**: 标准日志库
- **数据库存储**: 关键日志存入数据库

### 4.2 项目结构建议

```
trading_system/
├── src/
│   ├── signal/          # 信号处理层
│   │   ├── receiver.py
│   │   └── parser.py
│   ├── strategy/        # 策略层
│   │   ├── manager.py
│   │   ├── executor.py
│   │   └── config.py
│   ├── risk/            # 风控层
│   │   ├── manager.py
│   │   └── rules.py
│   ├── execution/       # 执行层
│   │   ├── engine.py
│   │   └── order_manager.py
│   ├── position/        # 持仓管理
│   │   ├── manager.py
│   │   └── calculator.py
│   ├── account/         # 账户管理
│   │   └── manager.py
│   ├── adapters/        # 外部接口适配器
│   │   ├── tradingview.py
│   │   ├── exchange.py
│   │   └── market_data.py
│   ├── repositories/    # 数据仓库
│   │   ├── strategy.py
│   │   ├── trade.py
│   │   └── log.py
│   ├── monitoring/      # 监控
│   │   ├── monitor.py
│   │   └── health.py
│   └── utils/           # 工具函数
│       ├── logging.py
│       └── config.py
├── tests/               # 测试
├── config/              # 配置文件
├── scripts/             # 脚本
├── docs/                # 文档
└── requirements.txt
```

### 4.3 配置管理

#### 配置文件结构（YAML）
```yaml
# config/production.yaml
tradingview:
  webhook_secret: "${TV_WEBHOOK_SECRET}"
  
exchange:
  name: "binance"
  api_key: "${EXCHANGE_API_KEY}"
  api_secret: "${EXCHANGE_API_SECRET}"
  sandbox: false  # 生产环境设为 false
  
strategy:
  strategy_id: "SMC_FVG_v1"
  config:
    max_position_size: 0.1  # 最大仓位（BTC）
    stop_loss_pct: 0.02    # 止损 2%
    
risk:
  max_single_trade_risk: 0.01  # 单笔最大风险 1%
  max_account_risk: 0.05       # 账户最大风险 5%
  max_drawdown: 0.20            # 最大回撤 20%
  
database:
  url: "${DATABASE_URL}"
  
logging:
  level: "INFO"
  file: "/var/log/trading_system/app.log"
  database: true
```

---

## 五、风险控制与安全

### 5.1 MVP 阶段的风险控制

#### 资金风险
- 使用 Paper Trading 或最小资金测试
- 设置严格的单笔和账户风险限制
- 每日亏损上限（如 5%）
- 连续亏损自动停止

#### 技术风险
- 完整的错误处理和重试机制
- 数据库事务保证数据一致性
- 订单状态实时同步
- 系统故障自动恢复

#### 操作风险
- 所有操作都有审计日志
- 关键操作需要确认（可选，MVP 可以简化）
- 配置变更需要记录
- 系统状态可以查询和恢复

### 5.2 安全措施

#### API 安全
- Webhook 签名验证
- API Key 加密存储（使用环境变量或密钥管理服务）
- 数据库连接加密
- 日志不包含敏感信息

#### 系统安全
- 最小权限原则
- 定期备份数据库
- 日志轮转和归档
- 监控异常访问

---

## 六、后续扩展路径（Phase 2.0+）

### 6.1 不会推翻重来的设计原则

#### 接口稳定性
- 所有模块接口按照《模块接口与边界说明书》定义
- 后续扩展不破坏现有接口
- 新功能通过新模块实现，不修改核心模块

#### 数据模型扩展性
- 数据库表设计考虑未来扩展
- 使用 JSON 字段存储灵活配置
- 版本字段支持数据迁移

#### 架构可扩展性
- 模块解耦，便于独立扩展
- 支持插件化策略（Phase 2.0）
- 支持分布式部署（Phase 3.0）

### 6.2 Phase 2.0 规划（评估与优化系统）

在 MVP 稳定运行后，可以逐步添加：

1. **Shadow Strategy 系统**
   - ShadowExecutor
   - MarketSimulator
   - 策略对比和评估

2. **评估系统**
   - Evaluator
   - MetricsCalculator
   - MetricsRepository

3. **策略管理增强**
   - StrategyStateMachine（状态机）
   - PromotionEngine（晋升决策）
   - EliminationEngine（淘汰决策）

4. **优化系统**
   - Optimizer（参数优化）
   - 策略回测框架

### 6.3 扩展不影响现有系统

- 新模块通过接口与现有模块交互
- 不修改现有模块的核心逻辑
- 新功能可选启用，不影响 MVP 功能
- 数据模型向后兼容

---

## 七、总结

### 7.1 MVP 核心价值

1. **安全**: 完整的风控系统和审计日志
2. **可追溯**: 每笔交易可以完整追溯
3. **可扩展**: 架构设计支持后续扩展，不会推翻重来
4. **可维护**: 模块解耦，代码清晰，文档完整
5. **可运行**: 能够安全运行实盘交易

### 7.2 实现路径

```
Phase 1.0 (2-3 周)
  ↓ 能跑通一笔交易
Phase 1.1 (1-2 周)
  ↓ 补齐风控与状态
Phase 1.2 (1-2 周)
  ↓ 补齐日志与可追溯
MVP v1.0 上线 (里程碑)
  ↓ 稳定运行 2-4 周
Phase 2.0 规划
  ↓ 评估与优化系统
```

### 7.3 关键成功因素

1. **严格按照接口规范实现**，确保模块解耦
2. **每个 Phase 都要完整测试**，确保质量
3. **文档和日志要完整**，便于维护和排查
4. **安全第一**，风控不可绕过
5. **可追溯性**，所有操作都要记录

---

## 八、修订后的 Phase 模块清单与验收标准（v1.2）

### Phase 1.0: 能跑通一笔真实交易

#### 涉及的模块（按实现顺序）

1. **数据持久化基础**
   - ✅ TradeRepository（SQLite/PostgreSQL）
   - ⚠️ LogRepository（文件日志 + 数据库日志，简化版）

2. **外部接口层**
   - ✅ MarketDataAdapter（交易所市场数据 API）
   - ✅ ExchangeAdapter（交易所交易 API）
   - ✅ TradingViewAdapter（Webhook 适配器库：签名验证、数据转换）

3. **信号处理层**
   - ✅ SignalReceiver（HTTP Webhook 服务器，FastAPI 路由）
   - ✅ SignalParser（信号解析和标准化）

4. **账户和持仓管理**
   - ✅ AccountManager（查询账户信息）
   - ✅ PositionManager（持仓管理，使用 position_snapshot 投影表作为运行时真理源）

5. **策略执行层（核心）**
   - ✅ StrategyExecutor（实现策略逻辑，唯一真理版本）
   - ✅ StrategyManager（简化版，单策略管理）

6. **风控层**
   - ✅ RiskManager（基础风控检查）

7. **执行层**
   - ✅ ExecutionEngine（订单执行）
   - ✅ OrderManager（查询 + 取消 + 状态同步（基础版）；改价/replace 延后）

#### 是否需要真实交易所

**推荐**: 使用 **Paper Trading（模拟交易）**
- 使用交易所的 Paper Trading API（如币安测试网）
- 使用真实市场数据，但不下真实订单
- 可以完整测试所有流程，无资金风险

#### Phase 1.0 验收标准

**基础功能验收**
- [ ] 能够接收 TradingView Webhook 信号（SignalReceiver + TradingViewAdapter）
- [ ] 能够验证 Webhook 签名（TradingViewAdapter）
- [ ] 能够解析信号并路由到策略
- [ ] 策略能够生成交易决策
- [ ] 风控检查能够通过/拒绝决策
- [ ] 能够提交订单到交易所（Paper Trading）
- [ ] 能够记录交易到数据库
- [ ] 能够查询持仓（基于 position_snapshot 投影表，运行时真理源）
- [ ] 能够查询账户信息
- [ ] 能够查看基础日志

**幂等性与去重验收（量化标准）**
- [ ] **信号去重**: 相同 signal_id 永久只处理一次（DB 唯一键保证）
  - 测试方法：发送相同 signal_id 的信号 3 次，验证只生成 1 个交易决策
  - 验收标准：重复信号被拒绝，记录去重日志，不生成重复订单
  - 说明：`first_seen_at` 和 `received_at` 仅用于审计，不影响去重判定
- [ ] **信号重放保护**: 历史 signal_id 重放不会重复下单
  - 测试方法：使用已处理过的 signal_id（时间戳为过去时间）发送信号
  - 验收标准：系统识别为历史信号，拒绝处理，记录重放日志
- [ ] **订单幂等性**: 相同 decision_id 的决策不会重复提交订单
  - 测试方法：相同 decision_id 的 TradingDecision 提交 2 次
  - 验收标准：第二次提交被拒绝，返回已存在订单 ID，不重复下单
- [ ] **去重存储**: 所有去重操作记录到数据库，支持查询
  - 验收标准：可以查询到所有被去重的信号记录（signal_id、去重时间、原因）

**异常恢复验收（量化标准）**
- [ ] **交易所 API 超时恢复**:
  - 测试场景：模拟交易所 API 超时（> 30 秒无响应）
  - 验收标准：
    - 系统在 30 秒后自动超时，记录超时日志
    - 订单状态标记为 "TIMEOUT"
    - 系统继续运行，不阻塞后续信号处理
    - 支持手动重试超时订单（通过 OrderManager）
- [ ] **进程重启恢复**:
  - 测试场景：系统运行中强制 kill 进程，然后重启
  - 验收标准：
    - 重启后能够从数据库恢复策略状态
    - 重启后能够恢复 position_snapshot（从 TradeRepository 重建或从数据库加载）
    - 重启后能够查询到未完成订单（PENDING 状态）
    - 重启后能够继续处理新信号（不丢失功能）
    - 所有恢复操作记录到日志
- [ ] **重复 Webhook 处理**:
  - 测试场景：TradingView 因网络问题重复发送相同 Webhook（相同内容，不同时间）
  - 验收标准：
    - 通过 signal_id 去重，重复 Webhook 被拒绝
    - 记录重复 Webhook 日志（包含原始接收时间和重复接收时间）
    - 不生成重复交易决策
    - 返回 200 OK 避免 TradingView 重试
- [ ] **数据库连接中断恢复**:
  - 测试场景：运行中断开数据库连接，然后恢复连接
  - 验收标准：
    - 系统检测到连接中断，记录错误日志
    - 自动重连机制工作（重试间隔：5 秒、10 秒、30 秒，最多 3 次）
    - 重连成功后继续处理，不丢失数据
    - 连接中断期间的信号可以缓存或拒绝（记录日志）
- [ ] **交易所连接中断恢复**:
  - 测试场景：运行中断开交易所 API 连接
  - 验收标准：
    - 系统检测到连接中断，记录错误日志
    - 订单查询失败时标记为 "UNKNOWN"，不阻塞系统
    - 连接恢复后自动同步订单状态
    - 连接中断期间的新订单请求被拒绝，记录错误日志

---

### Phase 1.1: 补齐风控与状态

#### 涉及的模块（在 Phase 1.0 基础上）

1. **风控层增强**
   - ✅ RiskManager（完善所有风控规则）
     - 单笔交易风险检查
     - 账户级风险检查（VaR、集中度）
     - 策略级风险检查（连续亏损、回撤）
     - 动态仓位调整

2. **状态管理**
   - ✅ StrategyRepository（策略配置持久化）
   - ⚠️ StrategyVersionManager（策略配置版本管理，简化版）
   - ✅ PositionManager（完善持仓一致性：成交驱动更新 + 定期 reconcile）

3. **订单管理**
   - ✅ OrderManager（订单查询、取消、状态同步；改价功能延后）
   - ✅ ExecutionEngine（订单状态监控和更新）

4. **账户管理增强**
   - ✅ AccountManager（账户快照、历史查询）

#### 是否需要真实交易所

**建议**: 继续使用 **Paper Trading**，但可以开始准备真实交易所的配置。

#### Phase 1.1 验收标准

- [ ] 所有风控规则完整实现
- [ ] 策略配置可以持久化和版本管理
- [ ] 订单状态能够实时同步（OrderManager）
- [ ] 订单可以取消（OrderManager）
- [ ] 持仓通过 position_snapshot 投影表管理（运行时真理源）
- [ ] 持仓在成交时自动更新（成交驱动，更新 position_snapshot）
- [ ] 持仓定期与交易所 reconcile（定时任务，每 5 分钟，仅用于校验）
- [ ] 轻微不一致（< 1%）仅记录日志，不覆盖 position_snapshot
- [ ] 中等不一致（1-5%）触发报警，不覆盖 position_snapshot
- [ ] 严重不一致（> 5%）或持续不一致时覆盖 position_snapshot 并进入安全模式
- [ ] 账户信息能够实时查询和快照
- [ ] 风控拒绝的交易有完整记录和原因
- [ ] 系统状态可以持久化和恢复

#### Phase 1.1 新增功能

- 风控规则配置化（JSON/YAML 配置文件）
- 策略配置管理界面（CLI 或简单 Web 界面）
- 订单状态自动同步（定时任务）
- 订单取消功能（OrderManager）
- 持仓一致性机制（position_snapshot + 成交驱动更新 + 定期 reconcile）
- 持仓不一致报警和自动修复
- 账户快照功能（每日自动快照）

---

### Phase 1.2: 补齐日志与可追溯

#### 涉及的模块（在 Phase 1.1 基础上）

1. **日志系统完善**
   - ✅ LogRepository（完整实现）
     - 操作日志（所有关键操作）
     - 审计日志（交易决策、风控检查、订单执行）
     - 错误日志（异常和错误）
     - 性能日志（延迟、吞吐量）

2. **可追溯性**
   - 信号追踪（Signal ID → Decision ID → Execution ID → Trade ID）
   - 决策追踪（决策原因、策略状态快照）
   - 风控追踪（风控检查结果、拒绝原因）
   - 执行追踪（订单提交、成交、滑点）

3. **监控和告警增强**
   - ⚠️ SystemMonitor（系统健康监控，简化版）
   - ⚠️ HealthChecker（组件健康检查，简化版）
   - ⚠️ AlertSystem（告警通知，邮件/日志，简化版）

#### 是否需要真实交易所

**建议**: 可以开始**小额真实交易测试**（如 100 USDT），但保持 Paper Trading 并行运行。

#### Phase 1.2 验收标准

- [ ] 所有关键操作都有审计日志
- [ ] 每笔交易可以完整追溯（信号 → 决策 → 执行 → 成交）
- [ ] 可以查询任意时间点的系统状态
- [ ] 可以回放历史交易流程
- [ ] 系统健康监控正常工作
- [ ] 告警系统能够及时通知（邮件）
- [ ] 日志可以按时间、组件、级别查询
- [ ] 持仓一致性监控和报警正常工作

#### Phase 1.2 新增功能

- 审计日志查询界面（CLI 或 Web）
- 交易追溯工具（查询完整链路）
- 系统健康仪表板（简单 Web 界面）
- 告警规则配置（邮件通知规则）
- 持仓一致性监控和报警

---

### 模块实现状态汇总（v1.1 修订）

| Phase | 模块 | 实现状态 | 说明 |
|-------|------|---------|------|
| 1.0 | SignalReceiver | ✅ 完整实现 | HTTP 入口，依赖 TradingViewAdapter |
| 1.0 | TradingViewAdapter | ✅ 完整实现 | 库，被 SignalReceiver 调用 |
| 1.0 | SignalParser | ✅ 完整实现 | 必须 |
| 1.0 | StrategyManager | ✅ 简化实现 | 仅单策略支持 |
| 1.0 | StrategyExecutor | ✅ 完整实现 | **核心，唯一真理版本** |
| 1.0 | RiskManager | ✅ 完整实现（1.0 基础，1.1 完善） | 必须 |
| 1.0 | PositionManager | ✅ 完整实现（1.0 基础，1.1 完善） | position_snapshot + reconcile |
| 1.0 | AccountManager | ✅ 完整实现 | 必须 |
| 1.0 | ExecutionEngine | ✅ 完整实现 | 必须 |
| 1.0 | OrderManager | ✅ MVP 实现（1.0 基础，1.1 完善） | 查询、取消、状态同步；改价延后 |
| 1.0 | TradeRepository | ✅ 完整实现 | 必须 |
| 1.0 | LogRepository | ⚠️ 简化实现（1.0 基础，1.2 完善） | 基础日志 |
| 1.0 | MarketDataAdapter | ✅ 完整实现 | 必须 |
| 1.0 | ExchangeAdapter | ✅ 完整实现 | 必须 |
| 1.1 | StrategyRepository | ✅ 简化实现 | 基础配置存储 |
| 1.1 | StrategyVersionManager | ⚠️ 简化实现 | 仅配置管理 |
| 1.2 | SystemMonitor | ⚠️ 简化实现 | 基础监控 |
| 1.2 | HealthChecker | ⚠️ 简化实现 | 基础检查 |
| 1.2 | AlertSystem | ⚠️ 简化实现 | 基础告警 |

**总计 MVP 模块**: 19 个
- ✅ 完整实现: 14 个
- ✅ MVP 实现: 1 个（OrderManager）
- ⚠️ 简化实现: 4 个
- ❌ 暂不实现: 9 个（评估优化系统、Shadow Strategy 等）

---

**文档结束**
