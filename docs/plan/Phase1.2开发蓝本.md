# Phase 1.2 开发交付包（全文版）

**版本**: v2.0.0（全文扩写）  
**创建日期**: 2026-02-07  
**基于**: Phase划分与实现顺序-需求清单.md v2.0.0

**范围**: 本交付包覆盖 **Phase 1.2a**、**最小 Dashboard**、**Phase 1.2b** 三部分，作为一个整体交付包规划与验收。本文档为**可执行全文版**：工程师可据此直接实现，QA 可据此逐条验收；不引入 Phase 2.x 能力，不弱化既有架构级硬约束。

---

## A. 概述

### A.1 目标

- **1.2a**：系统具备全链路可追溯、决策输入快照落库（与 TradingDecision 同事务或等价原子流程，写入失败则禁止产出 TradingDecision）、审计与错误日志可查、监控告警与健康仪表板，满足与 Phase 2.0 的契约（含决策快照 schema 与查询方式）。
- **最小 Dashboard**：用户可在一个页面上看到最近决策/执行/成交与健康状态；**仅消费 Phase 1.2 提供的 API**，不在前端或 Dashboard 层计算业务指标；盈亏/汇总口径由本 Phase 写死定义（见 D.7、E TDASH-1）。
- **1.2b**：可审计——性能日志、多笔回放、审计查询界面与 MVP 生产就绪门禁完成，达到 MVP v1.0 生产就绪。

### A.2 完成判定

以下条件**全部**满足时，Phase 1.2 视为完成；**任一条未达成则 Phase 2.0 不得启动**。

- **1.2a**  
  - （1）1.2a-0～1.2a-5 全部验收通过（E 节每项验收用例可判定「做了/没做」「对/不对」）。  
  - （2）支撑 2.0 的最小审计与查询清单（含决策输入快照 schema 与查询方式）在本文档 C 节显式列出且已实现。  
  - （3）至少一条端到端链路在测试环境验证：按 decision_id 可查决策快照 + 全链路（signal→decision→决策快照→execution→trade）。  
  - （4）**决策快照时点一致性与不可变性**（B.1）：快照内容来自「本次决策实际使用的输入」、写入后不被覆盖或回写；存储层无按 decision_id 的 UPDATE/OVERWRITE。  
  - （5）**决策快照写入失败策略**（B.1）：写入失败时不产出 TradingDecision、触发强告警、拒绝本次决策输出（安全降级）、记录审计/错误日志；不得静默放行。
- **最小 Dashboard**  
  - （1）DASH-1、DASH-2 验收通过；（2）页面可访问且展示内容与 1.2a API 返回数据一致；（3）无前端侧业务指标计算，汇总数据来自后端 API。
- **1.2b**  
  - （1）1.2b-1～1.2b-3 全部验收通过；（2）多笔回放与审计查询界面与 1.2a 数据一致；（3）压力测试报告、故障恢复与备份恢复演练已交付并符合本包约定。

### A.3 Phase 1.2 终止条件（何时可进入 Phase 2.0）

- **允许进入 Phase 2.0 的充要条件**：A.2 中 1.2a、最小 Dashboard、1.2b 的**全部**条目均已验收通过，且 F 节端到端用例 E2E-1～E2E-5 及决策快照写入失败场景均已通过。
- **禁止启动 Phase 2.0 的情况**：若存在任一条未达成（包括但不限于：决策快照未与 TradingDecision 同事务、快照写入失败仍产出决策、Trace 返回空对象或缺失 missing_nodes、审计日志路径未覆盖、Dashboard 使用非 1.2 API 或前端自算指标），则 **Phase 2.0 不得启动**，须先闭环 Phase 1.2 缺陷后再进入 2.0。

### A.4 前置依赖

- Phase 1.0、Phase 1.1 已完成。
- 最小 Dashboard 与 1.2b 依赖 1.2a 验收通过。

### A.5 In-Scope / Out-of-Scope（写死）

| 类别 | 内容 |
|------|------|
| **In-Scope** | 决策输入快照（0.4）落库与按 decision_id/strategy_id+时间查询；全链路追溯 API（signal→decision→决策快照→execution→trade），含 COMPLETE/PARTIAL/NOT_FOUND 与 missing_nodes 规范；LogRepository 审计/操作/错误日志入库与按时间/组件/级别查询；SystemMonitor/HealthChecker/AlertSystem 增强；简单健康仪表板；持仓一致性监控与告警；最小 Dashboard 列表/汇总与页面（仅消费 1.2 API）；性能日志采集与按维度查询；多笔回放 API 与审计日志查询界面（CLI 或 Web）；MVP 压力测试、故障恢复、备份恢复门禁验收。 |
| **Out-of-Scope** | 策略或参数自动写回、Optimizer、Evaluator、策略版本发布门禁与回滚（属 Phase 2.x）；完整智能 BI、多租户与完整权限（属后续 BI 交付包）；「任意时间点系统状态」还原（本包不实现）；任何在 Phase 1.2 范围外的评估、学习、写回、发布、回滚能力。 |

