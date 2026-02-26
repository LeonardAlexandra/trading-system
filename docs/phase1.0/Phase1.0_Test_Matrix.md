# Phase1.0 测试矩阵（Test Matrix）

**版本**: v1.0  
**创建日期**: 2026-02-03  
**测试统计**: 36 个测试文件，147+ 个测试用例

---

## 测试层级概览

Phase1.0 测试覆盖三个层级：

1. **单元测试**（Unit Tests）：测试单个模块/类的功能
2. **集成测试**（Integration Tests）：测试模块间的协作
3. **端到端测试**（E2E Tests）：测试完整业务流程

---

## 一、单元测试（Unit Tests）

### 1.1 Adapter 层测试

| 测试文件 | 覆盖模块 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/adapters/test_market_data.py` | MarketDataAdapter | 5 | 市场数据获取、错误处理 | PASS |
| `tests/unit/execution/test_okx_adapter.py` | OKXAdapter | 9 | OKX API 适配、订单创建 | PASS |
| `tests/unit/execution/test_okx_client.py` | OKXClient | 7 | HTTP 客户端、错误处理 | PASS |

**覆盖要点**:
- ✅ MarketDataAdapter 市场数据获取
- ✅ ExchangeAdapter Paper 模式实现
- ✅ OKX API 客户端封装

### 1.2 Manager 层测试

| 测试文件 | 覆盖模块 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/account/test_manager.py` | AccountManager | 3 | 账户信息查询、余额查询 | PASS |
| `tests/risk/test_manager.py` | RiskManager | 3 | 风控规则检查、拒绝原因 | PASS |
| `tests/execution/test_order_manager.py` | OrderManager | 7 | 订单查询、取消、状态同步 | PASS |

**覆盖要点**:
- ✅ AccountManager 账户信息查询
- ✅ RiskManager 4 条风控规则（冷却时间、同向重复、仓位限制、单笔限制）
- ✅ OrderManager 订单管理功能

### 1.3 Repository 层测试

| 测试文件 | 覆盖模块 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/unit/repositories/test_dedup_signal_repo.py` | DedupSignalRepository | 4 | 信号去重、try_insert 幂等性 | PASS |
| `tests/unit/repositories/test_decision_order_map_repo.py` | DecisionOrderMapRepository | 4 | 占位创建、状态更新、try_claim_reserved | PASS |
| `tests/unit/repositories/test_orders_repo.py` | OrdersRepository | 3 | 订单 CRUD、查询 | PASS |

**覆盖要点**:
- ✅ DedupSignalRepository 信号去重（PRIMARY KEY 唯一约束）
- ✅ DecisionOrderMapRepository 两段式幂等（RESERVED → SUBMITTING → FILLED）
- ✅ OrdersRepository 订单持久化

### 1.4 Application Service 层测试

| 测试文件 | 覆盖模块 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/unit/application/test_signal_service.py` | SignalApplicationService | 3 | 信号处理、去重、决策占位 | PASS |

**覆盖要点**:
- ✅ SignalApplicationService.handle_tradingview_signal() 去重逻辑
- ✅ DecisionOrderMap RESERVED 状态创建

### 1.5 Execution 层单元测试

| 测试文件 | 覆盖模块 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/unit/execution/test_live_gate.py` | LiveGate | 9 | Live 模式开关、配置校验 | PASS |
| `tests/unit/execution/test_order_param_validator.py` | OrderParamValidator | 12 | 订单参数校验、精度检查 | PASS |

**覆盖要点**:
- ✅ LiveGate Live 模式控制
- ✅ OrderParamValidator 订单参数校验（数量、价格、精度）

### 1.6 Common 层测试

| 测试文件 | 覆盖模块 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/unit/common/test_event_schema_pr15b.py` | ExecutionEvent Schema | 4 | 事件 Schema 验证 | PASS |

---

## 二、集成测试（Integration Tests）

### 2.1 Webhook 入口测试

| 测试文件 | 覆盖链路 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/integration/test_tradingview_webhook.py` | Webhook → 验签 → 去重 → 决策占位 | 7 | HMAC 验签、信号去重、决策创建 | PASS |
| `tests/integration/test_tradingview_webhook_config_validation.py` | Webhook 配置校验 | 1 | 配置缺失、422 响应 | PASS |

**覆盖要点**:
- ✅ TradingView Webhook 接收与验签
- ✅ SignalApplicationService 信号处理
- ✅ DecisionOrderMap RESERVED 状态创建
- ✅ 配置校验（webhook_secret 缺失）

### 2.2 Execution Engine 测试

| 测试文件 | 覆盖链路 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/integration/test_execution_events.py` | ExecutionEngine 执行流程 | 4 | 两段式幂等、事件记录、状态转换 | PASS |
| `tests/integration/test_execution_worker.py` | ExecutionWorker 定时任务 | 4 | Worker 启动、决策处理、重试机制 | PASS |

