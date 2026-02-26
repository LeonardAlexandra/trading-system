# Phase 2.0 模块化开发交付包

**版本**: v1.0.0  
**创建日期**: 2026-02-07  
**最后修订**: 2026-02-07  
**基于**: Phase2.0 开发蓝本（系统宪法，不可改写语义）

---

## 一、推荐执行顺序（强制）

以下顺序为 Cursor/开发者的**推荐执行顺序**，不可调整。开发项必须按此顺序实施，以降低依赖冲突与返工风险。

| 步骤 | 开发项 | 说明 |
|------|--------|------|
| 1 | A1 / A2 | 数据库迁移（metrics_snapshot、evaluation_report，可并行或按 A1→A2 顺序） |
| 2 | C1 | MetricsRepository（仅写 Phase 2.0 表 metrics_snapshot，按策略/版本/时间段查询） |
| 3 | C2 | MetricsCalculator（只读 Phase 1.2 的 trade 等，按 B.2 口径算数，不产出结论） |
| 4 | C3 | Evaluator（只读 Phase 1.2 与 MetricsCalculator 输出，产出 0.2 报告并仅写 evaluation_report） |
| 5 | C4 | 策略版本与评估结果可查（StrategyVersion 只读 + 按 strategy_version_id / evaluated_at / param_version_id 查询报告） |
| 6 | C5 | 历史数据假设与硬性待办（文档，不实现导入） |
| 7 | D6-D8 | 技术债专项修复（SECURITY/TRACE/HEALTH 专项） |
| 8 | D1～D5 | 端到端与回归可验证点（E2E-2.0 主流程、只读、可重复、baseline、回归清单） |

### 模块级执行规则（强制）

1. Phase2.0 的开发必须严格按模块逐一推进。
2. 任一时刻，只允许存在 **一个「活跃开发模块」**。
3. 当正在开发某一模块（如 C2）时：
   - 禁止修改、实现、重构任何非本模块定义范围内的代码；
   - 禁止提前实现后续模块（如 C3～C5）的任何逻辑；
   - 禁止为「后续模块方便」而预埋代码、接口或占位实现。
4. 当前模块在 **未通过验收** 前，不得进入下一模块。
5. 若某模块验收失败，只允许在该模块范围内返工，不得牵连其他模块。

---

## 二、开发项与交付

### A. 数据库迁移（Migrations）

#### A1. metrics_snapshot 表（指标快照，Phase 2.0 自有）

**目标**  
- 为 Phase 2.0 指标计算产出提供持久化存储；表为 Phase 2.0 自有，**禁止**对 Phase 1.2 任何表执行写操作。

**开发范围（必须明确）**  
- 新增表 `metrics_snapshot`，字段与约束严格按蓝本 C.1：  
  - 必填字段：id（BIGINT 或 UUID，PK）、strategy_id（string, NOT NULL）、strategy_version_id（string, NOT NULL）、param_version_id（string, NULLABLE）、period_start（timestamptz, NOT NULL）、period_end（timestamptz, NOT NULL）、trade_count（integer, NOT NULL）、win_rate（decimal, NULLABLE 或 0）、realized_pnl（decimal, NOT NULL）、max_drawdown（decimal, NULLABLE 或 0）、avg_holding_time_sec（decimal, NULLABLE）、created_at（timestamptz, NOT NULL）。  
  - **禁止**在表中出现未在 B.2 或 C.1 列出的指标字段。  
  - 索引：`(strategy_id, period_start, period_end)`；`(strategy_id, strategy_version_id)`；`(strategy_version_id, param_version_id, period_start)`。  
- 迁移脚本：仅建表与索引，不修改 Phase 1.2 任何表。

**硬性约束（Strong Constraints）**  
- 本表为 Phase 2.0 自有表；**禁止**对 Phase 1.2 表（decision_snapshot、trade、execution、log 等）执行任何 UPDATE/INSERT/DELETE。  
- 表中仅存在 B.2/C.1 文档化字段，**禁止**未文档化列。  
- 迁移必须支持 alembic upgrade/downgrade，不破坏已有表。

**输入 / 输出**  
- 输入：无（迁移无业务输入）。  
- 输出：表 `metrics_snapshot` 及索引；为 C1 MetricsRepository 提供存储。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行（upgrade/downgrade 无报错，幂等）。  
- [ ] 表中存在上述三组索引及 C.1 全部字段。  
- [ ] 文档或注释明确本表为 Phase 2.0 自有、仅存 B.2 指标，无未文档化列。

**绑定说明**  
本模块为 C1、C2、C3 提供指标存储基础，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 C5、D），证据包可为文档、报告或演练记录；
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### A2. evaluation_report 表（评估报告，满足 0.2，Phase 2.0 自有）

**目标**  
- 为 Evaluator 产出的评估报告提供持久化存储；满足 0.2 Evaluator Contract，表为 Phase 2.0 自有，**禁止**对 Phase 1.2 任何表执行写操作。

