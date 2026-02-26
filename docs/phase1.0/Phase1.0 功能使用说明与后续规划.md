# TradingView 交易系统 - 功能使用说明与后续规划

**文档用途**：作为与 Cursor / ChatGPT 沟通的需求基线，用于梳理后续 Phase 与「可学习、可监控、可统计」的扩展方向。  
**当前基线**：Phase1.0 已封版，仅实现**基础功能基座**。

---

## 一、当前系统功能边界（Phase1.0 已实现）

### 1.1 核心能力概览

| 能力 | 说明 | 实现位置/证据 |
|------|------|----------------|
| **TradingView Webhook 接收** | 接收 POST、HMAC-SHA256 验签、原始 body 验签 | `src/app/routers/signal_receiver.py`、`src/adapters/tradingview_adapter.py` |
| **信号解析与去重** | 解析为 StandardizedSignal、按 signal_id 永久去重（DB 唯一约束） | `src/application/signal_service.py`、`dedup_signal` 表、`DedupSignalRepository` |
| **单策略决策与占位** | 信号 → 决策占位（RESERVED）→ decision_order_map 幂等 | `decision_order_map` 表、`DecisionOrderMapRepository.try_claim_reserved()` |
| **风控** | 单笔/账户检查、限频、断路器 | `src/execution/risk_manager.py`、rate_limit_state / circuit_breaker_state 表 |
| **订单执行（幂等）** | decision_id 不重复下单、client_order_id=decision_id、异常状态独立落库 | `src/execution/execution_engine.py`、orders/trade 落库、execution_events |
| **Paper 模式** | 单交易所、Paper 即成交、无真实异步成交 | `src/execution/exchange_adapter.py`（Paper）、execution_engine 落库 |
| **单实例部署** | workers=1、无 Celery/Redis/队列 | `pyproject.toml`、Dockerfile、docker-compose |
| **DB 与迁移** | PostgreSQL/SQLite、Alembic、init_db.sh | `alembic/`、`scripts/init_db.sh`、docker-compose |

### 1.2 功能边界与限制（Phase1.0 明确不做的）

- **策略**：仅 1 个策略，无 StrategyManager 多策略、无策略切换、无 Shadow/Candidate。
- **执行**：仅 Paper；无真实交易所异步成交、无部分成交、无改价（仅查询/取消/状态同步）。
- **部署**：单实例（workers=1）；无水平扩展、无消息队列。
- **监控与告警**：无仪表板、无短信/电话告警；仅文件日志 + execution_events 表。
- **评估与优化**：无 Evaluator、无 MetricsCalculator、无 Optimizer、无策略回测、无自动晋升/淘汰。

以上均来自 `docs/系统使用指南-小白版.md`、`docs/MVP实现计划.md`、`docs/Phase1.0开发交付包.md`。

### 1.3 对外接口（Phase1.0）

- **GET** `/healthz`：健康检查。
- **POST** `/webhook/tradingview`：接收 TradingView Webhook（验签 → 解析 → 去重 → 决策占位 → 返回）。
- 无账户/订单/持仓的对外 REST API；详见 `docs/API.md`。

### 1.4 已有数据与可追溯性

| 数据 | 用途 | 表/存储 |
|------|------|--------|
| 信号去重 | signal_id 唯一、防重放 | `dedup_signal` |
| 决策与订单映射 | decision_id 幂等、状态 RESERVED/FILLED/FAILED/TIMEOUT/UNKNOWN | `decision_order_map`、`orders` |
| 执行事件审计 | 按 decision_id + created_at 审计链路 | `execution_events` |
| 成交记录 | 成交落库 | `trade`、orders |
| 持仓快照 | 策略维度持仓（运行时真理源） | `position_snapshot` |
| 风控/限频/断路器 | 状态持久化 | `risk_state`、`rate_limit_state`、`circuit_breaker_state` |

当前**没有**：交易效果统计、决策逻辑结构化存储、学习/迭代历史、可视化统计面板。

---

## 二、已计划但在后续 Phase 开发的功能

来源：`docs/MVP实现计划.md`、`docs/模块接口与边界说明书.md`。

### 2.1 Phase 1.1（补齐风控与状态）

- 风控规则完整化（单笔/账户/策略级、VaR、集中度、连续亏损、回撤等）。
- 策略配置持久化与版本管理（StrategyRepository、StrategyVersionManager 简化版）。
- 订单状态定时同步、取消；持仓成交驱动更新 + 定期与交易所 reconcile（分层不一致处理：轻微/中等/严重）。
- 账户快照、风控拒绝原因记录、系统状态持久化与恢复。

### 2.2 Phase 1.2（补齐日志与可追溯）

- 完整审计日志（操作/决策/风控/执行/错误/性能）。
- 信号 → 决策 → 执行 → 成交 全链路追溯与查询。
- 按时间/组件/级别查询日志；简单健康检查与告警（如邮件）。

### 2.3 Phase 2.0（评估与优化系统）

- **Shadow Strategy**：ShadowExecutor、MarketSimulator、策略对比与评估。
- **评估**：Evaluator、MetricsCalculator、MetricsRepository。
- **策略管理增强**：StrategyStateMachine、PromotionEngine、EliminationEngine。
- **优化**：Optimizer（参数优化）、策略回测框架。
- 文档中**未**使用「强化学习」一词，但 Evaluator/Optimizer/晋升淘汰 为「策略评估与迭代」的基础设施。

### 2.4 技术扩展（Phase 2+）