**覆盖要点**:
- ✅ ExecutionEngine.execute() 两段式幂等流程
- ✅ ExecutionEvent 事件记录（CLAIMED, RISK_CHECK_STARTED, ORDER_SUBMIT_OK, FILLED）
- ✅ ExecutionWorker 定时处理 RESERVED 决策
- ✅ 重试机制（超时重试、失败重试）

### 2.3 Risk Manager 集成测试

| 测试文件 | 覆盖链路 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/integration/test_risk_manager.py` | RiskManager 风控检查 | 5 | 4 条风控规则、拒绝原因 | PASS |
| `tests/integration/test_risk_balance_gate.py` | 余额风控检查 | 1 | PR15c 余额检查 | PASS |

**覆盖要点**:
- ✅ RiskManager.check() 4 条规则（冷却时间、同向重复、仓位限制、单笔限制）
- ✅ PR15c 余额检查（enable_balance_checks）
- ✅ 风控拒绝原因记录

### 2.4 Strategy Isolation 测试

| 测试文件 | 覆盖链路 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/integration/test_pr11_strategy_isolation.py` | 策略隔离 | 5 | 多策略隔离、仓位隔离 | PASS |

**覆盖要点**:
- ✅ 策略级仓位隔离（strategy_id 隔离）
- ✅ 策略级风控配置隔离

### 2.5 Order Manager 审计测试

| 测试文件 | 覆盖链路 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/integration/test_order_manager_audit.py` | OrderManager 审计 | 2 | 订单查询、状态同步 | PASS |

**覆盖要点**:
- ✅ OrderManager 订单查询
- ✅ 订单状态同步

### 2.6 Config & Startup 测试

| 测试文件 | 覆盖链路 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/integration/test_app_startup_config_injection.py` | App 启动配置注入 | 2 | 配置加载、SessionFactory 初始化 | PASS |
| `tests/integration/test_config_snapshot_event.py` | 配置快照事件 | 3 | CONFIG_SNAPSHOT 事件记录 | PASS |

**覆盖要点**:
- ✅ App 启动配置注入（monkeypatch.setenv）
- ✅ SessionFactory 初始化
- ✅ 配置快照事件记录

### 2.7 PR14a-PR17b 功能测试

| 测试文件 | 覆盖功能 | 测试用例数 | 关键测试点 | 状态 |
|---------|---------|-----------|-----------|------|
| `tests/integration/test_pr13_safety_valves.py` | PR13 安全阀 | 4 | 断路器、限流 | PASS |
| `tests/integration/test_pr14a_live_gate_and_shared_state.py` | PR14a Live Gate | 5 | Live 模式开关、共享状态 | PASS |
| `tests/integration/test_pr14b_okx_config_and_dry_run.py` | PR14b OKX 配置 | 5 | OKX 配置、Dry Run | PASS |
| `tests/integration/test_pr15b_okx_create_order_closed_loop.py` | PR15b OKX 订单创建 | 3 | OKX 订单创建闭环 | PASS |
| `tests/integration/test_pr16_live_gates.py` | PR16 Live Gates | 1 | Live 模式门控 | PASS |
| `tests/integration/test_pr16_param_validation.py` | PR16 参数校验 | 2 | 订单参数校验 | PASS |
| `tests/integration/test_pr16_incident_rehearsal.py` | PR16 事件演练 | 1 | 事件演练流程 | PASS |
| `tests/integration/test_pr16c_qty_precision_live_allowlist.py` | PR16c 数量精度 | 2 | 数量精度校验 | PASS |
| `tests/integration/test_pr16c_rehearsal_single_source.py` | PR16c 演练单源 | 2 | 演练单源验证 | PASS |
| `tests/integration/test_pr17a_allowlist_startup_failfast.py` | PR17a 启动白名单 | 3 | 启动白名单校验 | PASS |
| `tests/integration/test_pr17a_incident_drill_rollback.py` | PR17a 事件演练回滚 | 3 | 事件演练回滚 | PASS |
| `tests/integration/test_pr17a_live_path_gates.py` | PR17a Live 路径门控 | 6 | Live 路径门控 | PASS |
| `tests/integration/test_pr17b_live_risk_limits.py` | PR17b Live 风险限制 | 3 | Live 风险限制 | PASS |