**开发范围（必须明确）**  
- 新增表 `evaluation_report`，字段与约束严格按蓝本 C.2：  
  - 必填字段：id（BIGINT 或 UUID，PK）、strategy_id（string, NOT NULL）、strategy_version_id（string, NOT NULL）、param_version_id（string, NULLABLE）、evaluated_at（timestamptz, NOT NULL）、period_start（timestamptz, NOT NULL）、period_end（timestamptz, NOT NULL）、objective_definition（JSONB, NOT NULL）、constraint_definition（JSONB, NOT NULL）、baseline_version_id（string, NULLABLE，**仅存 strategy_version_id**）、conclusion（string, NOT NULL）、comparison_summary（JSONB 或 TEXT, NULLABLE）、metrics_snapshot_id（BIGINT 或 UUID, NULLABLE, FK→metrics_snapshot.id）、created_at（timestamptz, NOT NULL）。  
  - **禁止**：baseline_version_id 指向 param_version；conclusion 或 comparison_summary 中出现「建议参数」「可写回」「供优化」等语义。  
  - 索引：`(strategy_id, evaluated_at)`、`(strategy_version_id, evaluated_at)`、`(param_version_id, evaluated_at)`。  
- 迁移脚本：仅建表与索引，不修改 Phase 1.2 任何表。

**硬性约束（Strong Constraints）**  
- 本表为 Phase 2.0 自有表；**禁止**对 Phase 1.2 表执行任何 UPDATE/INSERT/DELETE。  
- baseline_version_id **仅**存 strategy_version_id，**禁止**存 param_version_id。  
- objective_definition / constraint_definition 须符合 B.1 最小结构化字段集，**禁止**未文档化顶层键。  
- 迁移必须支持 alembic upgrade/downgrade，不破坏已有表。

**输入 / 输出**  
- 输入：无（迁移无业务输入）。  
- 输出：表 `evaluation_report` 及索引；为 C3 Evaluator、C4 查询提供存储。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行且可回滚。  
- [ ] 表中存在上述索引及 C.2 全部字段；metrics_snapshot_id 可 FK 至 metrics_snapshot.id。  
- [ ] 文档明确 baseline_version_id 仅存 strategy_version_id、禁止「建议参数/写回/优化」语义。

**绑定说明**  
本模块为 C3、C4 及 D1～D4 提供表结构基础，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 C5、D），证据包可为文档、报告或演练记录；
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

### B. API 层

（Phase 2.0 无独立 Dashboard 类 API 层；评估与策略版本查询接口归入 C4。）

---

### C. 核心逻辑

#### C1. MetricsRepository（T2.0-1）

**目标**  
- 提供指标快照的写入与按策略/版本/时间段的只读查询；**仅**读写 Phase 2.0 自有表 metrics_snapshot，**禁止**对 Phase 1.2 任何表执行写操作。

**开发范围（必须明确）**  
- **MetricsRepository**：  
  - `write(session, snapshot: MetricsSnapshot) -> void`：仅写入 metrics_snapshot 表；**禁止**读写 Phase 1.2 表。  
  - `get_by_strategy_period(session, strategy_id, period_start, period_end) -> list[MetricsSnapshot]`：仅读 metrics_snapshot。  
  - `get_by_strategy_time_range(session, strategy_id, start_ts, end_ts) -> list[MetricsSnapshot]`：仅读 metrics_snapshot。  
- MetricsSnapshot 与 C.1 schema 一致：含 strategy_id、strategy_version_id、param_version_id、period_start、period_end、trade_count、win_rate、realized_pnl、max_drawdown、avg_holding_time_sec、created_at；**禁止**未文档化字段。

**硬性约束（Strong Constraints）**  
- **只读边界**：本模块**禁止**对 Phase 1.2 表（decision_snapshot、trade、execution、log 等）执行任何 UPDATE/INSERT/DELETE；所有写操作**仅**发生在 metrics_snapshot 表。  
- 接口契约：`This API MUST NOT mutate any Phase 1.2 data.` 实现须通过依赖与权限约束保证仅访问 Phase 2.0 表。  
- 表中仅存在 B.2/C.1 文档化字段，无未文档化列。

**输入 / 输出**  
- 输入：调用方传入 MetricsSnapshot（含 B.2 字段）；查询入参 strategy_id、period 或 time_range。  
- 输出：metrics_snapshot 表持久化；查询返回 list[MetricsSnapshot]。

**验收口径（Acceptance Criteria）**  
- [ ] 指标可按 strategy_id / strategy_version_id / period 写入并持久化。  
- [ ] 按策略、时间段、版本查询结果与写入一致。  
- [ ] **只读边界**：该模块未对 Phase 1.2 表执行任何写操作（可通过审计或测试验证）。  
- [ ] 表中仅存在 B.2/C.1 文档化字段，无未文档化列。

**绑定说明**  
本模块为 C2、C3 及 D1 提供指标存储与查询基础，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 C5、D），证据包可为文档、报告或演练记录；
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### C2. MetricsCalculator（T2.0-2）

**目标**  
- 按 B.2 写死的口径从 Phase 1.2 **只读**数据计算指标；**不**知道 baseline、不产出结论、不写 evaluation_report；**禁止**对 Phase 1.2 任何表执行写操作。