- 多实例/多进程（需分布式锁、幂等与 DB 约束）。
- 多交易所/多产品形态。
- 订单改价（replace）。
- 可选：Celery/Redis/消息队列（当前 Phase 1.x 禁止）。

---

## 三、建议添加的拓展功能（面向愿景）

愿景可归纳为：**有输入、能持续强化学习迭代、实时监控、完整交易记录与决策逻辑、学习迭代历史、交易效果统计面板**。在现有基座上，建议按「数据 → 记录与逻辑 → 学习与迭代 → 监控与面板」分层扩展。

### 3.1 交易记录与决策逻辑（数据层）

- **结构化决策记录**：每条决策的输入（信号快照、策略 ID、参数版本）、输出（方向、数量、风控结果）、时间、环境（账户/持仓快照）。可新表或扩展现有 execution_events/decision_order_map。
- **交易与绩效快照**：每笔 trade 关联 decision_id、signal_id；可选：按日/周/策略的汇总表（笔数、盈亏、胜率等），便于统计与学习样本。
- **决策逻辑可解释存储**：决策原因（规则/模型版本、关键因子、风控通过/拒绝原因）存为结构化字段或 JSON，便于回溯与后续学习输入。

### 3.2 学习迭代与强化学习（能力层）

- **样本与特征**：以「信号 + 决策 + 结果（盈亏/持仓变化）」为样本，可选特征：市场状态、策略参数、风控状态等，供离线/在线学习。
- **策略参数/策略版本管理**：策略配置版本化（已有规划），并扩展为「可回滚、可 A/B 的版本」，便于做策略迭代与实验。
- **评估与反馈**：Evaluator/MetricsCalculator 产出收益、回撤、胜率、夏普等；这些指标可作为奖励信号，驱动参数优化或策略更新（与 Phase 2.0 Evaluator/Optimizer 对齐）。
- **强化学习/自适应**：在 Phase 2.0 评估与优化之上，增加「策略参数或信号权重随绩效自动更新」的闭环（例如基于策略梯度或 bandit），需明确状态/动作/奖励定义与安全边界（风控、回滚）。

### 3.3 实时监控与统计面板（展示层）

- **实时监控**：健康检查、信号接收量、决策/成交/拒绝计数、风控与断路器状态、最近错误；可先 REST/SSE，再考虑简单 Web 看板。
- **交易效果统计**：按日/周/策略的盈亏、胜率、最大回撤、交易次数；可从现有 trade/execution_events 聚合。
- **决策与学习历史**：决策列表（时间、信号、决策结果、风控结果）、策略/参数版本变更历史、评估报告与优化历史（与 Phase 2.0 评估/优化对接）。
- **告警**：关键风控、异常成交、系统异常等；先日志/邮件，再按需扩展通知渠道。

### 3.4 建议的扩展优先级（便于和 AI 沟通）

1. **先补齐「可观测」**：交易记录查询 API、决策/执行事件查询 API、基础统计（笔数、盈亏、按日汇总）。
2. **再补「可回顾」**：决策逻辑与原因存储、按 signal_id/decision_id 的完整链路查询。
3. **然后「可评估」**：与 Phase 1.2/2.0 对齐的 Evaluator、MetricsCalculator、简单报告。
4. **最后「可学习」**：策略/参数版本化、样本与指标闭环、再考虑强化学习或自动调参（含风控与回滚策略）。

---

## 四、与 Cursor / ChatGPT 沟通时的使用建议

1. **引用本文档**：说明「当前是 Phase1.0 基座，功能边界以《功能使用说明与后续规划》为准」，避免从零描述。
2. **明确 Phase**：例如「在 Phase 1.1 里做持仓 reconcile」「在 Phase 2.0 里做 Evaluator」，便于对接到现有文档的 PR/模块。
3. **区分「已有 / 计划 / 建议」**：  
   - 已有：第二节的表格与 1.4 数据表。  
   - 计划：Phase 1.1/1.2/2.0 的列表。  
   - 建议：第三节的扩展功能与优先级。
4. **需求拆解可按**：  
   - 数据模型（新表/新字段）。  
   - 接口（内部服务接口 + 对外 API）。  
   - 与现有模块的边界（不破坏 Phase1.0 契约）。  
   - 测试与验收标准（可追溯、可复现）。

---

## 五、关键文档索引

| 文档 | 用途 |
|------|------|
| `docs/Phase1.0开发交付包.md` | Phase1.0 PR 与验收、交付物 |
| `docs/MVP实现计划.md` | Phase 1.0/1.1/1.2/2.0 范围与顺序、约束 |
| `docs/模块接口与边界说明书.md` | 各层模块职责与接口 |
| `docs/系统使用指南-小白版.md` | 使用方式与 Phase1.0 限制 |
| `docs/API.md` | 当前 HTTP API |
| `docs/Phase1.0_系统完成度检查报告（终版）.md` | Phase1.0 封版结论 |

---

**总结**：当前系统是「信号接入 → 去重 → 单策略决策 → 风控 → 幂等执行 → 落库」的基座，**没有**策略评估、自动优化、强化学习、统计面板和完整决策逻辑存储。后续可在 Phase 1.1/1.2 上补齐风控与可追溯，在 Phase 2.0 上做评估与优化，再在此基础上按第三节的优先级增加「交易记录与决策逻辑 → 学习迭代 → 监控与统计面板」，逐步向「有输入、能学习迭代、可监控、可统计」的愿景推进。与 Cursor/ChatGPT 沟通时，可直接引用本文档的章节与表格做需求拆分与排期。