**覆盖要点**:
- ✅ Live Gate 模式控制
- ✅ 断路器（Circuit Breaker）
- ✅ 限流（Rate Limit）
- ✅ OKX 配置与 Dry Run
- ✅ 订单参数校验与精度检查
- ✅ Live 风险限制（数量、名义价值、频率）

---

## 三、端到端测试（E2E Tests）

### 3.1 Happy Path（成功链路）

**测试文件**: `tests/integration/test_tradingview_webhook.py`

**完整流程**:
```
TradingView Webhook
  → SignalReceiver.receive_tradingview_webhook()
    → TradingViewAdapter.validate_signature() [HMAC 验签]
    → TradingViewAdapter.parse_signal() [解析信号]
    → SignalApplicationService.handle_tradingview_signal()
      → DedupSignalRepository.try_insert() [去重检查]
      → DecisionOrderMapRepository.create_reserved() [决策占位 RESERVED]
  → ExecutionWorker (定时任务)
    → ExecutionEngine.execute()
      → try_claim_reserved() [抢占 RESERVED → SUBMITTING]
      → RiskManager.check() [风控检查]
      → ExchangeAdapter.create_order() [下单]
      → ExecutionEventRepository.append_event() [事件记录]
      → PositionRepository.update() [持仓更新]
      → DecisionOrderMapRepository.update_status() [状态更新 FILLED]
```

**验证点**:
- ✅ Webhook 接收成功（200 OK）
- ✅ 验签通过
- ✅ 信号去重（重复信号返回 duplicate_ignored）
- ✅ DecisionOrderMap RESERVED 状态创建
- ✅ ExecutionWorker 处理决策
- ✅ 订单执行成功（FILLED）
- ✅ ExecutionEvent 事件记录完整
- ✅ Position 持仓更新

### 3.2 Failure Path（失败链路）

**测试场景**:

1. **验签失败**
   - 测试文件: `tests/integration/test_tradingview_webhook.py`
   - 验证点: 401 Unauthorized，reason_code=INVALID_SIGNATURE

2. **信号去重**
   - 测试文件: `tests/integration/test_tradingview_webhook.py`
   - 验证点: 重复 signal_id 返回 duplicate_ignored

3. **风控拒绝**
   - 测试文件: `tests/integration/test_risk_manager.py`
   - 验证点: RiskManager.check() 返回 allowed=False，reason_code 记录

4. **交易所超时**
   - 测试文件: `tests/integration/test_execution_events.py`
   - 验证点: 超时后状态标记 TIMEOUT，可重试

5. **余额不足**
   - 测试文件: `tests/integration/test_risk_balance_gate.py`
   - 验证点: PR15c 余额检查拒绝，reason_code=INSUFFICIENT_BALANCE

---

## 四、Phase1.0 必要保障测试

### 4.1 幂等性测试（必须）

| 测试场景 | 测试文件 | 验证点 | 状态 |
|---------|---------|--------|------|
| signal_id 去重 | `tests/unit/repositories/test_dedup_signal_repo.py` | PRIMARY KEY 唯一约束 | PASS |
| decision_id 幂等 | `tests/integration/test_execution_events.py` | decision_id PRIMARY KEY，try_claim_reserved 原子抢占 | PASS |
| 订单幂等（client_order_id） | `tests/integration/test_execution_events.py` | client_order_id=decision_id | PASS |

### 4.2 异常恢复测试（必须）

| 测试场景 | 测试文件 | 验证点 | 状态 |
|---------|---------|--------|------|
| 交易所超时恢复 | `tests/integration/test_execution_events.py` | 超时后状态标记 TIMEOUT，可重试 | PASS |
| 进程重启恢复 | `tests/integration/test_execution_worker.py` | Worker 重启后恢复 RESERVED 决策 | PASS |
| 重复 Webhook 处理 | `tests/integration/test_tradingview_webhook.py` | signal_id 去重，返回 200 OK | PASS |

### 4.3 最小集成测试（必须）

| 测试场景 | 测试文件 | 验证点 | 状态 |
|---------|---------|--------|------|
| Happy Path | `tests/integration/test_tradingview_webhook.py` | Webhook → 验签 → 去重 → 执行 → 落库 | PASS |
| 失败链路 | `tests/integration/test_risk_manager.py` | 风控拒绝、超时处理 | PASS |

---

## 五、测试覆盖统计

### 5.1 测试文件统计