**开发范围（必须明确）**  
- **MetricsCalculator.compute(strategy_id, strategy_version_id, param_version_id?, period_start, period_end) -> MetricsResult**：  
  - 数据来源：**仅只读** Phase 1.2 的 trade 表（及 B.2 约定的 execution/decision_snapshot 辅助）；盈亏/胜率/回撤/笔数/持仓时间**以 trade 为准**；风控拒绝、下单失败的 decision **不计入** B.2 核心指标。  
  - 输出：MetricsResult 含 trade_count、win_rate、realized_pnl、max_drawdown、avg_holding_time_sec（与 B.2/C.1 一致）；**不**包含 conclusion、comparison_summary、baseline 或「建议」。  
  - 可选：compute 后由调用方（Evaluator 或独立 job）写入 metrics_snapshot；MetricsCalculator 本身可不写库。  
- **B.2 口径（写死）**：trade_count = 时间范围内 COUNT(trade_id)，无 trade 时为 0；win_rate = 盈利笔数/总笔数，无 trade 时按实现约定 0 或 NULL；realized_pnl = SUM(realized_pnl)，无 trade 时为 0；max_drawdown = 基于逐笔成交后累计权益曲线，无 trade 或仅一笔时按文档约定；avg_holding_time_sec = AVG(close_time - open_time) 秒，无 trade 或缺少时间字段时为 NULL。

**硬性约束（Strong Constraints）**  
- **只读边界**：compute 执行前后 Phase 1.2 表**禁止**任何 INSERT/UPDATE/DELETE；**This API MUST NOT mutate any Phase 1.2 data.**  
- 核心指标（trade_count、win_rate、realized_pnl、max_drawdown、avg_holding_time_sec）**仅基于 trade**；风控拒绝/未成交 **不计入**，**不**把拒绝/失败 decision 算作「亏损一笔」。  
- MetricsCalculator **禁止**输出 conclusion、comparison_summary、baseline 或「建议」；**禁止**同名指标不同口径、禁止未文档化指标出现在输出。

**输入 / 输出**  
- 输入：Phase 1.2 只读接口（trade 表及 B.2 约定的 execution/decision_snapshot）；入参 strategy_id、strategy_version_id、param_version_id（可选）、period_start、period_end。  
- 输出：MetricsResult（B.2 五指标）；不写 Phase 1.2；可选由调用方写 metrics_snapshot。

**验收口径（Acceptance Criteria）**  
- [ ] 给定策略+版本+时间范围可返回 B.2 五指标。  
- [ ] **口径**：用固定 trade 集抽检 — trade_count=COUNT、realized_pnl=SUM、win_rate=盈利笔数/总笔数、max_drawdown 来自权益曲线、avg_holding_time_sec=AVG(close-open)。  
- [ ] **口径**：构造「仅风控拒绝无 trade」的周期，上述核心指标为 0 或 NULL（与 B.2 约定一致）。  
- [ ] **只读边界**：compute 执行前后 Phase 1.2 表无任何 INSERT/UPDATE/DELETE。  
- [ ] MetricsCalculator 未输出 conclusion、comparison_summary、baseline 或「建议」。

**绑定说明**  
本模块为 C3 及 D1、D2 提供指标计算能力，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 C5、D），证据包可为文档、报告或演练记录；
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### C3. Evaluator（T2.0-3）

**目标**  
- 读取 Phase 1.2 数据与 MetricsCalculator 输出（或 metrics_snapshot）；做**版本比较**与**结论生成**；**仅写入** evaluation_report；**不**自行从 trade 计算指标；**禁止**对 Phase 1.2 任何表执行写操作、**禁止**输出「建议参数」/写回/发布/回滚语义。

**开发范围（必须明确）**  
- **Evaluator.evaluate(strategy_id, strategy_version_id, param_version_id?, period_start, period_end, config?) -> EvaluationReport**：  
  - config：objective_definition?、constraint_definition?、baseline_version_id?（**必须**为 strategy_version_id 或 null）。  
  - 内部：调用 MetricsCalculator.compute 或读取 metrics_snapshot；**禁止**直接从 trade 表算指标。  
  - 根据 objective/constraint 与 baseline 生成 conclusion、comparison_summary。  
  - 侧效应：**仅**写入 evaluation_report 表；**禁止**写 Phase 1.2 表。  
- **EvaluationReport** 必含：objective_definition、constraint_definition、baseline_version_id、conclusion、comparison_summary，及关联的 metrics 摘要或 metrics_snapshot_id。  
- **B.1 结构**：objective_definition 含 primary、primary_weight、secondary、secondary_weights；constraint_definition 含 max_drawdown_pct、min_trade_count、max_risk_exposure、custom；**禁止**未文档化顶层键。  
- **禁止**：修改任何策略参数；输出「建议参数」；调用任何写回接口；触发发布、回滚或门禁；baseline_version_id 指向 param_version。

