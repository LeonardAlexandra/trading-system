# Phase 1.2 模块化开发交付包

**版本**: v1.0.0  
**创建日期**: 2026-02-07  
**最后修订**: 2026-02-07  
**基于**: Phase1.2 开发蓝本（系统宪法，不可改写语义）

---

## 一、推荐执行顺序（强制）

以下顺序为 Cursor/开发者的**推荐执行顺序**，不可调整。开发项必须按此顺序实施，以降低依赖冲突与返工风险。

| 步骤 | 开发项 | 说明 |
|------|--------|------|
| 1 | A1 / A2 / A3 | 数据库迁移（decision_snapshot、log、perf_log，可并行或按 A1→A2→A3 顺序） |
| 2 | C1 | 决策输入快照（DecisionSnapshotRepository + 同事务写入 + 写入失败策略） |
| 3 | C2 | 全链路追溯（TraceQueryService + B.2 链路不完整规范） |
| 4 | C3 | 审计/操作/错误日志（LogRepository + 必写路径 + 脱敏） |
| 5 | C4 | 监控与告警（SystemMonitor、HealthChecker、AlertSystem） |
| 6 | C5 | 健康仪表板（GET /api/health/summary） |
| 7 | C6 | 持仓一致性监控与告警 |
| 8 | B1 | 最小 Dashboard 列表与汇总 API（口径 D.7，仅消费 1.2a 数据） |
| 9 | B2 | 最小 Dashboard 页面（仅调用 /api/dashboard/* 与 /api/health/summary） |
| 10 | C7 | 性能日志（PerfLogRepository + 关键路径打点） |
| 11 | C8 | 多笔回放 API 与审计查询界面（list_traces + 界面） |
| 12 | C9 | MVP 门禁验收（压力测试、故障恢复、备份恢复） |
| 13 | D1 ~ D6 | 端到端与回归可验证点（E2E-1～E2E-6 及回归清单） |

### 模块级执行规则（强制）

1. Phase1.2 的开发必须严格按模块逐一推进。
2. 任一时刻，只允许存在 **一个“活跃开发模块”**。
3. 当正在开发某一模块（如 C2）时：
   - 禁止修改、实现、重构任何非本模块定义范围内的代码；
   - 禁止提前实现后续模块（如 C3~C9）的任何逻辑；
   - 禁止为“后续模块方便”而预埋代码、接口或占位实现。
4. 当前模块在 **未通过验收** 前，不得进入下一模块。
5. 若某模块验收失败，只允许在该模块范围内返工，不得牵连其他模块。

---

## 二、开发项与交付

### A. 数据库迁移（Migrations）

#### A1. decision_snapshot 表（决策输入快照，落实 0.4）

**目标**  
- 为每次 TradingDecision 提供与 decision_id 强关联的、不可变的决策输入快照存储，支撑 Phase 2.x 评估与审计；表仅追加、无 UPDATE/DELETE。

**开发范围（必须明确）**  
- 新增表 `decision_snapshot`，字段与约束严格按蓝本 C.1：  
  - 必填字段：id（UUID 或 BIGSERIAL）、decision_id（VARCHAR(64)）、strategy_id（VARCHAR(64)）、created_at（TIMESTAMPTZ）、signal_state（JSONB）、position_state（JSONB）、risk_check_result（JSONB）、decision_result（JSONB）。  
  - 唯一约束：`UNIQUE(decision_id)`。  
  - 索引：`(strategy_id, created_at)` 用于按策略+时间范围查询。  
- 迁移脚本：仅建表与索引，不提供、不暴露按 decision_id 或 id 的 UPDATE/DELETE；Repository 层在 C1 中仅暴露 insert 与 select。

**硬性约束（Strong Constraints）**  
- 本表为**仅追加、不可变**；存储层**禁止**提供按 decision_id 或 id 的 UPDATE/DELETE。  
- 所有字段内容**必须**为「本次决策实际使用的输入状态」（蓝本 B.1 时点一致性与不可变性）。  
- 迁移必须支持 alembic upgrade/downgrade，不破坏已有表主键与唯一约束。

**逻辑真理源（Source of Truth）**  
- 以数据库 `decision_snapshot` 表为准；决策输入历史以该表只读查询为准，不得改写。

**交付物（Deliverables）**  
- Alembic 迁移脚本：新增 `decision_snapshot` 表及唯一约束、索引。  
- 与 C.1 schema 一致的模型/字段定义或文档说明。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行（upgrade/downgrade 无报错，幂等）。  
- [ ] 表中存在 decision_id 唯一约束及 (strategy_id, created_at) 索引。  
- [ ] 文档或注释明确本表仅追加、不可变，无 update/delete 接口。

**绑定说明**  
本模块为 C1 及 D1、D6 提供表结构基础，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### A2. log 表（审计/操作/错误日志）

**目标**  
- 统一存储审计、操作、错误日志，支持按时间/组件/级别查询，满足 C.3 必写路径与脱敏要求。

**开发范围（必须明确）**  
- 新增表 `log`，字段与约束严格按蓝本 C.1：  
  - 必填字段：id（BIGSERIAL）、created_at（TIMESTAMPTZ）、component（VARCHAR(64)）、level（VARCHAR(16)）、message（TEXT）；可选 event_type（VARCHAR(32)）、payload（JSONB）。  
  - level 枚举：INFO, WARNING, ERROR, AUDIT。  
  - 索引：`(created_at, component, level)`；分页查询必须带 limit/offset 或 limit+游标，单次上限由接口约定（如 1000 条）。  
- 迁移脚本：仅建表与索引，不修改既有表。

**硬性约束（Strong Constraints）**  
- message 与 payload **禁止**含完整 API Key、完整 token、明文密码；脱敏规则在 C3 实现时统一（见 C3）。  
- 分页查询**必须**带 limit/offset 或等价机制，**禁止**单次无上限全表扫描。

**逻辑真理源（Source of Truth）**  
- 以数据库 `log` 表为准；审计与错误追溯以该表查询为准。

**交付物（Deliverables）**  
- Alembic 迁移脚本：新增 `log` 表及索引。  
- 与 C.1 一致的模型/字段定义或文档说明。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行且可回滚。  
- [ ] 表中存在 (created_at, component, level) 索引。  
- [ ] 文档明确 level 枚举与分页要求。

**绑定说明**  
本模块为 C3 及 D2 提供表结构基础，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### A3. perf_log 表（性能日志，1.2b）

**目标**  
- 存储性能指标（延迟、吞吐等），与业务审计分离，支持按时间/组件等维度查询。

**开发范围（必须明确）**  
- 新增表 `perf_log`（或与 log 同库不同表，实现时在交付包中写死一种）：  
  - 必填字段：id（BIGSERIAL）、created_at（TIMESTAMPTZ）、component（VARCHAR(64)）、metric（VARCHAR(64)）、value（DECIMAL(18,6)）；可选 tags（JSONB）。  
- 迁移脚本：仅建表及必要索引，不修改既有表。

**硬性约束（Strong Constraints）**  
- 与 log 表语义分离：perf_log 仅性能指标，log 为审计/操作/错误。  
- 查询**必须**分页，禁止单次无上限全表扫描。

**逻辑真理源（Source of Truth）**  
- 以数据库 `perf_log` 表为准。

**交付物（Deliverables）**  
- Alembic 迁移脚本：新增 `perf_log` 表（及选定存储方式的说明）。  
- 与 C.1 一致的模型/字段定义或文档说明。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行且可回滚。  
- [ ] 可写入并按时间/组件查询性能记录。  
- [ ] 文档明确与 log 的存储与语义边界。

**绑定说明**  
本模块为 C7 及 D4 提供表结构基础，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

### B. API 层

#### B1. 最小 Dashboard 列表与汇总 API（TDASH-1）

**目标**  
- 提供决策列表、执行/成交列表、汇总（笔数、盈亏）的 HTTP API，口径写死为 D.7，仅消费 Phase 1.2 数据，供最小 Dashboard 页面调用。

**开发范围（必须明确）**  
- 实现以下路由（路径与蓝本 D.7 一致）：  
  - `GET /api/dashboard/decisions?from=&to=&strategy_id=&limit=100`：决策列表，字段至少 decision_id, strategy_id, symbol, side, created_at。  
  - `GET /api/dashboard/executions?from=&to=&limit=100`：执行/成交列表，字段至少 decision_id, symbol, side, quantity, price, realized_pnl, created_at。  
  - `GET /api/dashboard/summary?from=&to=&group_by=day|strategy`：返回 `{ "trade_count": N, "pnl_sum": decimal }` 列表。  
  - `GET /api/dashboard/recent?n=20`：最近 N 笔决策或成交，由实现约定。  
- **汇总口径（写死）**：笔数 = 该周期 trade 表条数（按 group_by 聚合）；盈亏 = 该周期 trade.realized_pnl 之和；无 trade 则盈亏为 0，不将风控拒绝/执行失败计为「亏损一笔」。  
- 数据来源**必须**为 1.2a 已有表/服务（如 decision、trade、TraceQueryService 等），**禁止**在前端或本 API 层自行从原始表重算业务指标。

**硬性约束（Strong Constraints）**  
- 所有列表与汇总**必须**来自后端 API 与既定口径，禁止前端或 Dashboard 服务层计算业务指标（如自行从 trade 表聚合盈亏）。  
- 列表接口**必须**分页或 limit 上限（如单次最多 100 条）。  
- 与蓝本 D.7 口径完全一致，不得增删或改写。

**逻辑真理源（Source of Truth）**  
- 笔数、盈亏以数据库 trade 表及约定 group_by 聚合为准；决策/执行列表以 1.2a 数据源为准。

**交付物（Deliverables）**  
- 上述四个 GET 路由实现及响应模型（字段说明）。  
- 汇总口径文档（D.7 写死口径的显式说明）。

**验收口径（Acceptance Criteria）**  
- [ ] GET decisions/executions/summary/recent 返回 200 且字段符合蓝本。  
- [ ] GET summary(group_by=day) 的 trade_count、pnl_sum 与 trade 表聚合结果一致。  
- [ ] GET summary(group_by=strategy) 与按策略聚合一致。  
- [ ] 无 trade 时 pnl_sum 为 0；无前端/服务层自算指标。

**绑定说明**  
本模块至少需要满足 D3 中与其功能直接相关的可验证点，方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### B2. 最小 Dashboard 页面（TDASH-2）

**目标**  
- 单页展示最近决策/执行/成交、汇总、健康状态；仅消费 Phase 1.2 提供的 API，不在前端计算业务指标。

**开发范围（必须明确）**  
- 实现一个最小 Dashboard 页面（单页）：  
  - 展示内容：决策列表、执行/成交列表、汇总（笔数、盈亏）、健康状态（overall_ok, metrics, recent_alerts, recent_errors）。  
  - 数据来源**仅允许**：`GET /api/dashboard/decisions`、`GET /api/dashboard/executions`、`GET /api/dashboard/summary`、`GET /api/dashboard/recent`、`GET /api/health/summary`。  
- **禁止**在前端根据本地数据重算 pnl、笔数或任何业务指标；所有列表与汇总必须直接使用上述 API 返回数据展示。

**硬性约束（Strong Constraints）**  
- **禁止**前端或 Dashboard 层计算业务指标；汇总数据**必须**来自后端 API。  
- 页面可访问且展示内容与 1.2a/1.2b API 返回数据一致；健康块与 `/api/health/summary` 一致。

**逻辑真理源（Source of Truth）**  
- 页面展示以 API 响应为准；不引入额外数据源或本地计算。

**交付物（Deliverables）**  
- 最小 Dashboard 前端页面与路由。  
- 简短说明：调用的 API 列表及「无前端自算」的约定。

**验收口径（Acceptance Criteria）**  
- [ ] 页面可访问且展示决策/执行/汇总/健康。  
- [ ] 列表与汇总数据与直接调用 /api/dashboard/* 及 /api/health/summary 的响应一致（可对比验证）。  
- [ ] 健康块与 /api/health/summary 一致。  
- [ ] 无前端侧 pnl/笔数计算逻辑。

**绑定说明**  
本模块至少需要满足 D3 中与其功能直接相关的可验证点，方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

### C. 核心逻辑

#### C1. 决策输入快照（0.4）落库与写入失败策略（T1.2a-0）

**目标**  
- 在 StrategyExecutor 产出 TradingDecision 时，在同一数据库事务或等价原子流程内写入一条 decision_snapshot；写入失败时不产出 TradingDecision、触发强告警、写审计/错误日志、拒绝本次决策输出。

**开发范围（必须明确）**  
- **DecisionSnapshotRepository**：  
  - 仅暴露 `save(session, snapshot)`（插入）、`get_by_decision_id(session, decision_id)`、`list_by_strategy_time(session, strategy_id, start_ts, end_ts, limit, offset)`；**禁止**暴露按 decision_id 的 update/delete。  
  - save 失败时抛出异常，由调用方处理。  
- **StrategyExecutor 集成**：在产出 TradingDecision 的同一事务或等价原子流程内调用 `DecisionSnapshotRepository.save`；  
  - 快照内容**必须**来自本轮决策实际使用的 signal_state、position_state、risk_check_result 与 decision_result（蓝本 B.1 时点一致性）。  
  - 若 save 失败：**禁止**向 ExecutionEngine 传递该 TradingDecision；**必须**触发强告警（AlertSystem）；**必须**写入 ERROR 或 AUDIT 日志（含 decision_id、strategy_id、失败原因、时间戳）；**必须**拒绝本次决策输出（安全降级）；**禁止**静默放行。  
- **不可变性**：写入后存储层无按 decision_id 的 UPDATE/OVERWRITE；Repository 不提供 update/delete。

**硬性约束（Strong Constraints）**  
- 决策快照与 TradingDecision 产出**必须在同一数据库事务或等价原子流程内**；写入失败则禁止产出 TradingDecision。  
- 快照内容**必须**为本次决策实际使用的输入；写入后为不可变历史记录。  
- 写入失败时：不传 TradingDecision、触发强告警、写 log、拒绝决策；不得静默放行。  
- 支撑 2.0 的决策输入快照 schema 与查询方式按蓝本 C.1、D.1 实现，不得删减。

**逻辑真理源（Source of Truth）**  
- 决策输入历史以 decision_snapshot 表为准；是否允许产出 TradingDecision 以「快照是否成功写入」为准。

**交付物（Deliverables）**  
- DecisionSnapshotRepository（仅 insert + get_by_decision_id + list_by_strategy_time）。  
- StrategyExecutor 内同事务写入与失败策略实现。  
- 决策输入快照 schema 文档（C.1）与写入/查询约定。  
- 失败策略与告警说明文档。

**验收口径（Acceptance Criteria）**  
- [ ] 给定一条决策，DB 中有一条 decision_snapshot 且 decision_id 一致。  
- [ ] get_by_decision_id 返回完整四块（signal_state, position_state, risk_check_result, decision_result）。  
- [ ] list_by_strategy_time 返回该策略时间范围内快照。  
- [ ] 时点一致性：写入后修改持仓再查快照，快照内容未变。  
- [ ] 不可变：无 update(decision_id) 接口，尝试更新返回错误或不存在。  
- [ ] 写入失败：mock 写入失败时，验证无 trade 产生、有 ERROR 日志与告警、ExecutionEngine 未收到该 decision。

**绑定说明**  
本模块至少需要满足 D1、D6 中与其功能直接相关的可验证点，方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### C2. 全链路追溯（T1.2a-1）

**目标**  
- 提供按 signal_id / decision_id 的单链路查询及列表/回放接口；链路不完整时返回 PARTIAL/NOT_FOUND，必含 trace_status 与 missing_nodes，禁止静默忽略或返回空对象。

**开发范围（必须明确）**  
- **TraceQueryService** 实现蓝本 D.2 全部接口：  
  - 单链路：`get_trace_by_signal_id(signal_id)`、`get_trace_by_decision_id(decision_id)`，返回 TraceResult（含 trace_status、missing_nodes、已有节点 signal/decision/decision_snapshot/execution/trade）。  
  - 列表/回放：`list_decisions(strategy_id, start_ts, end_ts, limit, offset)`、`list_decisions_by_time(start_ts, end_ts, limit, offset)`、`get_recent_n(n, strategy_id?)`；1.2b 多笔回放在 C8。  
- **TraceResult 结构**：严格按蓝本 D.2 表格（trace_status 枚举 COMPLETE|PARTIAL|NOT_FOUND；PARTIAL 时 missing_nodes 必填且非空；NOT_FOUND 时缺失标识完整）。  
- **HTTP 约定**：查不到任何节点返回 404；查到部分或全部返回 200，body 为 TraceResult；**禁止**部分数据存在时返回 404 或空 body。  
- **链路不完整行为**：遵守蓝本 B.2（返回 partial 数据、missing_nodes 枚举、trace_status、禁止静默忽略、禁止空对象无说明）。  
- **HTTP 路由（写死）**：`GET /api/trace/signal/{signal_id}`、`GET /api/trace/decision/{decision_id}`。

**硬性约束（Strong Constraints）**  
- 链路不完整时**必须**返回已存在节点并显式标识 missing_nodes；**禁止**静默忽略缺失或返回空对象且无 trace_status/missing_nodes。  
- trace_status 取值**写死**为 COMPLETE | PARTIAL | NOT_FOUND；PARTIAL 时 missing_nodes 非空。  
- 与蓝本 B.2、D.2 完全一致，不得弱化。

**逻辑真理源（Source of Truth）**  
- 链路数据以 dedup_signal、decision、decision_snapshot、execution、trade 等表聚合为准；完整度以 trace_status 与 missing_nodes 为准。

**交付物（Deliverables）**  
- TraceQueryService 及 TraceResult/DecisionSummary 实现。  
- B.2 响应规范实现与契约说明。  
- 上述 HTTP 路由实现。

**验收口径（Acceptance Criteria）**  
- [ ] 完整链路：trace_status=COMPLETE，missing_nodes 为空，五节点均有。  
- [ ] 缺 execution：PARTIAL，missing_nodes 含 execution/trade，返回 signal/decision/snapshot。  
- [ ] 缺 decision_snapshot：PARTIAL，missing_nodes 含 decision_snapshot。  
- [ ] 缺 trade：PARTIAL，missing_nodes 含 trade。  
- [ ] 不存在的 signal_id：404 或 NOT_FOUND+无节点。  
- [ ] 任一部分存在时 HTTP 200 且 body 非空、含 trace_status。

**绑定说明**  
本模块至少需要满足 D1、D5 中与其功能直接相关的可验证点，方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### C3. 审计/操作/错误日志（T1.2a-2）

**目标**  
- 统一写入与查询审计、操作、错误日志；覆盖 C.3 必写路径，写入前脱敏，支持按时间/组件/级别分页查询。

**开发范围（必须明确）**  
- **LogRepository**：  
  - `append(session, component, level, message, event_type=None, payload=None)`；level 枚举 INFO, WARNING, ERROR, AUDIT。  
  - `query(session, start_ts, end_ts, component=None, level=None, page=1, page_size=100)` 返回分页列表。  
- **必写路径（写死）**：信号接收（signal_received）、决策生成（decision_created）、风控检查结果（risk_check_pass/risk_check_reject）、执行提交（execution_submit）、成交/失败（trade_filled/execution_failed）；上述任一路径发生**必须**有一条 level=AUDIT 的 log，含 event_type 与必要业务键（如 signal_id, decision_id）。决策快照写入失败**必须**写 ERROR 并触发强告警（与 C1 衔接）。  
- **脱敏（写死）**：message 与 payload **禁止**完整 API Key、完整 token、明文密码；使用截断或哈希（如 key_last4）；在 LogRepository 或写入前统一脱敏，并在交付包文档中列出规则。

**硬性约束（Strong Constraints）**  
- C.3 所列必写路径**必须**有对应 AUDIT 或 ERROR 日志；不得遗漏。  
- 脱敏规则**必须**在实现中落实；message/payload 中无完整 key/token。  
- 查询**必须**分页（limit/offset 或 page/page_size），单次上限约定（如 1000 条）。

**逻辑真理源（Source of Truth）**  
- 以数据库 log 表为准；审计与错误追溯以该表为准。

**交付物（Deliverables）**  
- LogRepository（append, query）实现。  
- 脱敏规则文档（列出禁止项与处理方式）。  
- 必写路径与 event_type 对照说明（C.3）。

**验收口径（Acceptance Criteria）**  
- [ ] 发 signal→决策→执行→成交后，query(level=AUDIT) 含至少 4 条对应 event_type。  
- [ ] query(start_ts, end_ts, component, level) 返回正确子集。  
- [ ] 错误路径写 level=ERROR 可查。  
- [ ] message/payload 无完整 key/token。

**绑定说明**  
本模块至少需要满足 D2 中与其功能直接相关的可验证点，方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### C4. 监控与告警（T1.2a-3）

**目标**  
- 提供系统指标、健康检查与告警规则评估；告警触发时写 log 并可选发邮件，支撑健康仪表板与运维。

**开发范围（必须明确）**  
- **SystemMonitor.get_metrics()**：至少返回 signals_received_count, orders_executed_count, error_count, error_rate 等。  
- **HealthChecker.check_all()**：至少返回 db_ok, exchange_ok, strategy_status；返回类型 HealthResult。  
- **AlertSystem.evaluate_rules()**：根据规则评估，返回 list[Alert]；触发时写 log 且可选发邮件。  
- 决策快照写入失败**必须**触发强告警（高优先级，接入 AlertSystem，写审计/错误日志）；告警去重与冷却（如 1 分钟内同类型只告警一次）在实现文档中写死。  
- 与蓝本 D.4 一致；数据来源禁止硬编码假数据。

**硬性约束（Strong Constraints）**  
- 健康仪表板与健康 API 的数据**必须**来自 SystemMonitor/HealthChecker/LogRepository，**禁止**硬编码假数据。  
- 决策快照写入失败**必须**触发强告警（与 C1 一致）。  
- 告警规则可配置；邮件依赖 SMTP 时配置与失败降级（如仅写 log）写死。

**逻辑真理源（Source of Truth）**  
- 指标以实际运行时数据为准；健康状态以 check_all 与 DB/交易所可达性为准。

**交付物（Deliverables）**  
- SystemMonitor、HealthChecker、AlertSystem 实现。  
- 告警规则配置示例与失败降级说明。

**验收口径（Acceptance Criteria）**  
- [ ] get_metrics() 返回含 signals_received_count 等。  
- [ ] check_all() 返回各组件状态。  
- [ ] 触发规则后存在 Alert 与 log/邮件（若配置）。

**绑定说明**  
本模块至少需要满足 D3 中与其功能直接相关的可验证点（健康数据来源），方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### C5. 健康仪表板（T1.2a-4）

**目标**  
- 提供健康汇总 HTTP 接口，供 Dashboard 与运维使用；数据来自 C4 与 LogRepository，禁止假数据。

**开发范围（必须明确）**  
- 实现 `GET /api/health/summary`：返回 JSON 含 overall_ok, metrics（如 signals_received_count 等）, recent_alerts[], recent_errors[]。  
- 数据来源**必须**为 SystemMonitor.get_metrics()、HealthChecker.check_all()、LogRepository（recent_errors 等），**禁止**硬编码假数据。

**硬性约束（Strong Constraints）**  
- 访问 URL 返回 200；返回数据与 get_metrics/check_all/LogRepository 一致。  
- 禁止假数据；与蓝本 D.5 一致。

**逻辑真理源（Source of Truth）**  
- 以 C4 与 LogRepository 实时查询为准。

**交付物（Deliverables）**  
- GET /api/health/summary 路由与实现。  
- 响应模型说明（字段含义）。

**验收口径（Acceptance Criteria）**  
- [ ] 访问 URL 返回 200。  
- [ ] 数据与 get_metrics/check_all/LogRepository 一致。

**绑定说明**  
本模块至少需要满足 D3 中与其功能直接相关的可验证点，方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### C6. 持仓一致性监控（T1.2a-5）

**目标**  
- 监控持仓与外部/本地一致性；中/严重不一致时通过 AlertSystem 触发告警。

**开发范围（必须明确）**  
- **PositionConsistencyMonitor.get_status(strategy_id=None)**：返回 list[ConsistencyStatus]；ConsistencyStatus 含 strategy_id, symbol, reconcile_status, last_reconcile_at。  
- 中等/严重不一致时调用 AlertSystem 触发告警；与蓝本 D.6 一致。  
- 数据来源：position_snapshot 与对账/reconcile 结果。

**硬性约束（Strong Constraints）**  
- get_status() 返回的 reconcile_status 等与真实一致性状态一致。  
- 模拟不一致时可触发告警；与 AlertSystem 集成。

**逻辑真理源（Source of Truth）**  
- 以 position_snapshot 与对账结果为准；告警以 AlertSystem 规则为准。

**交付物（Deliverables）**  
- PositionConsistencyMonitor 实现。  
- 与 AlertSystem 的告警集成说明。

**验收口径（Acceptance Criteria）**  
- [ ] get_status() 返回 reconcile_status、last_reconcile_at 等。  
- [ ] 模拟不一致可触发告警。

**绑定说明**  
本模块无单独 D 可验证点，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### C7. 性能日志（T1.2b-1）

**目标**  
- 采集关键路径性能指标（延迟、吞吐等）写入 perf_log，支持按时间/组件等维度查询。

**开发范围（必须明确）**  
- **PerfLogRepository**：`record(session, component, metric, value, tags=None)`、`query(session, start_ts, end_ts, component=None, page=1, page_size=100)` 返回 list[PerfLogEntry]。  
- 关键路径打点：信号处理、决策、执行等（与蓝本 E T1.2b-1 一致）。  
- 存储使用 A3 的 perf_log 表；与 log 表语义分离。

**硬性约束（Strong Constraints）**  
- 查询**必须**分页；禁止单次无上限全表扫描。  
- 与业务审计 log 分离；仅性能指标。

**逻辑真理源（Source of Truth）**  
- 以 perf_log 表为准。

**交付物（Deliverables）**  
- PerfLogRepository 实现。  
- 打点位置与 metric 命名说明。

**验收口径（Acceptance Criteria）**  
- [ ] 执行一条链路后 perf_log 有 latency 等记录。  
- [ ] query 返回符合时间/组件条件的记录。

**绑定说明**  
本模块至少需要满足 D4 中与其功能直接相关的可验证点，方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### C8. 多笔回放与审计查询界面（T1.2b-2）

**目标**  
- 提供多笔回放 API（list_traces）与审计日志查询界面（CLI 或 Web）；每条 TraceSummary 含 trace_status，PARTIAL 时含 missing_nodes；界面与 1.2a 入库数据一致。

**开发范围（必须明确）**  
- **TraceQueryService.list_traces(start_ts, end_ts, strategy_id=None, limit=100, offset=0)**：返回 list[TraceSummary]。  
- **TraceSummary 结构**（蓝本 D.9）：trace_status（必填）、missing_nodes（PARTIAL 时非空）、signal_id、decision_id、strategy_id、created_at、summary 等；**禁止**静默返回空或省略缺失说明。  
- **审计日志查询界面**：CLI 或 Web，筛选条件至少 start_ts, end_ts, component, level；调用 LogRepository.query；与 1.2a 入库数据一致。  
- 错误码：400 参数错误、404 未找到、500 服务错误；列表单次上限 100 条（或配置写死）。

**硬性约束（Strong Constraints）**  
- 每条 TraceSummary **必须**包含 trace_status；PARTIAL 时 **missing_nodes** 必填且非空；与单链路 B.2 行为一致。  
- 审计界面筛选结果与 log 表一致；**禁止**静默忽略缺失或返回无说明空结果。

**逻辑真理源（Source of Truth）**  
- 多笔回放以 TraceQueryService 聚合结果为准；审计以 LogRepository.query 为准。

**交付物（Deliverables）**  
- list_traces 实现与 TraceSummary 结构。  
- 审计查询界面（CLI 或 Web）及筛选参数说明。

**验收口径（Acceptance Criteria）**  
- [ ] list_traces 返回列表；任一条 PARTIAL 含 missing_nodes 非空及已有节点摘要。  
- [ ] 审计界面按时间/组件/级别筛选结果与 log 表一致。

**绑定说明**  
本模块至少需要满足 D4 中与其功能直接相关的可验证点，方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### C9. MVP 门禁验收（T1.2b-3）

**目标**  
- 完成压力测试、故障恢复、备份恢复的文档与演练，达到 MVP v1.0 生产就绪门禁。

**开发范围（必须明确）**  
- 压力测试：负载与通过标准在实现文档中写死；交付压力测试报告（含通过/不通过结论）。  
- 故障恢复：故障恢复测试记录。  
- 备份与恢复：备份恢复流程文档及至少一次演练成功记录。  
- 与蓝本 E T1.2b-3、F、H 交付物清单一致。

**硬性约束（Strong Constraints）**  
- 压力测试报告存在且结论明确；故障恢复与备份恢复有可追溯记录。  
- 不引入 Phase 2.x 能力；不弱化本包约定。

**逻辑真理源（Source of Truth）**  
- 以交付的报告与演练记录为准。

**交付物（Deliverables）**  
- 压力测试报告（含负载与通过标准、结论）。  
- 故障恢复测试记录。  
- 备份与恢复流程文档及演练记录。

**验收口径（Acceptance Criteria）**  
- [ ] 压力测试报告存在且结论通过。  
- [ ] 故障恢复测试有记录。  
- [ ] 备份与恢复文档存在且至少一次演练成功。

**绑定说明**  
本模块为门禁验收类，无 D 可验证点绑定，验收通过即完成 Phase1.2 门禁。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

### D. 测试与验收（可验证点）

以下仅描述**可验证点**，不要求编写测试代码；用于端到端与回归验收判定。

#### D1. E2E-1 完整链路可验证点

**目标**  
- 验证端到端：Webhook 信号 → decision → 同事务 decision_snapshot → 执行并成交 → 按 signal_id/decision_id 查询得完整链路（含 decision_snapshot）；trace_status=COMPLETE。

**可验证点**  
- [ ] 发送一条 Webhook 信号后，DB 有 1 条 trade、1 条 decision_snapshot，且 decision_id 一致。  
- [ ] get_trace_by_signal_id / get_trace_by_decision_id 返回 TraceResult 含五节点；trace_status=COMPLETE，missing_nodes 为空或不存在。

**绑定说明**  
本模块为可验证点定义，执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### D2. E2E-2 审计可验证点

**目标**  
- 验证风控拒绝或执行失败时，审计日志可查且可按时间/组件/级别筛选。

**可验证点**  
- [ ] 触发一次风控拒绝或执行失败后，LogRepository.query(level=AUDIT 或 ERROR) 含该事件。  
- [ ] query 按 start_ts, end_ts, component, level 可筛选出对应记录。

**绑定说明**  
本模块为可验证点定义，执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### D3. E2E-3 Dashboard 可验证点

**目标**  
- 验证最小 Dashboard 页面展示与 API 一致，无前端自算指标。

**可验证点**  
- [ ] 打开最小 Dashboard 页面，展示最近决策/执行/成交、汇总、健康指标。  
- [ ] 页面数据与 GET /api/dashboard/* 及 GET /api/health/summary 返回一致。  
- [ ] 无前端自算 pnl/笔数。

**绑定说明**  
本模块为可验证点定义，执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### D4. E2E-4 多笔回放可验证点

**目标**  
- 验证多笔回放 API 与审计查询界面与 1.2a 数据一致。

**可验证点**  
- [ ] list_traces 指定时间范围返回 list[TraceSummary]。  
- [ ] 审计查询界面筛选结果与 log 表一致。

**绑定说明**  
本模块为可验证点定义，执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### D5. E2E-5 链路缺失可验证点

**目标**  
- 验证有 decision 无 execution、有 decision 无 decision_snapshot、有 execution 无 trade、signal_id 不存在等场景下，响应符合 B.2（200、trace_status=PARTIAL 或 NOT_FOUND、missing_nodes 正确、body 含已存在节点）。

**可验证点**  
- [ ] 构造「有 decision 无 execution」：get_trace 返回 HTTP 200，trace_status=PARTIAL，missing_nodes 含 execution/trade，body 含 signal/decision/snapshot。  
- [ ] 构造「有 decision 无 decision_snapshot」：trace_status=PARTIAL，missing_nodes 含 decision_snapshot。  
- [ ] 构造「有 execution 无 trade」：trace_status=PARTIAL，missing_nodes 含 trade。  
- [ ] 不存在的 signal_id：404 或 200+ trace_status=NOT_FOUND。  
- [ ] **禁止**部分数据存在时返回 404 或 body 为空对象/null 且无 trace_status、missing_nodes。

**绑定说明**  
本模块为可验证点定义，执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

#### D6. E2E-6 决策快照写入失败可验证点

**目标**  
- 验证决策快照写入失败时，不产出 TradingDecision、触发强告警、写 ERROR 日志、拒绝本次决策；禁止静默放行。

**可验证点**  
- [ ] 模拟 decision_snapshot 写入失败（如 DB 约束失败或 mock save 抛异常）：**未**向 ExecutionEngine 传递 TradingDecision（无对应 trade/order）。  
- [ ] **已**触发强告警（AlertSystem 或等价有记录）。  
- [ ] **已**写入 ERROR 或 AUDIT 日志（含 decision_id/strategy_id/失败原因）。  
- [ ] 该 signal 在本轮视为决策失败（可查 log 或拒绝状态）。  
- [ ] **禁止**静默放行或仍产生 trade。

**绑定说明**  
本模块为可验证点定义，执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 D、C9），证据包可为文档、报告或演练记录；
- 禁止用"整体 E2E 已通过"替代本模块证据。

---

## 二.2 开发与验收记录（Phase1.2 整体性验收）

以下为各模块证据包路径及整体验收结论，用于确保所有需求已开发完毕且满足验收标准。

| 模块 | 证据包路径 | 验收状态 |
|------|------------|----------|
| A1 | docs/phase1.2/Phase1.2_A1_模块证据包.md | 已验收 |
| A2 | docs/phase1.2/Phase1.2_A2_模块证据包.md | 已验收 |
| A3 | docs/phase1.2/Phase1.2_A3_模块证据包.md | 已验收 |
| B1 | docs/Phase1.2_B1_模块证据包.md | 已验收 |
| B2 | docs/Phase1.2_B2_模块证据包.md | 已验收 |
| C1 | docs/phase1.2/Phase1.2_C1_模块证据包.md | 已验收 |
| C2 | docs/phase1.2/Phase1.2_C2_模块证据包.md | 已验收 |
| C3 | docs/phase1.2/Phase1.2_C3_模块证据包.md | 已验收 |
| C4 | docs/phase1.2/Phase1.2_C4_模块证据包.md | 已验收 |
| C5 | docs/phase1.2/Phase1.2_C5_模块证据包.md | 已验收 |
| C6 | docs/phase1.2/Phase1.2_C6_模块证据包.md | 已验收 |
| C7 | docs/Phase1.2_C7_模块证据包.md | 已验收 |
| C8 | docs/Phase1.2_C8_模块证据包.md | 已验收 |
| C9 | docs/Phase1.2_C9_模块证据包.md | 已验收（压力/故障/备份演练） |
| D1 | docs/Phase1.2_D1_模块证据包.md | 已验收 |
| D2 | docs/Phase1.2_D2_模块证据包.md | 已验收 |
| D3 | docs/Phase1.2_D3_模块证据包.md | 已验收 |
| D4 | docs/Phase1.2_D4_模块证据包.md | 已验收 |
| D5 | docs/Phase1.2_D5_模块证据包.md | 已验收 |
| D6 | docs/Phase1.2_D6_模块证据包.md | 已验收 |

- **E2E 测试报告**：见 `docs/Phase1.2_整体验收报告.md` 第二节；完整集成测试原始输出见 `docs/runlogs/phase12_full_integration_pytest.txt`（78 项通过）。
- **压力测试 / 故障恢复 / 备份恢复**：见 `docs/Phase1.2_C9_模块证据包.md` 及 `docs/runlogs/c9_stress_*.txt`、`c9_failure_drill_*.txt`、`c9_backup_restore_run.txt`。
- **整体验收结论**：见 `docs/Phase1.2_整体验收报告.md`；Phase1.2 符合系统标准与开发蓝本要求，E2E-1～E2E-6 及决策快照写入失败场景通过，无漏开发、无未修复 Bug，日志与告警符合脱敏与合规要求。

---

## 三、关键约束遵守检查清单

### ✅ 开发项唯一性
- [ ] Phase1.2 开发项仅包含 A1、A2、A3、B1、B2、C1～C9、D1～D6，无合并、拆分、新增、遗漏或编号调整。
- [ ] 执行顺序与本文档「一、推荐执行顺序」一致。

### ✅ 决策输入快照（0.4）
- [ ] decision_snapshot 与 TradingDecision 同事务或等价原子流程；写入失败不产出 TradingDecision、触发强告警、写日志、拒绝决策。
- [ ] 快照内容为本次决策实际输入；写入后不可变；无按 decision_id 的 UPDATE/DELETE。
- [ ] DecisionSnapshotRepository 仅暴露 insert + get_by_decision_id + list_by_strategy_time。

### ✅ 全链路追溯（B.2）
- [ ] 链路不完整时返回 PARTIAL/NOT_FOUND，含 trace_status、missing_nodes；禁止静默忽略或空对象无说明。
- [ ] 查不到任何节点返回 404；查到部分或全部返回 200，body 含 TraceResult。
- [ ] 单链路与多笔回放（TraceSummary）均遵守 B.2。

### ✅ 审计与日志
- [ ] C.3 必写路径（信号/决策/风控/执行/成交/失败）均有 AUDIT 或 ERROR 日志。
- [ ] message/payload 脱敏，无完整 API Key/token/明文密码。
- [ ] 分页查询，单次上限约定；无全表无上限扫描。

### ✅ 监控、健康与 Dashboard
- [ ] GET /api/health/summary 数据来自 SystemMonitor/HealthChecker/LogRepository，禁止假数据。
- [ ] 最小 Dashboard 仅消费 /api/dashboard/* 与 /api/health/summary；汇总口径 D.7 写死；禁止前端自算指标。

### ✅ Phase 1.2 终止条件
- [ ] 允许进入 Phase 2.0：A.2（1.2a、最小 Dashboard、1.2b）全部达成，且 E2E-1～E2E-6 及决策快照写入失败场景通过。
- [ ] 禁止启动 Phase 2.0：任一条未达成（含决策快照未同事务、写入失败仍产出决策、Trace 空对象或缺 missing_nodes、审计必写路径未覆盖、Dashboard 自算指标等），须先闭环 Phase 1.2。

### ✅ C9 门禁与技术债登记
- [ ] C9 门禁验收通过后，**已登记技术债**以 TECH_DEBT.md 为准：TD-C9-01（压测数据库 SQLite）、TD-C9-02（execution worker 故障演练为手工）、TD-C9-03（备份校验非 schema-aware）。Phase2.0 C5 附中已列对应硬性 AC（AC-C9-STRESS-DB-01、AC-C9-FAILURE-DRILL-01、AC-C9-BACKUP-VERIFY-01），封版时三处一致。

### ✅ D2 已通过与技术债 Phase2.x 清偿
- [ ] D2（Failure & Degradation E2E）已通过；**以下技术债必须在 Phase2.x 清偿**，未完成不得封版 Phase2.x：**D2-TRACE-404**（执行失败 decision 必须可 trace，明确失败节点与原因）、**D2-HEALTH-WEAK-OBSERVABILITY**（health 异常须有明确字段与判定标准）。TECH_DEBT.md、Phase2.0 交付包 C5 附及封版 Gate（GATE-TD-04、GATE-TD-05）三处口径一致。

---

## 封版声明

> 本 Phase1.2 模块化开发交付包一经确认，即作为 Phase1.2 的**唯一开发真理源**。  
> 在后续开发、测试、验收过程中：  
> - 不允许新增开发项  
> - 不允许删除开发项  
> - 不允许调整模块顺序  
> - 不允许修改模块语义  
> - 不允许删减或弱化蓝本中的任何「必须/禁止/写死」规则  
>  
> 如需变更，必须基于 Phase1.2 开发蓝本（系统宪法）进行修订并同步本交付包。

---

**文档结束**