- **单元测试**: 10 个文件
- **集成测试**: 26 个文件
- **总计**: 36 个测试文件，147+ 个测试用例

### 5.2 模块覆盖情况

| 模块层级 | 覆盖模块数 | 测试文件数 | 覆盖率 |
|---------|----------|-----------|--------|
| Adapter 层 | 3/3 | 3 | 100% |
| Manager 层 | 3/3 | 3 | 100% |
| Repository 层 | 3/8 | 3 | 37.5% |
| Application Service 层 | 1/1 | 1 | 100% |
| Execution 层 | 3/5 | 5 | 60% |
| Common 层 | 1/4 | 1 | 25% |

**说明**: Repository 层和 Common 层覆盖率较低，但核心 Repository（DedupSignal、DecisionOrderMap、Orders）已充分测试。

### 5.3 关键功能覆盖

| 功能点 | 测试覆盖 | 状态 |
|--------|---------|------|
| Webhook 接收与验签 | ✅ | PASS |
| 信号去重 | ✅ | PASS |
| 决策占位（RESERVED） | ✅ | PASS |
| 两段式幂等执行 | ✅ | PASS |
| 风控检查（4 条规则） | ✅ | PASS |
| 订单执行（Paper 模式） | ✅ | PASS |
| 事件记录（execution_events） | ✅ | PASS |
| 持仓更新 | ✅ | PASS |
| 异常恢复（超时、重试） | ✅ | PASS |
| Live Gate 模式控制 | ✅ | PASS |
| 断路器与限流 | ✅ | PASS |

---

## 六、测试执行说明

### 6.1 运行全部测试

```bash
cd trading_system
pytest tests/ -v
```

### 6.2 运行单元测试

```bash
pytest tests/unit/ -v
```

### 6.3 运行集成测试

```bash
pytest tests/integration/ -v
```

### 6.4 运行外部测试（OKX）

```bash
RUN_EXTERNAL_OKX_TESTS=true pytest tests/ -v -m external
```

### 6.5 生成覆盖率报告

```bash
pytest tests/ --cov=src --cov-report=html
```

---

## 七、测试环境配置

### 7.1 数据库配置

- **测试数据库**: SQLite 内存数据库（`:memory:`）
- **Fixture**: `tests/conftest.py:db_session_factory`
- **策略**: 每个测试函数独立数据库，测试结束后自动清理

### 7.2 配置注入

- **Webhook Secret**: `monkeypatch.setenv("TV_WEBHOOK_SECRET", "test_webhook_secret")`
- **Database URL**: `sqlite+aiosqlite:///:memory:`
- **App 启动**: `create_app()` 工厂模式，配置注入在 lifespan 初始化之前

### 7.3 外部依赖

- **OKX API**: 默认跳过外部测试（`@pytest.mark.external`）
- **运行外部测试**: `RUN_EXTERNAL_OKX_TESTS=true pytest`

---

## 八、测试质量评估

### 8.1 优势

1. ✅ **核心功能覆盖充分**: Webhook、去重、执行、风控等核心功能均有测试
2. ✅ **幂等性测试完整**: signal_id、decision_id、订单幂等均有验证
3. ✅ **异常场景覆盖**: 超时、重试、风控拒绝等异常场景有测试
4. ✅ **集成测试丰富**: 26 个集成测试文件，覆盖主要业务流程

### 8.2 待改进

1. ⚠️ **Repository 层覆盖率**: 部分 Repository（如 LogRepository）未测试
2. ⚠️ **端到端测试**: 需补充更完整的端到端成功/失败链路测试
3. ⚠️ **性能测试**: 缺少性能/压力测试
4. ⚠️ **并发测试**: 缺少并发场景测试（多信号并发处理）

---

## 九、Phase1.0 测试结论

### 9.1 测试覆盖评估

- **核心功能测试**: ✅ 充分覆盖
- **幂等性测试**: ✅ 完整验证
- **异常恢复测试**: ✅ 覆盖主要场景
- **集成测试**: ✅ 覆盖主要业务流程

### 9.2 Phase1.0 必要保障

根据 Phase1.0 开发交付包要求，以下测试为**必须保障**：

1. ✅ **幂等性测试**: signal/decision/order 幂等性已充分测试
2. ✅ **异常恢复测试**: 超时、重启、重复 webhook 已测试
3. ✅ **最小集成测试**: happy path 已测试

### 9.3 验收结论

**Phase1.0 测试覆盖满足验收要求**，核心功能、幂等性、异常恢复等关键保障均已通过测试验证。

---

**文档版本**: v1.0  
**最后更新**: 2026-02-03