**硬性约束（Strong Constraints）**  
- **只读边界**：evaluate 执行前后 Phase 1.2 表**禁止**任何 INSERT/UPDATE/DELETE；Evaluator **禁止**调用任何写回/发布/回滚接口。  
- baseline_version_id **仅**为 strategy_version_id 或 null；**禁止**存 param_version_id。  
- 结论与 comparison_summary 中**禁止**出现「建议参数」「可写回」「供优化」等措辞。  
- 每次输出必须包含且持久化：目标函数定义、约束条件、基线版本、结论与对比摘要（0.2 Evaluator Contract）。

**输入 / 输出**  
- 输入：Phase 1.2 只读数据；MetricsCalculator.compute 或 metrics_snapshot；入参 strategy_id、strategy_version_id、param_version_id?、period_*、config（objective、constraint、baseline_version_id?）。  
- 输出：evaluation_report 表一条记录；内存 EvaluationReport（含 0.2 五项）。

**验收口径（Acceptance Criteria）**  
- [ ] 产出报告必含 objective_definition、constraint_definition、baseline_version_id、conclusion、comparison_summary，且已持久化。  
- [ ] **版本**：report.strategy_version_id 存在；baseline_version_id 为 null 或为某 strategy_version_id（**非** param_version_id）。  
- [ ] **结构**：objective 含 primary、primary_weight、secondary、secondary_weights；constraint 含 max_drawdown_pct、min_trade_count、max_risk_exposure、custom；无未文档化顶层键。  
- [ ] **只读边界**：evaluate 执行前后 Phase 1.2 表无任何写操作；Evaluator 未调用任何写回/发布/回滚接口。  
- [ ] 结论与 comparison_summary 中无「建议参数」「可写回」「供优化」等措辞。

**绑定说明**  
本模块为 C4 及 D1、D3、D4 提供评估报告产出能力，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 C5、D），证据包可为文档、报告或演练记录；
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### C4. 策略版本与评估结果可查（T2.0-4）

**目标**  
- 提供策略版本只读访问与评估结果按 strategy_version_id / evaluated_at / param_version_id 的查询；**禁止**对 Phase 1.2 表执行写操作；baseline_version_id 仅引用 strategy_version。

**开发范围（必须明确）**  
- **StrategyVersionRepository**（或等价只读接口）：  
  - `get_by_id(session, version_id) -> StrategyVersion`；`list_by_strategy(session, strategy_id) -> list[StrategyVersion]`。  
  - Phase 2.0 **仅读取**策略版本信息；若该表属 1.2 或外部，2.0 仅通过只读接口访问；**禁止**写 Phase 1.2 表。  
- **EvaluationReportRepository**：  
  - `get_by_strategy_version(session, strategy_version_id) -> list[EvaluationReport]`；  
  - `get_by_evaluated_at(session, strategy_id, from_ts, to_ts) -> list[EvaluationReport]`；  
  - `get_by_param_version(session, param_version_id) -> list[EvaluationReport]`。  
  - 仅读 evaluation_report；**禁止**写 Phase 1.2 表。  
- 可选：暴露 HTTP API（如 GET /api/evaluation/report?strategy_version_id=&evaluated_at_from=&evaluated_at_to=&param_version_id=），与蓝本 D.3/D.4 一致。

**硬性约束（Strong Constraints）**  
- **只读边界**：所有查询接口**禁止**对 Phase 1.2 表执行任何 INSERT/UPDATE/DELETE；**This API MUST NOT mutate any Phase 1.2 data.**  
- **版本模型**：evaluation_report.baseline_version_id 仅引用 strategy_version 表 id，**禁止**引用 param_version。  
- 本 Phase **不提供**：参数写回、发布、回滚、Optimizer、学习、写回 API。

**输入 / 输出**  
- 输入：strategy_version 表或只读接口；evaluation_report 表；查询入参 strategy_version_id、evaluated_at 范围、param_version_id。  
- 输出：按 strategy_version_id / evaluated_at / param_version_id 查询到的 list[EvaluationReport]；返回数据含 0.2 语义字段。

**验收口径（Acceptance Criteria）**  
- [ ] 策略配置可按 version_id 查询。  
- [ ] 评估结果可按 strategy_version_id、evaluated_at 范围、param_version_id 查询。  
- [ ] 返回数据含 0.2 语义字段（objective_definition、constraint_definition、baseline_version_id、conclusion、comparison_summary）。  
- [ ] **版本模型**：evaluation_report.baseline_version_id 仅引用 strategy_version 表 id，不引用 param_version。  
- [ ] **只读边界**：查询接口未对 Phase 1.2 表执行写操作。

**绑定说明**  
本模块为 D1～D4 提供查询能力，验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 C5、D），证据包可为文档、报告或演练记录；
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### C5. 历史数据假设与硬性待办（T2.0-5）

**目标**  
- 交付「历史数据假设」与「硬性待办」文档，明确责任方、TradingView 可行方式、与 Webhook 一致性、触发条件；**本 Phase 不实现**历史数据导入代码。