---

## B. 架构级硬约束（0.1～0.4 在本 Phase 的落地）

本 Phase **不涉及** 0.1（学习边界）、0.2（Evaluator Contract）、0.3（发布门禁与回滚）的实现，但必须为 2.x 提供数据与契约基础。

| 约束 | 在本 Phase 的落地 |
|------|------------------|
| **0.1 学习边界** | 不实现；本 Phase 不修改策略参数或执行逻辑，仅提供可追溯与审计数据。 |
| **0.2 Evaluator Contract** | 不实现；本 Phase 提供「支撑 2.0 评估所需的最小审计与查询清单」（见下），含决策输入快照的 schema 与查询方式。 |
| **0.3 发布门禁与回滚** | 不实现；属 Phase 2.1。 |
| **0.4 决策输入快照** | **必须落地**。每次 StrategyExecutor 产出 TradingDecision 时，**在同一数据库事务或等价原子流程内**写入一条结构化决策输入快照，与 decision_id 强关联。快照内容**必须**为「本次决策实际使用的输入」；写入后为**不可变历史记录**，存储层**禁止**按 decision_id 的 UPDATE/OVERWRITE。**写入失败时**：**禁止**继续产出 TradingDecision；**必须**触发强告警并记录审计/错误日志；**必须**拒绝本次决策输出；**禁止**静默放行。支持按 decision_id 单条查询、按 strategy_id+时间范围批量查询。 |

**支撑 2.0 评估所需的最小审计与查询清单**（1.2a 验收须逐项覆盖；Phase 2.x 评估与学习只读依赖下列能力）：

- 按 strategy_id 的决策与成交查询（列表，支持时间范围）。
- 按时间段的决策与成交查询。
- 按 signal_id 的完整链路查询（signal→decision→决策快照→execution→trade）。
- 审计日志：至少决策、风控结果、执行结果可按时间/组件/级别查询并入库。
- **决策输入快照**：按 decision_id 可查、按 strategy_id+时间范围可批量查；schema 见 C；内容为本次决策实际输入、不可变、无 UPDATE/OVERWRITE。

### B.1 决策输入快照（0.4）工程级约束（写死）

以下约束为保证 Phase 2.x 评估与学习始终基于「真实、不可变、可追溯」的决策输入，实现与验收必须遵守。

#### 1️⃣ 时点一致性与不可变性

- **时点一致性**：Decision Snapshot 中的 `signal_state`、`position_state`、`risk_check_result` **必须**来自「本次决策实际使用的输入状态」，即 StrategyExecutor 在本轮决策计算时所读取的信号、持仓与风控结果；**禁止**使用决策完成之后或异步更新后的状态（如后续成交导致的持仓变化、后续风控重算结果等）。
- **不可变历史记录**：上述状态在写入快照后视为**不可变历史记录**。后续任何业务状态变化（持仓变更、风控规则变更、信号修正等）**不得**覆盖、回写或更新该条 decision_snapshot 记录；仅允许按 decision_id 做只读查询。存储层不得提供按 decision_id 的 update/overwrite 接口；若存在修正需求，只能通过新增版本或审计日志记录，不得改原快照。

#### 2️⃣ 写入失败时的系统行为（写死策略）

- **是否允许继续生成 TradingDecision**：**不允许**。决策快照写入失败时，**禁止**向下游产出或传递该笔 TradingDecision（即本次决策视为失败，不进入执行链路）。理由：若允许「无快照的决策」存在，Phase 2.x 无法基于真实输入评估该笔决策，违背可追溯与可评估契约。
- **是否触发强告警**：**必须**。决策快照写入失败时，**必须**触发强告警（高优先级告警，接入 AlertSystem，并写入审计/错误日志，包含 decision_id、strategy_id、失败原因、时间戳）。
- **是否进入安全降级**：**必须**。安全降级行为为：**拒绝本次决策输出**（不向 ExecutionEngine 传递 TradingDecision；不生成订单；该 signal 在本轮视为「决策失败」）。是否同时暂停该策略由配置或运维决定，但**至少**必须拒绝本次决策并记录失败，不得在快照未落库的情况下继续执行该笔决策。

### B.2 全链路追溯：链路不完整时的行为规范（写死）

当链路数据不完整时（例如：有 decision 但无 execution；有 execution 但无 trade；decision 存在但缺失 decision_snapshot），TraceQueryService / 回放 API **必须**遵守下列规则，禁止静默忽略或返回无说明的空结果。

#### 1️⃣ 返回结构与缺失标识

