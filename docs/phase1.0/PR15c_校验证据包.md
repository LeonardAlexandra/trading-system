# PR15c：Phase1.0 遗漏接口补齐 — 校验证据包

## 一、新增/修改文件清单

### 新增文件（PR15c 交付物）
| 路径 | 说明 |
|------|------|
| `src/adapters/models.py` | PR8/PR9 数据模型：MarketData、AccountInfo、MarketDataError、AccountInfoError |
| `src/adapters/market_data.py` | PR8 MarketDataAdapter：get_market_data(symbol)→MarketData，超时/异常→MarketDataError |
| `src/account/manager.py` | PR9 AccountManager：get_account_info()→AccountInfo，exchange_adapter + balance_repo fallback |
| `tests/adapters/test_market_data.py` | MarketDataAdapter 单元测试（配置价格、无价格抛错、超时、异常封装） |
| `tests/account/test_manager.py` | AccountManager 单元测试（exchange 正常、fallback、无 fallback 抛错） |
| `tests/risk/test_manager.py` | RiskManager 余额检查单元测试（开启拒单、关闭通过、充足通过） |
| `tests/integration/test_risk_balance_gate.py` | 集成测试：开启资金检查且余额不足时拒单，无订单/成交 |

### 修改文件
| 路径 | 说明 |
|------|------|
| `src/app/dependencies.py` | 注入 market_data_adapter、account_manager（非 None），不改变策略/执行路径 |
| `src/execution/risk_manager.py` | 支持注入 account_manager、market_data_adapter；可配置 enable_balance_checks、enable_total_exposure_checks（默认 false） |
| `src/execution/risk_config.py` | RiskConfig 增加 enable_balance_checks、enable_total_exposure_checks、max_exposure_ratio、quote_asset_for_balance |
| `src/execution/exchange_adapter.py` | ExchangeAdapter 抽象 get_account_info()；PaperExchangeAdapter/DryRunExchangeAdapter 实现 |
| `src/config/app_config.py` | RiskSectionConfig 增加 PR15c 开关；load_app_config 设置 _raw_config 供 worker 的 MarketDataAdapter 读取 paper.prices |
| `src/execution/execution_worker.py` | 每任务创建 MarketDataAdapter、AccountManager 并注入 RiskManager，使用 RiskConfig.from_app_config |
| `src/repositories/balance_repository.py` | list_all() 供 AccountManager fallback 组装 AccountInfo |

---

## 二、pytest 全量输出摘要

- **命令**：`cd trading_system && .venv/bin/python -m pytest tests/ -v --tb=short`
- **结果**：**102 passed** in ~2.2s

### 新增测试文件通过情况
| 测试文件 | 用例数 | 结果 |
|----------|--------|------|
| `tests/adapters/test_market_data.py` | 5 | 全部通过 |
| `tests/account/test_manager.py` | 3 | 全部通过 |
| `tests/risk/test_manager.py` | 3 | 全部通过 |
| `tests/integration/test_risk_balance_gate.py` | 1 | 通过 |

### 回归保障（happy path 相关）
| 测试文件 | 说明 |
|----------|------|
| `tests/integration/test_tradingview_webhook.py` | Webhook 验签、accepted、去重等 — 全部通过 |
| `tests/integration/test_execution_worker.py` | Worker 拉取 RESERVED、FILLED、并发幂等、reason_code 契约 — 全部通过 |
| `tests/integration/test_execution_events.py` | 事件落库、重试流、审计 — 全部通过 |
| `tests/integration/test_pr13_safety_valves.py` | PR13 安全阀 — 全部通过 |
| `tests/integration/test_pr14a_live_gate_and_shared_state.py` | PR14a 实盘门禁与共享状态 — 全部通过 |
| `tests/integration/test_pr15b_okx_create_order_closed_loop.py` | PR15b OKX 下单闭环 — 全部通过 |

---

## 三、默认配置不改变行为的说明

### 默认开关值（与现有 PR13/PR14/PR15b happy path 一致）
| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `risk.enable_balance_checks` | **false** | 不进行余额检查，BUY 单不查 AccountInfo/MarketData |
| `risk.enable_total_exposure_checks` | **false** | 不进行总敞口检查 |

### 行为保证
1. **交易链路**：默认下 RiskManager 不调用 account_manager / market_data_adapter，仅执行原有 4 条规则（冷却、同向去重、最大仓位、单笔最大量）；若未注入 position_repo/dom_repo/risk_state_repo（如部分测试/worker 场景），则对应规则被跳过，与改动前一致。
2. **Webhook → RESERVED**：不变；仍由 SignalApplicationService 占位，不经过 RiskManager。
3. **Worker execute_one**：默认 risk_config 来自 AppConfig，enable_balance_checks=false，故不触发余额/敞口检查；signal 决策透传并执行的 happy path 不变。
4. **依赖注入**：deps.market_data_adapter 与 deps.account_manager 被初始化为非 None，仅保证可被独立调用与测试，未塞入策略或执行路径逻辑。

---

## 四、交付物与 Phase1.0 文档对齐

- **PR8**：MarketDataAdapter.get_market_data(symbol)→MarketData（价格、可选订单簿），错误处理（超时/网络等）→MarketDataError；交付 `src/adapters/market_data.py`、`src/adapters/models.py`（含 MarketData）。
- **PR9**：AccountManager.get_account_info()→AccountInfo（内部通过 ExchangeAdapter.get_account_info 或 balance_repo fallback）；用于风控；交付 `src/account/manager.py`、`tests/account/test_manager.py`。
- **PR10**：RiskManager 具备单笔交易风险检查（仓位、资金）与账户级风险检查（总仓位、资金充足性）；通过 risk.enable_balance_checks / risk.enable_total_exposure_checks 可配置，默认关闭。

以上为 PR15c 校验证据包。