**开发范围（必须明确）**  
- 在交付包或独立附录中提供：  
  - **历史数据假设**：责任方（谁提供历史导出、谁落地导入）；TradingView 侧可行方式（CSV/手动/API 等）；与实盘 Webhook 格式的一致性要求。  
  - **硬性待办**：2.1 结束前必须约定历史数据格式、至少一条导入路径（如 CSV/API）及责任方。  
  - **触发条件**：当实盘评估闭环跑通且需与历史回测对比时，启动历史管道；若 2.0 启动时责任方未定，则写明「2.1 结束前由产品/技术共同确认来源与格式」。  
- **Phase 2.0 边界**：本 Phase **不实现**历史数据导入；仅交付假设与待办文档。

**硬性约束（Strong Constraints）**  
- **禁止**在 Phase 2.0 实现历史数据导入代码；仅允许文档与约定。  
- 不得引入 Phase 2.1 的写回、Optimizer、学习或发布/回滚能力。

**输入 / 输出**  
- 输入：无（文档任务）。  
- 输出：本文档或附录中的「历史数据假设」与「硬性待办」章节；责任方、触发条件、2.0 边界说明。

**验收口径（Acceptance Criteria）**  
- [ ] 交付包中存在历史数据假设章节。  
- [ ] 硬性待办与触发条件、责任方已写明。  
- [ ] 未在 Phase 2.0 实现历史数据导入代码。

**绑定说明**  
本模块为文档类交付，无下游代码依赖，验收通过即满足 T2.0-5。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 若模块为文档/验收类（如 C5、D），证据包可为文档、报告或演练记录；
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### C5 附：运行模型与告警一致性（硬性待办，Phase2.1/2.x 实现）

**背景**  
本小节为 C5 的硬性待办附录，不构成 Phase2.0 新增开发项与编号。  
Phase1.2 C4 的告警系统存在两条运行时技术债，Phase2.0 不实现代码，但必须在本阶段明确前置决策与后续落地计划，避免遗忘：  
1) 告警冷却去重目前为进程内状态（单实例有效；重启丢失；多实例会重复告警）；  
2) 告警评估为拉模式（evaluate_rules 需外部触发，系统本身不调度）。

**1) 运行模型前置决策（必须在 Phase2.0 封版前做出选择）**

- 是否多实例运行：单实例 / 多实例 / 未来可能多实例  
- 告警是否要求「全局唯一」：同 rule_id 在冷却窗口内是否只触发一次（跨实例）  
- 监控/告警由谁触发：外部 cron/k8s job 拉取，还是系统内部 scheduler/worker 自跑  
- 监控频率建议值（例如 30s/60s），标注为「可调整参数」

**2) 目标行为（验收口径，可测试的句子）**

- 多实例下：同一 rule_id 在 60s 冷却窗口内只触发一次（全局去重）  
- 进程重启后：冷却状态不丢失（若选择持久化方案）  
- 评估调度：evaluate_rules 能按固定周期自动触发（若选择内部 scheduler），或由外部 cron 驱动且可观测（若选择外部触发）

**3) 预选技术方案（不实现，只列选项并说明适用条件）**

- **冷却去重持久化/分布式**  
  - 选项 A：Redis（推荐多实例场景）  
  - 选项 B：DB 表（低频告警可行）  
  - 选项 C：现有 log 表不推荐做状态源（log 为审计流水，不适合做冷却状态源，易歧义且难以保证原子性）  
- **调度触发**  
  - 选项 A：外部 cron/k8s job（轻量、无常驻调度进程）  
  - 选项 B：内部 scheduler（常驻进程/worker 内周期调用）  
  - 选项 C：混合方式（按需选用）

**4) 落地阶段归属（明确不在 Phase2.0 实现）**

- **本 Phase2.0**：仅记录上述决策与验收口径，不写代码、不改运行时。  
- **Phase2.1 或 Phase2.x**：实现「全局冷却去重 + 调度触发」，并补充对应证据包与集成测试。

---

#### C5 附：Perf Logging Isolation（硬性待办，Phase2.x 实现）

本小节为 C5 的硬性待办附录，不构成 Phase2.0 新增开发项与编号。

- **AC-PERF-ISOLATION-01**：  
  perf 记录写入失败时，不得导致 webhook/执行链路失败（主链路可继续）；失败必须被审计记录（log/alert），且可在追溯/健康页中定位到失败事实。

- **AC-PERF-ISOLATION-02**：  
  多实例运行时 perf 采集仍可用且不会重复/丢失关键记录；采用 outbox/queue/worker 任一隔离方案；必须提供 E2E 证据包（包含：故障注入→主链路成功→perf 异步落库或重试成功的证据）。

---

#### C5 附：Audit 回放与审计页面（技术债验收口径，Phase2.x 实现）

本小节为 C5 的硬性待办附录，不构成 Phase2.0 新增开发项与编号。

**针对 TD-C8-01（N+1）**

- **AC-AUDIT-LISTTRACES-PERF-01**：  
  list_traces 不得出现 N+1 查询模式；在 limit=100、时间窗>=24h 的回放场景中，后端对 trace 数据的获取必须为批量化（例如联表/批量查询/物化视图），并提供 SQL/日志或测试证据证明「查询次数不随 items 线性增长」。