- **返回 partial 数据**：**必须**返回已存在的节点数据（如存在 signal 则返回 signal，存在 decision 则返回 decision），**不得**因某一节点缺失而整体返回空。缺失的节点在响应中**必须**显式标识。
- **缺失节点标识**（响应中**必须**包含以下之一或等价字段）：
  - **missing_nodes**：数组，列出缺失的节点类型，取值为枚举：`signal` | `decision` | `decision_snapshot` | `execution` | `trade`。示例：`["decision_snapshot", "trade"]`。
  - **missing_reason**：字符串或结构化说明（可选与 missing_nodes 对应），说明缺失原因（如 `NO_EXECUTION_FOR_DECISION`、`NO_TRADE_FOR_EXECUTION`、`NO_SNAPSHOT_FOR_DECISION`）；若统一用 missing_nodes 即可表达，可省略或与枚举一一对应。
- **链路完整度状态**：响应**必须**包含业务状态字段（如 **trace_status**），取值**写死**为：
  - `COMPLETE`：signal、decision、decision_snapshot、execution、trade 均存在。
  - `PARTIAL`：至少一个节点缺失；此时 **missing_nodes** 必填且非空。
  - `NOT_FOUND`：按查询键（如 signal_id / decision_id）未找到任何节点（如 signal 本身不存在）；此时可返回 404 或 200+ body 内 trace_status=NOT_FOUND、missing_nodes 含全部节点或等价表达）。
- **HTTP 状态码**：按 query key 查不到任何数据时返回 **404**；查到部分或全部数据时返回 **200**，通过 body 内 **trace_status** 与 **missing_nodes** 区分完整与部分。**禁止**在存在部分数据时返回 404 或空 body。

#### 2️⃣ 禁止行为

- **禁止**静默忽略缺失链路：不得在内部丢弃缺失信息后仅返回已有节点而不标注缺失。
- **禁止**直接返回空对象而无原因说明：不得在链路不完整时返回 `{}` 或 `null` 且无 trace_status / missing_nodes / missing_reason 等字段；若为列表接口（如 list_traces），单条结果为 partial 时该条**必须**带 trace_status 与 missing_nodes。

#### 3️⃣ 适用接口

- 单链路查询：`get_trace_by_signal_id`、`get_trace_by_decision_id`。
- 多笔回放：`list_traces` 返回的每条 TraceSummary **必须**包含 trace_status 与 missing_nodes（若该条为 PARTIAL）。

---

## C. 数据模型与 Schema

### C.1 新增/扩展表（完整字段与约束）

#### decision_snapshot（决策输入快照，落实 0.4）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | UUID 或 BIGSERIAL | 是 | 主键 |
| decision_id | VARCHAR(64) | 是 | 与 TradingDecision 强关联，唯一 |
| strategy_id | VARCHAR(64) | 是 | 策略 ID |
| created_at | TIMESTAMPTZ | 是 | 写入时间，默认 NOW() |
| signal_state | JSONB | 是 | 行情/信号状态：symbol, action, price, indicator_name, bar_time 等；**必须**为本次决策实际使用的信号输入 |
| position_state | JSONB | 是 | 持仓状态摘要：strategy_id, symbol, side, quantity 等；**必须**为本次决策时刻实际使用的持仓输入 |
| risk_check_result | JSONB | 是 | 风控检查结果：passed, reason, risk_check_id 等；**必须**为本次决策前风控实际结果 |
| decision_result | JSONB | 是 | 最终决策结果：decision_id, symbol, side, quantity, reason 等 |

- **唯一约束**：`UNIQUE(decision_id)`。
- **索引**：`(strategy_id, created_at)` 用于按策略+时间范围查询。
- **工程约束（写死）**：本表**仅追加、不可变**。**禁止**提供按 decision_id 或 id 的 UPDATE/DELETE；所有字段内容**必须**为「本次决策实际使用的输入状态」（B.1）。实现时 Repository 仅暴露 insert 与 select，不暴露 update/delete。

#### log（审计 / 操作 / 错误日志，统一表，用 level + event_type 区分）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | BIGSERIAL | 是 | 主键 |
| created_at | TIMESTAMPTZ | 是 | 写入时间 |
| component | VARCHAR(64) | 是 | 组件：signal_parser, risk_manager, execution_engine, strategy_executor 等 |
| level | VARCHAR(16) | 是 | 枚举：INFO, WARNING, ERROR, **AUDIT**；见 C.3 |
| event_type | VARCHAR(32) | 否 | 事件类型：decision_created, risk_check, execution_submit, trade_filled, decision_rejected 等 |
| message | TEXT | 是 | 摘要，**禁止**含完整 API Key、完整 token、明文密码；脱敏见 C.3 |
| payload | JSONB | 否 | 结构化扩展，**禁止**含敏感字段明文 |