- **AC-AUDIT-LISTTRACES-PERF-02**：  
  提供 E2E 证据包：构造 100 条 decision 回放，证明 list_traces 的数据库查询次数为常数级（<=K，K 在证据包中明确），并给出耗时与结果正确性对照。

**针对 TD-C8-02（XSS）**

- **AC-AUDIT-WEB-XSS-01**：  
  /audit 页面渲染必须对来自后端的可变字符串字段做安全输出（自动转义或显式 escape）；对包含 `<script>`、`onerror=` 等 payload 的字段，页面最终 DOM 不得执行脚本。

- **AC-AUDIT-WEB-XSS-02**：  
  提供最小验证证据：注入一条包含典型 XSS payload 的日志/字段（可通过测试数据或手工插入），访问 /audit 页面后，页面只显示转义后的文本且无脚本执行；证据包包含复现步骤与截图/HTML 片段（或浏览器控制台无执行证据说明）。

---

#### C5 附：C9 生产就绪门禁技术债（技术债验收口径，Phase2.x 实现）

本小节为 C5 的硬性待办附录，不构成 Phase2.0 新增开发项与编号。与 TECH_DEBT.md 中 TD-C9-01～TD-C9-03 一一对应。

**针对 TD-C9-01（压测数据库）**

- **AC-C9-STRESS-DB-01**：  
  压力测试（含 baseline + stress）须在与生产等价的数据库（如 PostgreSQL，或文档明确的生产等价配置）上可复现；报告中标明数据库类型与配置，且 Gate（success_rate / error_rate）在该环境下满足。

**针对 TD-C9-02（execution worker 故障演练自动化）**

- **AC-C9-FAILURE-DRILL-01**：  
  「执行端不可用」故障恢复演练须可复现、可自动化（脚本或测试注入）；提供触发→观测→恢复→验证的完整步骤与原始输出，不得仅依赖手工 kill/重启说明。

**针对 TD-C9-03（备份校验 schema-aware）**

- **AC-C9-BACKUP-VERIFY-01**：  
  备份与恢复演练的恢复后校验须 schema-aware：按当前迁移版本（或文档声明的 schema 版本）对必查表（如 decision_snapshot、log、trade）做存在性及条数/抽样校验；表不存在时须显式说明适用迁移版本或跳过理由。

#### C5 附：D2 技术债门禁（技术债验收口径，Phase2.x 实现）

本小节为 C5 的硬性待办附录，不构成 Phase2.0 新增开发项与编号。与 TECH_DEBT.md 中 D2-TRACE-404、D2-HEALTH-WEAK-OBSERVABILITY 一一对应。**未完成不得封版**（见封版 Gate GATE-TD-04、GATE-TD-05）。

**针对 D2-TRACE-404（执行失败 decision 必须可 trace）**

- **AC-D2-TRACE-404-01**：  
  执行失败的 decision（如 status=FAILED 或执行端异常导致未成交）必须可通过 trace 接口查询到；trace 结果中必须明确失败节点与失败原因（如 missing_nodes 含 execution/trade，或显式 failed_reason/failed_node 等），不得依赖 404 表示「不存在」而掩盖失败路径；审计与回放可据此区分「未创建」与「已创建但执行失败」。

**针对 D2-HEALTH-WEAK-OBSERVABILITY（health 异常门禁明确化）**

- **AC-D2-HEALTH-OBSERVABILITY-01**：  
  定义明确的 health 异常字段与判定标准（如 error_rate 阈值、recent_errors 条数阈值、或等价字段），文档化后作为生产门禁依据；不得仅依赖「log_ok OR recent_errors OR error_count>0」的弱或条件，须达到与 C9 Gate 同级的可判定性。

---

### D. 测试与验收（可验证点）

以下仅描述**可验证点**，不要求编写测试代码；用于端到端与回归验收判定。

#### D1. E2E-2.0 主流程可验证点

**目标**  
- 验证端到端：指定策略+版本+时间范围 → MetricsCalculator.compute → Evaluator.evaluate → 报告持久化 → 按 strategy_version_id / evaluated_at / param_version_id 查询到该报告；报告含 0.2 五项；baseline_version_id 为 null 或 strategy_version_id；无「建议参数/写回/优化」措辞。

**可验证点**  
- [ ] 调用 MetricsCalculator.compute 得到 B.2 五指标。  
- [ ] 调用 Evaluator.evaluate（传入 objective/constraint/baseline_version_id）得到含 0.2 五项的 EvaluationReport，报告持久化到 evaluation_report 表。  
- [ ] 按 strategy_version_id / evaluated_at / param_version_id 能查询到该报告。  
- [ ] 报告内 baseline_version_id 为 null 或为某 strategy_version_id（非 param_version_id）；conclusion、comparison_summary 无「建议参数」「写回」「优化」等措辞。

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
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### D2. E2E-2.0-只读可验证点

**目标**  
- 验证 Evaluator / MetricsCalculator 未写 Phase 1.2 数据；执行 E2E-2.0 后 Phase 1.2 表无任何行数或内容变化。

**可验证点**  
- [ ] 在固定 Phase 1.2 数据下执行一次 E2E-2.0；记录 Phase 1.2 相关表（如 decision_snapshot、trade、execution、log）的行数与关键行内容。  
- [ ] 执行后 Phase 1.2 表无任何行数或内容变化（即 **Evaluator / MetricsCalculator 未写 Phase 1.2 数据**）。

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
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### D3. E2E-2.0-可重复可验证点

**目标**  
- 验证同一输入连续两次 evaluate 产出的报告在 objective_definition、constraint_definition、conclusion、comparison_summary、指标相关字段上一致（允许 evaluated_at、id 不同）。

**可验证点**  
- [ ] 同一输入（strategy_id、strategy_version_id、period、config）连续调用两次 Evaluator.evaluate。  
- [ ] 两次产出的 evaluation_report 在 objective_definition、constraint_definition、conclusion、comparison_summary、指标相关字段上**一致**（允许 evaluated_at、id 不同）；即**评估报告可重复生成**。

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
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### D4. E2E-2.0-baseline 可验证点

**目标**  
- 验证 evaluate 时传入 baseline_version_id = 某 strategy_version_id 时，报告中 baseline_version_id 等于传入值，comparison_summary 体现与基线的对比；未出现 baseline 指向 param_version 或「无明确 baseline」的歧义。

**可验证点**  
- [ ] evaluate 时传入 baseline_version_id = 某 strategy_version_id；确保该 strategy_version 存在。  
- [ ] 报告中 baseline_version_id 等于传入值；comparison_summary 体现与基线的对比。  
- [ ] **未**出现 baseline 指向 param_version 或「无明确 baseline」的歧义。

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
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### D5. 回归清单可验证点

**目标**  
- 验证 Phase 1.2 追溯与决策快照查询仍可用；Evaluator/MetricsCalculator 读取 Phase 1.2 的路径无回归；Phase 1.2 表无被 2.0 写入。

**可验证点**  
- [ ] Phase 1.2 全链路追溯（如 get_trace_by_signal_id / get_trace_by_decision_id）仍可用。  
- [ ] Phase 1.2 决策快照查询（如 get_by_decision_id、list_by_strategy_time）仍可用。  
- [ ] Evaluator/MetricsCalculator 读取 Phase 1.2 的路径无回归（读接口行为与 1.2 一致）。  
- [ ] Phase 1.2 表（decision_snapshot、trade、execution、log 等）无被 Phase 2.0 写入。

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
- 禁止用「整体 E2E 已通过」替代本模块证据。

---

#### D6. 技术债专项修复：SECURITY（T2.0-TD-1）

**模块目标（Goal）**  
- 修复 /audit 页面 XSS 风险；确保所有可变字符串输出均经过安全转义。

**Strong Constraints**  
- **不得污染**：修复代码仅限于渲染层，禁止修改核心业务逻辑或数据库结构。
- **安全第一**：必须使用成熟的转义库或框架内置安全机制。

**验收口径 (AC)**  
- [ ] AC-AUDIT-WEB-XSS-01: /audit 页面渲染对所有可变字段进行转义。

**证据包要求**  
- 修改文件清单、测试命令、原始输出、代码审计报告。

---

#### D7. 技术债专项修复：TRACE（T2.0-TD-2）

**模块目标（Goal）**  
- 修复失败决策无法追溯的问题；确保 FAILED 状态的决策可通过 Trace 接口查询。

**Strong Constraints**  
- **只读边界**：Trace 逻辑必须保持只读，禁止在 Trace 过程中修改决策状态。

**验收口径 (AC)**  
- [ ] AC-D2-TRACE-404-01: Trace API 对失败决策返回聚合后的原因而非 404。

**证据包要求**  
- API 响应样本、原始输出、追溯日志。

---

#### D8. 技术债专项修复：HEALTH（T2.0-TD-3）

**模块目标（Goal）**  
- 升级健康检查可观测性；提供符合 Prometheus 规范的结构化指标。

**Strong Constraints**  
- **性能影响**：健康检查接口执行耗时必须 < 100ms，禁止在健康检查中执行重型查询。

**验收口径 (AC)**  
- [ ] AC-D2-HEALTH-OBS-01: 健康接口返回具体的组件状态与阈值指标。

**证据包要求**  
- 接口测试报告、原始输出。

---

### 技术债模块级绑定清单

| TD ID | target_module | solution_plan 摘要 | acceptance 命令 | 证据包名称 |
|-------|---------------|-------------------|-----------------|------------|
| TD-AUDIT-XSS-01 | Phase2.0:D6 | 模板全局转义 | `pytest tests/unit/test_security_rendering.py` | Phase2.0_D6_证据包.md |
| TD-TRACE-404-01 | Phase2.0:D7 | Trace API 聚合修复 | `pytest tests/integration/test_failed_trace.py` | Phase2.0_D7_证据包.md |
| TD-HEALTH-OBS-01 | Phase2.0:D8 | 结构化健康接口 | `pytest tests/unit/test_health_check.py` | Phase2.0_D8_证据包.md |
| GATE-TD-01 | Phase2.0:D6 | 状态闭环校验 | `python3 scripts/check_tech_debt_gates.py --current-phase 2.0` | Phase2.0_Gate_证据包.md |