- **索引**：`(created_at, component, level)`；分页查询时**必须**带 limit/offset 或 limit+游标，单次上限由接口约定（如 1000 条）。

#### perf_log（性能日志，1.2b）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | BIGSERIAL | 是 | 主键 |
| created_at | TIMESTAMPTZ | 是 | 时间 |
| component | VARCHAR(64) | 是 | 如 signal_processing, decision, execution |
| metric | VARCHAR(64) | 是 | 如 latency_ms, throughput_count |
| value | DECIMAL(18,6) | 是 | 数值 |
| tags | JSONB | 否 | 维度：strategy_id, symbol 等 |

- **存储**：可与 log 同库不同表，或同表用 component/metric 区分；实现时在 E 任务中选定一种并写死。

### C.2 既有表引用（不修改主键与核心语义）

- 追溯依赖：`dedup_signal`、decision_order_map（或等价）、`trade`、`orders`、`position_snapshot` 等。TraceQueryService 通过查询层聚合「signal→decision→decision_snapshot→execution→trade」，不修改既有表结构。

### C.3 日志类型区分与必写路径（写死）

- **AUDIT**：用于合规与 Phase 2.x 只读依赖。**必须**写入的路径：信号接收（signal_received）、决策生成（decision_created）、风控检查结果（risk_check_pass/risk_check_reject）、执行提交（execution_submit）、成交/失败（trade_filled/execution_failed）。上述任一路径发生，**必须**有一条 level=AUDIT 的 log 记录，含 event_type 与必要业务键（如 signal_id, decision_id）。
- **ERROR**：错误/异常；**必须**独立写入并可按 level=ERROR 查询；决策快照写入失败**必须**写 ERROR 并触发强告警（B.1）。
- **INFO/WARNING**：操作类、一般告警；与 AUDIT 区分：AUDIT 为「必须留痕」事件，INFO/WARNING 为辅助。
- **perf_log**：仅性能指标（延迟、吞吐），与业务审计分离；Phase 2.x 可只读消费用于可选维度，非 2.0 评估必选。

**脱敏（写死）**：message 与 payload 中**禁止**出现：完整 API Key、完整 token、明文密码。若需记录第三方标识，使用截断或哈希（如 key_last4）。实现时在 LogRepository 或写入前统一脱敏规则，并在交付包文档中列出。

**Phase 2.x 只读依赖**：决策输入快照（decision_snapshot）、按时间/组件/级别的 log 查询、全链路追溯 API。评估与学习**仅读取**上述数据，不写入；Phase 1.2 不得删除或变更上述表/接口的语义。

---

## D. 接口与边界

### D.1 决策输入快照（1.2a-0）

**写入**：与 StrategyExecutor 产出 TradingDecision **同一数据库事务或等价原子流程**内调用；写入失败则**禁止**向 ExecutionEngine 传递 TradingDecision，并执行 B.1 失败策略（强告警、拒绝决策、写审计/错误日志）。

```text
# 写入（内部调用）
DecisionSnapshotRepository.save(session, snapshot: DecisionSnapshot) -> None
# 抛出异常表示写入失败；调用方必须捕获并在失败时不产出 TradingDecision、触发告警、写日志

# 查询（只读）
DecisionSnapshotRepository.get_by_decision_id(session, decision_id: str) -> DecisionSnapshot | None
DecisionSnapshotRepository.list_by_strategy_time(session, strategy_id: str, start_ts, end_ts, limit: int=1000, offset: int=0) -> list[DecisionSnapshot]
```

- **禁止**提供按 decision_id 的 update/delete 接口。

### D.2 全链路追溯（1.2a-1）

**链路不完整时的行为**：遵守 B.2。**禁止**静默忽略缺失；**禁止**返回空对象且 HTTP=200 无 trace_status/missing_nodes。

**TraceResult 完整字段定义（写死）**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| trace_status | string | 是 | 枚举：COMPLETE \| PARTIAL \| NOT_FOUND |
| missing_nodes | list[string] | PARTIAL 时必填且非空；NOT_FOUND 时为全量五节点或空 | 枚举元素：signal, decision, decision_snapshot, execution, trade |
| missing_reason | string 或 map | 否 | 与 missing_nodes 对应说明，如 NO_EXECUTION_FOR_DECISION |
| signal | object | 有则填 | 至少含 signal_id, received_at, symbol, action 等 |
| decision | object | 有则填 | 至少含 decision_id, strategy_id, symbol, side, quantity, reason 等 |
| decision_snapshot | object | 有则填 | 与 C.1 decision_snapshot 表字段对应 |
| execution | object | 有则填 | 至少含 execution_id, decision_id, order_id, status 等 |
| trade | object | 有则填 | 至少含 trade_id, decision_id, symbol, side, quantity, price, realized_pnl 等 |

**单链路接口**：

```text
TraceQueryService.get_trace_by_signal_id(signal_id: str) -> TraceResult
TraceQueryService.get_trace_by_decision_id(decision_id: str) -> TraceResult
```

**HTTP 约定**：查不到任何节点时返回 **404**；查到部分或全部时返回 **200**，body 为 TraceResult（PARTIAL 时必含已存在节点 + missing_nodes 非空）。

**缺失场景返回示例（语义描述，实现时结构一致）**：

- **有 decision 无 execution**：trace_status=PARTIAL，missing_nodes=["execution","trade"]，返回 signal、decision、decision_snapshot（若有），不返回 execution、trade。
- **有 decision 无 decision_snapshot**：trace_status=PARTIAL，missing_nodes=["decision_snapshot"]，返回 signal、decision；若有 execution/trade 则一并返回。
- **有 execution 无 trade**：trace_status=PARTIAL，missing_nodes=["trade"]，返回 signal、decision、decision_snapshot（若有）、execution。
- **signal_id 不存在**：trace_status=NOT_FOUND，missing_nodes=["signal","decision","decision_snapshot","execution","trade"]（或等价），不返回任何节点对象；HTTP 可为 404 或 200。
- **禁止**：上述任一部分存在时返回 404 或 body 为空对象/null 且无 trace_status、missing_nodes。

**列表/回放**：

```text
TraceQueryService.list_decisions(strategy_id: str, start_ts, end_ts, limit=100, offset=0) -> list[DecisionSummary]
TraceQueryService.list_decisions_by_time(start_ts, end_ts, limit=100, offset=0) -> list[DecisionSummary]
TraceQueryService.get_recent_n(n: int, strategy_id?: str) -> list[DecisionSummary]
```

- DecisionSummary 至少含：decision_id, strategy_id, symbol, side, created_at；可选 trace_status（若为单条链路摘要）。

**HTTP 路由（写死路径）**：`GET /api/trace/signal/{signal_id}`、`GET /api/trace/decision/{decision_id}`；实现时与本文档一致。

### D.3 审计/操作/错误日志（1.2a-2）

```text
LogRepository.append(session, component: str, level: str, message: str, event_type: str=None, payload: dict=None) -> None
LogRepository.query(session, start_ts, end_ts, component=None, level=None, page=1, page_size=100) -> list[LogEntry]
```

- level 枚举：INFO, WARNING, ERROR, AUDIT。必写路径见 C.3；写入前**必须**脱敏（C.3）。

### D.4 监控与健康（1.2a-3）

```text
SystemMonitor.get_metrics() -> dict  # 至少：signals_received_count, orders_executed_count, error_count, error_rate
HealthChecker.check_all() -> HealthResult  # 至少：db_ok, exchange_ok, strategy_status
AlertSystem.evaluate_rules() -> list[Alert]  # 触发时写 log 且可选发邮件
```

### D.5 健康仪表板（1.2a-4）

```text
GET /api/health/summary  # 返回：overall_ok, metrics(signals_received_count, ...), recent_alerts[], recent_errors[]
```

- 数据来源**必须**为 SystemMonitor/HealthChecker/LogRepository，**禁止**硬编码假数据。

### D.6 持仓一致性（1.2a-5）

```text
PositionConsistencyMonitor.get_status(strategy_id: str=None) -> list[ConsistencyStatus]
# ConsistencyStatus: strategy_id, symbol, reconcile_status, last_reconcile_at
# 中等/严重不一致时调用 AlertSystem 触发告警
```

### D.7 最小 Dashboard（DASH-1 / DASH-2）

**边界（写死）**：最小 Dashboard **只消费** Phase 1.2 提供的 API；**禁止**在前端或 Dashboard 服务层计算业务指标（如自行从 trade 表聚合盈亏）；所有列表与汇总**必须**来自后端 API。

**汇总口径（写死，本 Phase 唯一口径）**：

- **笔数**：按 group_by=day 时为该日**成交笔数**（trade 表条数）；按 group_by=strategy 时为该策略**成交笔数**。
- **盈亏**：该周期内 **trade.realized_pnl** 之和（或等价字段）；无 trade 则盈亏为 0，**不**将风控拒绝/执行失败计为「亏损一笔」。

**API**：

```text
GET /api/dashboard/decisions?from=&to=&strategy_id=&limit=100   # 决策列表，字段至少 decision_id, strategy_id, symbol, side, created_at
GET /api/dashboard/executions?from=&to=&limit=100               # 执行/成交列表，字段至少 decision_id, symbol, side, quantity, price, realized_pnl, created_at
GET /api/dashboard/summary?from=&to=&group_by=day|strategy      # 返回 { "trade_count": N, "pnl_sum": decimal } 列表
GET /api/dashboard/recent?n=20                                  # 最近 N 笔决策或成交，由实现约定
```