---

## 三、关键约束遵守检查清单

### ✅ 开发项唯一性
- [ ] Phase2.0 开发项仅包含 A1、A2、C1～C5、D1～D5，无合并、拆分、新增、遗漏或编号调整。
- [ ] 执行顺序与本文档「一、推荐执行顺序」一致。

### ✅ 只读边界（Phase 2.0 对 Phase 1.2）
- [ ] 所有 Phase 2.0 接口**未**对 Phase 1.2 表执行任何 UPDATE/INSERT/DELETE。
- [ ] 所有写操作仅发生在 Phase 2.0 自有表（metrics_snapshot、evaluation_report），且已在验收中验证。
- [ ] MetricsCalculator / Evaluator 仅持有 Phase 1.2 的只读 Repository 或只读查询接口；接口约束「MUST NOT mutate any Phase 1.2 data」在模块级 Strong Constraints 中已重复出现。

### ✅ Evaluator Contract（0.2）
- [ ] Evaluator 每次输出均包含且持久化目标函数定义、约束条件、基线版本、结论与对比摘要。
- [ ] objective_definition / constraint_definition 符合 B.1 最小结构化字段集，无未文档化扩展。
- [ ] Evaluator **未**修改任何策略参数、**未**输出「建议参数」、**未**调用任何写回接口、**未**触发发布/回滚/门禁。

### ✅ 版本模型（B.1）
- [ ] strategy_version_id 为评估与比较的最小单元；param_version_id 为 strategy_version 子版本且 Phase 2.0 只做关联与记录、**不创建新版本**。
- [ ] baseline_version_id **仅**指向 strategy_version_id；评估报告必有明确 baseline（或无基线时显式标注）。

### ✅ 指标口径（B.2）
- [ ] trade_count、win_rate、realized_pnl、max_drawdown、avg_holding_time 已按 B.2 写死数据来源、统计口径、聚合规则、缺失数据处理。
- [ ] 实现与验收可抽检一致；**禁止**同名指标不同口径、禁止代码中未文档化指标出现在评估表。
- [ ] 风控拒绝/未成交 decision **不计入**核心指标；**不**把拒绝/失败 decision 算作「亏损一笔」。

### ✅ Phase 2.0 终止条件与禁止进入 Phase 2.1
- [ ] 允许进入 Phase 2.1：2.0-1～2.0-5 全部验收通过，且 F 节端到端用例（E2E-2.0、只读、可重复、baseline、回归）通过。
- [ ] 禁止进入 Phase 2.1 的情形（任一条即禁止）：指标口径未在 B.2 锁定或实现与文档不一致；baseline_version_id 指向 param_version 或评估报告无明确 baseline；评估报告不可重复生成；Evaluator 或 MetricsCalculator 对 Phase 1.2 表执行了写操作；任何「建议参数」「可写回」「供优化使用」等输出或语义。

---

#### 封版门禁（唯一自动化依据）

Phase2.x 封版门禁唯一真源为 `docs/tech_debt_registry.yaml`。
封版前必须运行以下命令，且**返回码为 0** 是唯一放行依据：

```bash
python3 scripts/check_tech_debt_gates.py --registry docs/tech_debt_registry.yaml --current-phase 2.0
```

校验逻辑由脚本内部强制执行：
1. **真源校验**：打印并校验 registry 文件的 realpath 与 SHA256。
2. **GATE 强锁**：所有 `id` 以 `GATE-` 开头的条目必须为 `DONE` 且 evidence_refs 非空。
3. **阶段强锁**：所有 `target_phase` 等于当前阶段的条目必须为 `DONE` 且 evidence_refs 非空。

---

## 技术债完成时点声明

根据 `docs/tech_debt_registry.yaml` 定义，所有技术债已锁定明确的 `deadline_phase`：

- 所有 `deadline_phase=2.0` 的技术债（含 SECURITY 与 OBSERVABILITY 核心条目）**必须**在 Phase2.0 封版前完成状态转为 `DONE`。
- 不允许任何形式的延期至后续 Phase。
- 不允许擅自修改 `deadline_phase` 绑定关系。
- 若因极端特殊原因需变更时点，必须发起单独的技术评审会议，并在证据包中记录评审留痕。
- 若当前 Phase 等于条目的 `deadline_phase` 且状态仍为 `TODO` 或 `IN_PROGRESS`，系统门禁将拒绝封版。

---

## 封版声明

> 本 Phase2.0 模块化开发交付包一经确认，即作为 Phase2.0 的**唯一开发真理源**。  
> 在后续开发、测试、验收过程中：  
> - 不允许新增开发项  
> - 不允许删除开发项  
> - 不允许调整模块顺序  
> - 不允许修改模块语义  
> - 不允许删减或弱化蓝本中的任何「必须/禁止/写死」规则  
>  
> 如需变更，必须基于 Phase2.0 开发蓝本（系统宪法）进行修订并同步本交付包。

---

**文档结束**