- 前端：单页展示上述 API 的返回 + `/api/health/summary`；**禁止**前端根据本地数据重算 pnl/笔数。

### D.8 性能日志（1.2b-1）

```text
PerfLogRepository.record(session, component, metric, value, tags=None) -> None
PerfLogRepository.query(session, start_ts, end_ts, component=None, page=1, page_size=100) -> list[PerfLogEntry]
```

### D.9 多笔回放与审计查询（1.2b-2）

**链路不完整时的行为**：与单链路一致（B.2）。每条 TraceSummary **必须**包含 trace_status；若为 PARTIAL 则 **missing_nodes** 必填且非空，且含已存在节点或摘要；**禁止**静默返回空或省略缺失说明。

**TraceSummary 完整字段（写死）**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| trace_status | string | 是 | COMPLETE \| PARTIAL \| NOT_FOUND |
| missing_nodes | list[string] | PARTIAL 时非空 | 同 TraceResult |
| signal_id | string | 有则填 | |
| decision_id | string | 有则填 | |
| strategy_id | string | 有则填 | |
| created_at | string | 有则填 | 决策或成交时间 |
| summary | object | 有则填 | 节点摘要，不要求全量 |

```text
TraceQueryService.list_traces(start_ts, end_ts, strategy_id=None, limit=100, offset=0) -> list[TraceSummary]
```

**审计日志查询界面**：CLI 或 Web，筛选条件至少包含 start_ts, end_ts, component, level；调用 LogRepository.query；与 1.2a 入库数据一致。

- 错误码：400 参数错误、404 未找到、500 服务错误；列表**必须**分页，单次上限 100 条（或配置写死）。

---

## E. 任务拆分

每项任务的验收标准均为**可二元判定**：做了/没做、对/不对；禁止「人工感觉正常即可」类描述。输入/输出在下方各任务中明确。

### 1.2a 任务

| 任务编号 | 目的 | 输入 | 输出/可验证结果 | 实现要点 | 验收用例（checkbox） | 交付物 |
|----------|------|------|-----------------|----------|----------------------|--------|
| **T1.2a-0** | 落实 0.4 决策输入快照 | StrategyExecutor 本轮 signal/position/risk 与将产出的 TradingDecision | 同事务内 decision_snapshot 表新增一条且 decision_id 一致；或写入失败时无 TradingDecision 下传、有强告警与审计日志 | 与 TradingDecision 产出**同一事务**写快照；快照内容**仅**来自本轮 signal/position/risk；**禁止**按 decision_id 的 update/delete；写入失败：不传 TradingDecision、触发强告警、写 log、拒绝决策 | [ ] 给定一条决策，DB 中有一条 decision_snapshot 且 decision_id 一致；[ ] get_by_decision_id 返回完整四块（signal_state, position_state, risk_check_result, decision_result）；[ ] list_by_strategy_time 返回该策略时间范围内快照；[ ] 追溯 API 返回的链路含 decision_snapshot 节点；[ ] **时点一致性**：写入后修改持仓再查快照，快照内容未变；[ ] **不可变**：无 update(decision_id) 接口，尝试更新返回错误或不存在；[ ] **写入失败**：mock 写入失败，验证无 trade 产生、有 ERROR 日志与告警、ExecutionEngine 未收到该 decision | 迁移脚本、DecisionSnapshotRepository（仅 insert+select）、schema 文档、失败策略与告警说明 |
| **T1.2a-1** | 全链路追溯 API | signal_id 或 decision_id | TraceResult（含 trace_status、missing_nodes、已有节点对象） | 实现 D.2 全部接口；PARTIAL 必返回已有节点+missing_nodes；禁止空 body 200 | [ ] 完整链路：trace_status=COMPLETE，missing_nodes 为空，五节点均有；[ ] 缺 execution：PARTIAL，missing_nodes 含 execution/trade，返回 signal/decision/snapshot；[ ] 缺 decision_snapshot：PARTIAL，missing_nodes 含 decision_snapshot；[ ] 缺 trade：PARTIAL，missing_nodes 含 trade；[ ] 不存在的 signal_id：404 或 NOT_FOUND+无节点；[ ] 任一部分存在时 HTTP 200 且 body 非空、含 trace_status | 追溯服务、B.2 响应实现、契约说明 |
| **T1.2a-2** | 审计/操作/错误日志 | component, level, message, event_type?, payload? | 写入 log 表；query 返回分页列表 | 必写路径 C.3（信号/决策/风控/执行/成交/失败）；脱敏 C.3 | [ ] 发 signal→决策→执行→成交后，query(level=AUDIT) 含至少 4 条对应 event_type；[ ] query(start_ts, end_ts, component, level) 返回正确子集；[ ] 错误路径写 level=ERROR 可查；[ ] message/payload 无完整 key/token | LogRepository、脱敏规则文档 |
| **T1.2a-3** | 监控与告警 | 无（轮询或事件） | get_metrics() 含 signals/orders/error 相关；check_all() 含 db/exchange/strategy；告警触发时写 log/邮件 | 指标与健康见 D.4；告警规则可配置 | [ ] get_metrics() 返回含 signals_received_count 等；[ ] check_all() 返回各组件状态；[ ] 触发规则后存在 Alert 与 log/邮件 | 实现、告警配置示例 |
| **T1.2a-4** | 简单健康仪表板 | GET /api/health/summary | 200 + JSON（overall_ok, metrics, recent_alerts, recent_errors） | 数据来自 1.2a-3，禁止假数据 | [ ] 访问 URL 返回 200；[ ] 数据与 get_metrics/check_all/LogRepository 一致 | 健康仪表板页面与 API |
| **T1.2a-5** | 持仓一致性监控 | strategy_id? | list[ConsistencyStatus]；中/严重不一致时告警 | 读 position_snapshot/reconcile；与 AlertSystem 集成 | [ ] get_status() 返回 reconcile_status 等；[ ] 模拟不一致可触发告警 | 监控与告警集成 |

### 最小 Dashboard 任务

| 任务编号 | 目的 | 输入 | 输出/可验证结果 | 实现要点 | 验收用例（checkbox） | 交付物 |
|----------|------|------|-----------------|----------|----------------------|--------|
| **TDASH-1** | 列表与汇总 API | from, to, strategy_id?, group_by?, limit | 决策列表、执行/成交列表、summary(trade_count, pnl_sum) | 口径 D.7：笔数=trade 条数，盈亏=realized_pnl 之和；与 1.2a 同源 | [ ] GET decisions 返回列表；[ ] GET executions 返回列表；[ ] GET summary(group_by=day) 返回 trade_count+pnl_sum 与 trade 表聚合一致；[ ] 无前端/服务层自算 | 列表与汇总 API、口径文档 |
| **TDASH-2** | 最小 Dashboard 页面 | 浏览器访问 | 单页展示 decisions/executions/summary/health | **仅**调用 /api/dashboard/* 与 /api/health/summary；禁止前端计算 pnl/笔数 | [ ] 页面可访问；[ ] 列表与汇总数据与 API 响应一致（可对比接口）；[ ] 健康块与 /api/health/summary 一致 | 前端页面与路由 |

### 1.2b 任务

| 任务编号 | 目的 | 输入 | 输出/可验证结果 | 实现要点 | 验收用例（checkbox） | 交付物 |
|----------|------|------|-----------------|----------|----------------------|--------|
| **T1.2b-1** | 性能日志 | component, metric, value, tags? | perf_log 表有记录；query 可按时间/组件查 | 关键路径打点（信号/决策/执行） | [ ] 执行一条链路后 perf_log 有 latency 等；[ ] query 返回符合条件记录 | PerfLogRepository、打点说明 |
| **T1.2b-2** | 多笔回放与审计界面 | start_ts, end_ts, strategy_id?, limit, offset | list[TraceSummary] 每条约含 trace_status、PARTIAL 时 missing_nodes；审计界面可筛 log | TraceSummary 符合 D.9；审计界面调 LogRepository.query | [ ] list_traces 返回列表；[ ] 任一条 PARTIAL 含 missing_nodes 非空及已有节点摘要；[ ] 审计界面按时间/组件/级别筛选结果与 log 表一致 | 多笔回放 API、审计界面 |
| **T1.2b-3** | MVP 门禁验收 | 测试环境与脚本 | 压力测试报告、故障恢复记录、备份恢复文档与演练记录 | 负载与通过标准在实现文档写死 | [ ] 压力测试报告存在且结论通过；[ ] 故障恢复测试有记录；[ ] 备份与恢复文档存在且至少一次演练成功 | 报告与文档 |

---

## F. 测试与验收

### F.1 端到端用例

- **E2E-1（完整链路）**：发送一条 Webhook 信号 → 产生 decision → 同事务写入 decision_snapshot → 执行并成交 → 按 signal_id/decision_id 查询得到完整链路（含 decision_snapshot）；响应 trace_status=COMPLETE，missing_nodes 为空或不存在。**验收**：DB 有 1 条 trade、1 条 decision_snapshot，TraceResult 含五节点。
- **E2E-2（审计）**：触发一次风控拒绝或执行失败 → 审计日志中可查到对应 AUDIT/ERROR 记录；query 按时间/组件/级别可筛选。**验收**：LogRepository.query(level=AUDIT 或 ERROR) 含该事件。
- **E2E-3（Dashboard）**：打开最小 Dashboard 页面 → 展示最近决策/执行/成交、汇总、健康指标。**验收**：页面数据与 GET /api/dashboard/* 及 GET /api/health/summary 返回一致；无前端自算指标。
- **E2E-4（多笔回放）**：多笔回放 API 指定时间范围 → 返回 list[TraceSummary]；审计查询界面筛选 → 与 log 表一致。**验收**：list_traces 与 LogRepository.query 结果可对应。
- **E2E-5（链路缺失）**：构造「有 decision 但无 execution」或「有 decision 但无 decision_snapshot」或「有 execution 但无 trade」→ 调用 get_trace_by_signal_id 或 get_trace_by_decision_id → 验证：HTTP 200、trace_status=PARTIAL、missing_nodes 非空且与缺失一致、body 含已存在节点。验证不存在的 signal_id → 404 或 200+ trace_status=NOT_FOUND。**禁止**部分数据存在时返回 404 或空 body。
- **E2E-6（决策快照写入失败，必须覆盖）**：模拟 decision_snapshot 写入失败（如 DB 约束失败或 mock save 抛异常）→ 验证：**未**向 ExecutionEngine 传递 TradingDecision（即无对应 trade/order）；**已**触发强告警（AlertSystem 或等价有记录）；**已**写入 ERROR 或 AUDIT 日志（含 decision_id/strategy_id/失败原因）；该 signal 在本轮视为决策失败（可查 log 或拒绝状态）。**禁止**静默放行或仍产生 trade。

### F.2 回归清单

- Phase 1.0/1.1 已有 Happy Path、去重、对账、Resume 等用例仍通过。
- 1.2a 契约清单（B 节「支撑 2.0 评估所需的最小审计与查询清单」）逐项可查且已实现。
- 链路缺失：B.2 已落实；单链路与多笔回放在 PARTIAL/NOT_FOUND 下响应符合 D.2/D.9。
- 决策快照：B.1 时点一致性、不可变、写入失败策略已在 E2E-1 与 E2E-6 中显式覆盖。

### F.3 Phase 1.2 终止条件（与 A.3 一致）

**允许进入 Phase 2.0**：A.2 全部条目验收通过，且 E2E-1～E2E-6 全部通过。  
**禁止启动 Phase 2.0**：任一条未达成（含决策快照未同事务、写入失败仍产出决策、Trace 空对象或缺 missing_nodes、审计必写路径未覆盖、Dashboard 自算指标、汇总口径与 D.7 不一致等），须先闭环 Phase 1.2 后再启动 2.0。

---

## G. 风险与非功能性要求

- **性能**：追溯与 log/perf 查询**必须**分页（limit 默认 100，上限写死或配置）；**禁止**单次无上限全表扫描。日志量过大时采样或按 level 分级存储由实现文档写死策略。
- **安全**：log 的 message 与 payload **禁止**包含完整 API Key、完整 token、明文密码；脱敏规则见 C.3，实现时在 LogRepository 或写入前统一处理。
- **审计**：C.3 所列必写路径（信号接收、决策生成、风控结果、执行提交、成交/失败）**必须**有 level=AUDIT 或等价日志；决策快照写入失败**必须**有 ERROR 与告警。
- **告警**：决策快照写入失败**必须**触发强告警；告警去重与冷却（如 1 分钟内同类型只告警一次）在实现文档中写死；邮件依赖 SMTP 时配置与失败降级（如仅写 log）写死。
- **回滚**：本 Phase 不实现策略/参数回滚（属 2.1）；数据库迁移**必须**支持 alembic upgrade/downgrade，不得破坏已有表主键与唯一约束。

---

## H. 交付物清单

| 类别 | 交付物（可执行清单） |
|------|----------------------|
| **代码/配置** | Alembic 迁移脚本（decision_snapshot、log、perf_log 表）；DecisionSnapshotRepository（save, get_by_decision_id, list_by_strategy_time，无 update/delete）；TraceQueryService（get_trace_by_signal_id, get_trace_by_decision_id, list_decisions, list_decisions_by_time, get_recent_n, list_traces）及 TraceResult/TraceSummary 结构实现；LogRepository（append, query）与脱敏；SystemMonitor、HealthChecker、AlertSystem 实现；健康仪表板路由与前端；持仓一致性监控与告警；Dashboard 列表/汇总 API（口径 D.7）与前端；PerfLogRepository；审计查询界面（CLI 或 Web）。 |
| **文档** | 决策输入快照 schema（C.1）与写入/查询约定；支撑 2.0 的最小审计与查询清单（B 节）覆盖说明；日志 level/event_type 与必写路径（C.3）、脱敏规则；告警规则配置示例与失败降级；Dashboard 汇总口径（D.7）；压力测试负载与通过标准；备份与恢复流程文档。 |
| **证据包** | 压力测试报告（含通过/不通过结论）；故障恢复测试记录；备份与恢复演练记录；1.2a 契约清单逐项验收结果（可勾选表格）；E2E-1～E2E-6 执行结果记录。 |

---

**文档结束**
