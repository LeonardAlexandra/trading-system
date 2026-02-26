# Phase 2.0 开发交付包（全文版）

**版本**: v2.0.0（全文扩写）  
**创建日期**: 2026-02-07  
**基于**: Phase划分与实现顺序-需求清单.md v2.0.0、Phase1.2开发交付包.md（全文版）

**定位**：Phase 2.0 的唯一目标是**系统具备“可评估（Evaluatable）”能力**。本文档为评估系统宪法级文档：工程师可直接实现 Evaluator/Metrics 体系，QA 可逐条验收评估语义，Phase 2.1 可在不修改 Phase 2.0 语义的前提下只读复用评估结果。**严禁**在 Phase 2.0 中引入或暗示参数写回、自动发布、回滚、Optimizer、学习、优化或自动决策修改。

---

## A. 概述

### A.1 目标

系统具备**可评估**能力：按策略版本/时间，**只读** Phase 1.2 数据（decision_snapshot、trade、execution、audit log），按**写死的指标口径**计算指标，产出**版本化、可比较、可查询**的评估报告并**仅写入 Phase 2.0 自有表**。不实现、不暗示、不预留任何参数写回、自动发布、回滚、Optimizer 或学习能力（属 Phase 2.1）。

### A.2 完成判定

以下条件**全部**满足时，Phase 2.0 视为完成；**任一条未达成则禁止进入 Phase 2.1**。

- （1）2.0-1～2.0-5 全部验收通过（E 节每项可判定做了/没做、对/不对）。
- （2）**Evaluator Contract（0.2）**：Evaluator 每次输出均包含且持久化目标函数定义、约束条件、基线版本、结论与对比摘要；objective_definition / constraint_definition 符合 B.1 最小结构化字段集，无未文档化扩展；**Evaluator 未**修改任何策略参数、未输出“建议参数”、未调用任何写回接口、未触发发布/回滚/门禁。
- （3）至少一次在测试环境完成「指定策略+时间范围 → MetricsCalculator.compute → Evaluator.evaluate → 报告持久化 → 按 strategy_version_id / evaluated_at / param_version_id 查询到该报告」的验证。
- （4）**版本模型**（B.1）：strategy_version_id 为评估与比较的最小单元；param_version_id 为 strategy_version 子版本且 Phase 2.0 只做关联与记录、**不创建新版本**；baseline_version_id **仅**指向 strategy_version_id；评估报告必有明确 baseline（或无基线时显式标注）。
- （5）**指标口径**（B.2）：trade_count、win_rate、realized_pnl、max_drawdown、avg_holding_time 等已按 B.2 写死数据来源、统计口径、聚合规则、缺失数据处理；实现与验收可抽检一致；**禁止**同名指标不同口径、禁止代码中未文档化指标出现在评估表。
- （6）**只读边界**：所有 Phase 2.0 接口**未**对 Phase 1.2 表执行任何 UPDATE/INSERT/DELETE；所有写操作仅发生在 Phase 2.0 自有表（metrics_snapshot、evaluation_report 等），且已在验收中验证。

### A.3 Phase 2.0 终止条件与禁止进入 Phase 2.1 的情形（写死）

- **视为完成**：A.2 全部达成且 F 节端到端用例通过。
- **禁止进入 Phase 2.1** 的情形（任一条即禁止）：
  - 指标口径未在本文档 B.2 锁定或实现与文档不一致。
  - baseline_version_id 指向 param_version 或评估报告无明确 baseline。
  - 评估报告不可重复生成（同一输入多次 evaluate 结果不一致且非文档约定的非确定性部分）。
  - Evaluator 或 MetricsCalculator 对 Phase 1.2 表执行了写操作。
  - 出现任何“建议参数”“可写回”“供优化使用”等输出或接口。

### A.4 前置依赖

- Phase 1.2 已完成（含决策输入快照、全链路追溯、审计日志可查）；Phase 1.2 提供的**只读**数据与 API 可用。

### A.5 In-Scope / Out-of-Scope（写死）

| 类别 | 内容 |
|------|------|
| **In-Scope** | MetricsRepository 与 metrics_snapshot 表（Phase 2.0 自有）；MetricsCalculator **只读** Phase 1.2 的 trade/decision_snapshot/execution 等，按 B.2 口径计算指标并**仅写入** metrics_snapshot；Evaluator **只读** Phase 1.2 数据与 MetricsCalculator 输出，产出符合 0.2 的评估报告并**仅写入** evaluation_report；策略版本与评估结果按 strategy_version_id/评估时间/param_version_id 可查；历史数据假设与硬性待办文档。 |
| **Out-of-Scope** | 任何策略或参数**写回**、自动发布、发布门禁、回滚、Optimizer、可学习参数白名单、强化学习、自动决策修改（属 Phase 2.1）；完整智能 BI 前端；历史数据导入实现（仅约定与待办）。 |

---

## B. 架构级硬约束（0.1～0.4 在本 Phase 的落地）

| 约束 | 在本 Phase 的落地 |
|------|------------------|
| **0.1 学习边界** | 不实现。本 Phase 不修改任何策略参数或配置，仅产出评估报告。 |
| **0.2 Evaluator Contract** | **必须落地**，且为全文主轴。Evaluator 的职责**只有三件事**：（1）**读取** Phase 1.2 的真实历史数据（decision_snapshot、trade、execution，仅只读）；（2）按**写死的指标口径**（B.2）通过 MetricsCalculator 得到指标，不自行算数；（3）产出**版本化、可比较、可查询**的评估报告并**仅写入** evaluation_report 表。Evaluator **不允许**：修改任何策略参数；输出“建议参数”；调用任何写回接口；触发发布、回滚或门禁。每次输出必须包含且持久化：目标函数定义、约束条件、基线版本、结论与对比摘要；存储 schema 须支持按策略版本 ID / 评估时间 / 参数版本 ID 查询；不允许仅输出不可查询的报表文件。 |
| **0.3 发布门禁与回滚** | 不实现。属 Phase 2.1。 |
| **0.4 决策输入快照** | **只读依赖**。MetricsCalculator / Evaluator **仅读取** Phase 1.2 的 decision_snapshot（按 decision_id 或时间范围）；本 Phase **不写入**决策快照，且**禁止**对 Phase 1.2 任何表执行 UPDATE/INSERT/DELETE。 |

### B.0 Phase 2.0 只读边界（写死）

- **Phase 2.0 是只读系统**：对 Phase 1.2 数据**仅读**；对 Phase 1.2 表**禁止**任何 UPDATE / INSERT / DELETE。
- **所有写操作**只发生在 Phase 2.0 自有表：metrics_snapshot、evaluation_report，以及策略版本/参数版本关联表（若由 2.0 维护且不影响 1.2）。
- 接口层**必须**遵守：任何 Phase 2.0 对外或内部 API **MUST NOT mutate any Phase 1.2 data.** 实现时通过依赖注入与权限约束保证：MetricsCalculator/Evaluator 仅持有 Phase 1.2 的只读 Repository 或只读查询接口。

### B.1 版本模型（写死）

以下定义锁死，实现与 Phase 2.1 回滚/基线比较必须一致，禁止在未修订本文档前提下变更语义。

#### 1️⃣ strategy_version_id 与 param_version_id 的关系

- **参数版本是否为策略版本的子版本**：**是**。param_version 是 strategy_version 的**子版本**：同一 strategy_version 下可存在多组「仅可学习参数」不同取值，每组对应一个 param_version_id；策略代码/风控逻辑等不变部分由 strategy_version 标识，可变参数由 param_version 标识。存储上可为一表（strategy_version 主表 + param_version 关联）或两表，但**语义上** param_version 从属于 strategy_version。
- **评估报告绑定哪一个作为“对比与回滚的最小单元”**：**策略维度以 strategy_version_id 为最小可回滚单元**；**参数维度以 param_version_id 为最小可对比单元**。单条 evaluation_report **必须**绑定至少 strategy_version_id；若本次评估针对某组参数，则同时绑定 param_version_id。**对比与回滚的最小单元**：回滚时按 strategy_version 回退（2.1）；**同 strategy_version 下多 param_version 的对比**以 param_version_id 为粒度。
- **基线比较时使用 strategy_version 还是 param_version**：**写死规则**——baseline_version_id 在 evaluation_report 中**仅指向 strategy_version_id**（即 baseline 为「上一策略版本」或「选定的历史策略版本」）。同一 strategy_version 下不同 param_version 的对比，通过「多条 evaluation_report 共享同一 strategy_version_id、不同 param_version_id」并按 param_version_id 查询实现；**基线比较**指「当前 strategy_version（或当前 param_version 所属的 strategy_version）与 baseline_version_id（strategy_version）的指标/结论对比」。即：**基线比较使用 strategy_version**；同版内多组参数的比较使用 param_version_id 区分报告。

#### 2️⃣ objective_definition / constraint_definition 最小结构化字段集（写死）

底层仍可为 JSONB，但**字段名与语义**以本文档为准，**禁止**在未修订本文档前提下自由扩展或改名。

**objective_definition**（目标函数定义）——最小字段集：

| 字段名 | 类型 | 含义 |
|--------|------|------|
| primary | string | 主目标唯一键，枚举：`pnl` \| `sharpe` \| `max_drawdown` \| `win_rate` \| `trade_count` |
| primary_weight | number | 主目标权重（如 1.0） |
| secondary | array of string | 次目标键列表，取值同上枚举，可为空数组 |
| secondary_weights | array of number | 与 secondary 一一对应的权重，长度与 secondary 一致 |

- 禁止新增未在本文档列出的顶层键；扩展时仅允许在本文档修订后增加可选键并注明语义。

**constraint_definition**（约束条件）——最小字段集：

| 字段名 | 类型 | 含义 |
|--------|------|------|
| max_drawdown_pct | number \| null | 最大回撤上限（百分比），null 表示不约束 |
| min_trade_count | number \| null | 最小交易次数，null 表示不约束 |
| max_risk_exposure | number \| null | 最大风险暴露（口径在实现中与风控一致），null 表示不约束 |
| custom | object \| null | 预留键，若使用则必须为 key-value 且 key 在交付包或实现文档中列明语义；禁止未文档化的自由键 |

- 禁止新增未列出的顶层键（除 custom 内已文档化的 key）；实现时若无需某约束则填 null，不得省略该键。

#### 3️⃣ MetricsCalculator 数据口径（写死）

- **盈亏 / 胜率 / 回撤 以何为准**：**以 trade 为准**。即：pnl、win_rate、max_drawdown 等**仅基于已落库的 trade 记录**计算；execution 仅用于「是否有执行」的辅助判断，**不**用 execution 的未成交或中间状态参与盈亏/胜率/回撤计算。若存在「execution 有但 trade 尚未写入」的延迟，则**不计入**当次 compute 的周期内，以数据一致性为准（即：以 period 内已闭合的 trade 为统计范围）。
- **组合规则**：收益 = sum(trade.realized_pnl)（或等价字段）；胜率 = 盈利 trade 笔数 / 总 trade 笔数；回撤 = 基于按时间序的累计收益曲线计算最大回撤。**不**以 execution 数量或 decision 数量替代 trade 数量。
- **风控拒绝 / 下单失败的 decision 是否计入统计**：**不计入**。仅「已产生 trade 的 decision」参与盈亏/胜率/回撤统计。风控拒绝或下单失败的 decision：**不**计入 trade_count、**不**计入 pnl/胜率/回撤；可选在指标中单独提供「decision_total / decision_rejected / decision_executed」等统计口径供分析，但**核心指标**（pnl、win_rate、max_drawdown、trade_count）**仅基于 trade**，且**不**把拒绝/失败 decision 算作「亏损一笔」或「0 收益一笔」。若需「决策通过率」等，以单独字段或扩展口径提供，不与 pnl/win_rate 混淆。

#### 4️⃣ B.2 必实现指标清单（写死、工程级不可歧义）

以下指标为 Phase 2.0 **必须实现且唯一口径**；禁止同名指标不同口径、禁止在代码中未文档化指标出现在 metrics_snapshot / evaluation_report、禁止未在本文档列出的指标字段进入评估表。

| 指标名 | 数据来源 | 统计口径 | 聚合规则 | 缺失/异常数据处理 |
|--------|----------|----------|----------|-------------------|
| **trade_count** | trade 表 | 仅状态为已成交/已平仓的成交笔数；风控拒绝、下单失败、未成交的 decision **不计入** | 时间范围内 COUNT(trade_id) | 无 trade 时 trade_count = 0 |
| **win_rate** | trade 表 | 已平仓/已成交的 trade 中，realized_pnl > 0 的笔数 / 总笔数；**含手续费**（以 trade 表记录为准） | SUM(I(realized_pnl>0)) / COUNT(*); 无成交时按实现约定取 0 或 NULL | 无 trade 时与实现约定一致（0 或 NULL），文档与验收写死其一 |
| **realized_pnl** | trade 表 | 已实现盈亏，**含手续费、含滑点**（以 trade 表字段为准）；风控拒绝/未成交 **不计入** | 时间范围内 SUM(realized_pnl) | 无 trade 时 realized_pnl = 0 |
| **max_drawdown** | 基于 trade 的权益曲线 | 基于逐笔成交后累计权益曲线计算的最大回撤；**含手续费、含滑点**；风控拒绝/未成交不参与权益曲线 | 从权益高点至低点的最大跌幅（绝对值或比例，实现与 C 节 schema 写死其一） | 无 trade 或仅一笔时按文档约定（如 0 或 NULL） |
| **avg_holding_time** | trade 表 | 从开仓到平仓的持仓时长（单位：秒，写死）；以 trade 的 open_time/close_time 或等价字段计算 | 时间范围内 AVG(close_time - open_time) 秒 | 无 trade 或缺少时间字段时为 NULL |

- **数据来源约定**：若 trade 表无 realized_pnl 字段则从 execution 或约定字段聚合，且必须在本文档或实现说明中写死，保证全系统唯一口径。
- **MetricsCalculator** 只负责按上表“算数”；**不**输出“好/坏”判断；baseline 比较与结论由 **Evaluator** 负责。

---

## C. 数据模型与 Schema

**约定**：Phase 2.0 自有表仅限本节定义；禁止在未修订本文档前提下向 metrics_snapshot / evaluation_report 增加未文档化字段。

### C.1 指标存储（metrics_snapshot，Phase 2.0 自有）

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | BIGINT / UUID | PK | 主键 |
| strategy_id | string | NOT NULL, 外键或逻辑关联 | 策略标识 |
| strategy_version_id | string | NOT NULL | 评估与比较的最小单元，见 B.1 |
| param_version_id | string | NULLABLE | 子版本，仅标识参数差异；Phase 2.0 只关联不创建 |
| period_start | timestamptz | NOT NULL | 统计区间起 |
| period_end | timestamptz | NOT NULL | 统计区间止 |
| trade_count | integer | NOT NULL | 见 B.2，无 trade 时为 0 |
| win_rate | decimal | NULLABLE 或 0 | 见 B.2 |
| realized_pnl | decimal | NOT NULL | 见 B.2，无 trade 时为 0 |
| max_drawdown | decimal | NULLABLE 或 0 | 见 B.2（单位与口径写死） |
| avg_holding_time_sec | decimal | NULLABLE | 见 B.2，单位秒 |
| created_at | timestamptz | NOT NULL | 写入时间 |

- **禁止**在表中出现未在 B.2 或本表列出的指标字段；若增加 sharpe 等扩展指标，须先修订 B.2 与本节。
- 索引：`(strategy_id, period_start, period_end)`；`(strategy_id, strategy_version_id)`；`(strategy_version_id, param_version_id, period_start)`。

### C.2 评估结果（evaluation_report，满足 0.2，Phase 2.0 自有）

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | BIGINT / UUID | PK | 主键 |
| strategy_id | string | NOT NULL | 策略标识 |
| strategy_version_id | string | NOT NULL | 被评估的策略版本（strategy_version） |
| param_version_id | string | NULLABLE | 若评估针对某组参数则填，否则 NULL |
| evaluated_at | timestamptz | NOT NULL | 评估执行时间 |
| period_start | timestamptz | NOT NULL | 评估区间起 |
| period_end | timestamptz | NOT NULL | 评估区间止 |
| objective_definition | JSONB | NOT NULL | B.1 最小字段集，禁止未文档化顶层键 |
| constraint_definition | JSONB | NOT NULL | B.1 最小字段集，禁止未文档化顶层键 |
| baseline_version_id | string | NULLABLE | **仅存 strategy_version_id**；无基线时 NULL |
| conclusion | string | NOT NULL | 枚举：pass / fail / grade（或实现约定等级），由 Evaluator 写入 |
| comparison_summary | JSONB 或 TEXT | NULLABLE | 与基线的对比摘要，由 Evaluator 写入 |
| metrics_snapshot_id | BIGINT / UUID | NULLABLE, FK → metrics_snapshot.id | 关联的本周期指标快照 |
| created_at | timestamptz | NOT NULL | 写入时间 |

- **禁止**：baseline_version_id 指向 param_version；conclusion 或 comparison_summary 中出现“建议参数”“可写回”“供优化”等语义。
- 索引：`(strategy_id, evaluated_at)`、`(strategy_version_id, evaluated_at)`、`(param_version_id, evaluated_at)`。

### C.3 策略版本（只读引用或 Phase 2.0 只读缓存）

| 表/实体 | 骨架字段 | 说明 |
|---------|----------|------|
| strategy_version 或等价 | id, strategy_id, version_tag, config_snapshot (JSONB), effective_from?, created_at | 策略配置版本化；Phase 2.0 **仅读取**用于基线解析与报告展示，**不在此表执行写操作**；若表由 1.2 或其他模块维护，2.0 仅通过只读接口访问。 |

---

## D. 接口与边界

**边界原则**：MetricsCalculator **只负责按 B.2 口径算数**，不知道 baseline、版本比较、结论；**不**输出“好/坏”判断。Evaluator **负责**版本比较、结论生成、写入 evaluation_report；**不**参与指标计算细节（必须调用 MetricsCalculator 或读取 metrics_snapshot，禁止自行从 trade 算指标）。**禁止**：Evaluator 直接算指标；MetricsCalculator 输出 conclusion 或“建议”。

所有**读取 Phase 1.2 数据**的接口（TradeRepository、DecisionSnapshot、Execution 等）在实现与文档中**必须**满足：**This API MUST NOT mutate any Phase 1.2 data.** Phase 2.0 的写操作**仅**允许：MetricsRepository.write（写入 metrics_snapshot）、EvaluationReportRepository 写入 evaluation_report。

### D.1 MetricsRepository

- **写**：仅写入 Phase 2.0 自有表 metrics_snapshot；**不**读写 Phase 1.2 表。
- **读**：仅读 Phase 2.0 自有表。

```text
MetricsRepository.write(snapshot: MetricsSnapshot) -> void
# 仅写入 metrics_snapshot 表。This API MUST NOT mutate any Phase 1.2 data.

MetricsRepository.get_by_strategy_period(strategy_id, period_start, period_end) -> list[MetricsSnapshot]
MetricsRepository.get_by_strategy_time_range(strategy_id, start_ts, end_ts) -> list[MetricsSnapshot]
# 仅读 metrics_snapshot。
```

### D.2 MetricsCalculator

- **职责**：按 B.2 写死的口径从 Phase 1.2 **只读**数据计算指标；**不**知道 baseline、不产出结论、不写 evaluation_report。
- **数据来源**：仅**只读** trade 表（及 B.2 约定的 execution/decision_snapshot 辅助）；盈亏/胜率/回撤/笔数/持仓时间**以 trade 为准**；风控拒绝、下单失败的 decision **不计入** B.2 核心指标。
- **输出**：MetricsResult（trade_count, win_rate, realized_pnl, max_drawdown, avg_holding_time_sec 等 B.2 字段）；**不**包含 conclusion、comparison_summary、baseline 比较。

```text
MetricsCalculator.compute(strategy_id: str, strategy_version_id: str, param_version_id?: str, period_start, period_end) -> MetricsResult
# 输入：策略与版本、时间范围。仅读取 Phase 1.2 的 trade/execution/decision_snapshot，不写入任何表。
# This API MUST NOT mutate any Phase 1.2 data.
# MetricsResult 字段与 B.2/C.1 一致：trade_count, win_rate, realized_pnl, max_drawdown, avg_holding_time_sec；禁止未文档化字段。
# 可选：compute 后由调用方写入 metrics_snapshot（Evaluator 或独立 job），MetricsCalculator 本身不写库。
```

### D.3 Evaluator（输出必须满足 0.2）

- **职责**：读取 Phase 1.2 数据与 MetricsCalculator 输出（或 metrics_snapshot）；做**版本比较**与**结论生成**；**仅写入** evaluation_report；**不**自行从 trade 计算指标（必须用 MetricsCalculator 或已落库的 metrics_snapshot）。
- **版本与基线**：baseline_version_id **仅**存 strategy_version_id；objective_definition / constraint_definition 使用 B.1 最小字段集；**禁止**输出“建议参数”、写回、发布/回滚语义。

```text
Evaluator.evaluate(strategy_id, strategy_version_id, param_version_id?, period_start, period_end, config?) -> EvaluationReport
# config: objective_definition?, constraint_definition?, baseline_version_id? (必须为 strategy_version_id 或 null)
# 内部：调用 MetricsCalculator.compute 或读取 metrics_snapshot；根据 objective/constraint 与 baseline 生成 conclusion、comparison_summary。
# 侧效应：仅写入 evaluation_report 表。This API MUST NOT mutate any Phase 1.2 data.
# EvaluationReport 必含：objective_definition, constraint_definition, baseline_version_id, conclusion, comparison_summary，及关联的 metrics 摘要或 metrics_snapshot_id。

EvaluationReportRepository.get_by_strategy_version(strategy_version_id) -> list[EvaluationReport]
EvaluationReportRepository.get_by_evaluated_at(strategy_id, from_ts, to_ts) -> list[EvaluationReport]
EvaluationReportRepository.get_by_param_version(param_version_id) -> list[EvaluationReport]
# 仅读 evaluation_report。This API MUST NOT mutate any Phase 1.2 data.
```

### D.4 策略版本与评估结果可查

```text
StrategyVersionRepository.get_by_id(version_id) -> StrategyVersion
StrategyVersionRepository.list_by_strategy(strategy_id) -> list[StrategyVersion]
# Phase 2.0 仅读取策略版本信息；若该表属 1.2 或外部，2.0 仅通过只读接口访问。This API MUST NOT mutate any Phase 1.2 data.
```

- 本 Phase **不提供**：参数写回、发布、回滚、Optimizer、学习、写回 API。

---

## E. 任务拆分

每项任务均给出**输入（表/接口）**、**输出（表/报告）**、**可验证断言**；验收须能判断：指标是否算、口径是否对、baseline 是否用对、是否完全只读。

| 任务编号 | 目的 | 输入（表/接口） | 输出（表/报告） | 实现要点 | 可验证断言（验收 checkbox） | 交付物 |
|----------|------|-----------------|-----------------|----------|-----------------------------|--------|
| **T2.0-1** | MetricsRepository 与指标存储 | 调用方传入 MetricsSnapshot（含 B.2 字段） | metrics_snapshot 表持久化；查询返回 list[MetricsSnapshot] | 写入/按策略与时间段、strategy_version 查询；schema 与 C.1 一致；**仅写 Phase 2.0 表** | [ ] 指标可按 strategy_id/strategy_version_id/period 写入并持久化；[ ] 按策略、时间段、版本查询结果与写入一致；[ ] **只读边界**：该模块未对 Phase 1.2 表执行任何写操作；[ ] 表中仅存在 B.2/C.1 文档化字段，无未文档化列 | 迁移脚本、MetricsRepository、与 C.1 契约说明 |
| **T2.0-2** | MetricsCalculator | Phase 1.2：trade 表（及 B.2 约定的 execution/decision_snapshot）；入参：strategy_id, strategy_version_id, param_version_id?, period_start, period_end | MetricsResult（trade_count, win_rate, realized_pnl, max_drawdown, avg_holding_time_sec）；可选写入 metrics_snapshot | **数据口径 B.2**：盈亏/胜率/回撤/笔数/持仓时间仅基于 **trade**；风控拒绝、下单失败 decision **不计入**；**仅读** Phase 1.2，不写 Phase 1.2 | [ ] 给定策略+版本+时间范围可返回 B.2 五指标；[ ] **口径**：用固定 trade 集抽检 — trade_count=COUNT、realized_pnl=SUM、win_rate=盈利笔数/总笔数、max_drawdown 来自权益曲线、avg_holding_time_sec=AVG(close-open)；[ ] **口径**：构造“仅风控拒绝无 trade”的周期，上述核心指标为 0 或 NULL（与 B.2 约定一致）；[ ] **只读边界**：compute 执行前后 Phase 1.2 表无任何 INSERT/UPDATE/DELETE；[ ] MetricsCalculator 未输出 conclusion、comparison_summary、baseline 或“建议” | MetricsCalculator、B.2 口径说明、与 D.2 接口一致 |
| **T2.0-3** | Evaluator | Phase 1.2 只读；MetricsCalculator.compute 或 metrics_snapshot；入参：strategy_id, strategy_version_id, param_version_id?, period_*, config(objective, constraint, baseline_version_id?) | evaluation_report 表一条记录；内存 EvaluationReport（含 0.2 五项） | 调用 MetricsCalculator 或读 metrics_snapshot，**不**从 trade 直接算指标；objective/constraint 仅 B.1 最小字段集；baseline_version_id 仅 strategy_version_id 或 null；**仅写** evaluation_report | [ ] 产出报告必含 objective_definition, constraint_definition, baseline_version_id, conclusion, comparison_summary，且已持久化；[ ] **版本**：report.strategy_version_id 存在；baseline_version_id 为 null 或为某 strategy_version_id（**非** param_version_id）；[ ] **结构**：objective 含 primary、primary_weight、secondary、secondary_weights；constraint 含 max_drawdown_pct、min_trade_count、max_risk_exposure、custom；无未文档化顶层键；[ ] **只读边界**：evaluate 执行前后 Phase 1.2 表无任何写操作；Evaluator 未调用任何写回/发布/回滚接口；[ ] 结论与 comparison_summary 中无“建议参数”“可写回”“供优化”等措辞 | Evaluator 实现、报告 schema（0.2 与 B.1） |
| **T2.0-4** | 策略版本与评估结果可查 | strategy_version 表或只读接口；evaluation_report 表 | 按 strategy_version_id / evaluated_at / param_version_id 查询到的 list[EvaluationReport] | 策略版本仅读；评估结果按三键查询；baseline_version_id 仅存 strategy_version_id；与 1.2 边界明确 | [ ] 策略配置可按 version_id 查询；[ ] 评估结果可按 strategy_version_id、evaluated_at 范围、param_version_id 查询；[ ] 返回数据含 0.2 语义字段；[ ] **版本模型**：evaluation_report.baseline_version_id 仅引用 strategy_version 表 id，不引用 param_version；[ ] **只读边界**：查询接口未对 Phase 1.2 表执行写操作 | 策略版本与评估结果查询 API、schema 文档 |
| **T2.0-5** | 历史数据假设与硬性待办 | 无（文档任务） | 本文档内「历史数据假设」与「硬性待办」章节 | 责任方、TradingView 可行方式、与 Webhook 一致性；2.1 结束前格式与至少一条导入路径及责任方；触发条件；**本 Phase 不实现导入** | [ ] 交付包中存在历史数据假设章节；[ ] 硬性待办与触发条件、责任方已写明；[ ] 未在 Phase 2.0 实现历史数据导入代码 | 本文档附录更新 |

---

## F. 测试与验收

### F.1 端到端用例

- **E2E-2.0（主流程）**  
  - 输入：strategy_id、strategy_version_id、param_version_id（可选）、period_start、period_end。  
  - 步骤：调用 MetricsCalculator.compute → 得到 B.2 五指标；调用 Evaluator.evaluate（传入 objective/constraint/baseline_version_id）→ 得到含 0.2 五项的 EvaluationReport → 报告持久化到 evaluation_report 表。  
  - 验证：按 strategy_version_id / evaluated_at / param_version_id 能查询到该报告；报告内 baseline_version_id 为 null 或为某 strategy_version_id（非 param_version_id）；conclusion、comparison_summary 无“建议参数”“写回”“优化”等措辞。

- **E2E-2.0-只读**  
  - 步骤：在固定 Phase 1.2 数据下执行一次 E2E-2.0；记录 Phase 1.2 相关表的行数与关键行内容。  
  - 验证：执行后 Phase 1.2 表无任何行数或内容变化（即 **Evaluator / MetricsCalculator 未写 Phase 1.2 数据**）。

- **E2E-2.0-可重复**  
  - 步骤：同一输入（strategy_id、strategy_version_id、period、config）连续调用两次 Evaluator.evaluate。  
  - 验证：两次产出的 evaluation_report 在 objective_definition、constraint_definition、conclusion、comparison_summary、指标相关字段上**一致**（允许 evaluated_at、id 不同）；即**评估报告可重复生成**。

- **E2E-2.0-baseline**  
  - 步骤：evaluate 时传入 baseline_version_id = 某 strategy_version_id；确保该 strategy_version 存在。  
  - 验证：报告中 baseline_version_id 等于传入值；comparison_summary 体现与基线的对比；**未**出现 baseline 指向 param_version 或“无明确 baseline”的歧义。

### F.2 回归清单

- Phase 1.2 追溯与决策快照查询仍可用；Evaluator/MetricsCalculator 读取 Phase 1.2 的路径无回归；Phase 1.2 表无被 2.0 写入。

### F.3 禁止进入 Phase 2.1 的失败情形（验收不通过即禁止进入 2.1）

以下任一条成立则**禁止**进入 Phase 2.1，须在 Phase 2.0 内修复并重新验收：

- 指标口径未在 B.2 锁定，或实现与 B.2 不一致（如同名指标不同口径、未文档化指标出现在评估表）。
- baseline_version_id 指向 param_version，或评估报告无明确 baseline 且未在结论中说明。
- 评估报告不可重复生成（同一输入两次 evaluate 结果在结论/指标上不一致，且非文档约定的非确定性部分）。
- Evaluator 或 MetricsCalculator 对 Phase 1.2 表执行了 INSERT/UPDATE/DELETE。
- 任何接口或报告中出现“建议参数”“可写回”“供优化使用”等输出或语义。

---

## G. 风险与非功能性要求

- **指标口径**：B.2 五指标为必实现且唯一口径；若增加 sharpe、无风险利率等，须先修订 B.2 与 C.1 并约定默认值，**禁止**实现中“顺手多算”未文档化指标。周期口径（period_start/period_end）与产品约定一致；缺失数据按 B.2 表写死规则处理。
- **性能**：大量 trade 时 MetricsCalculator 需在交付包或实现说明中约定：单次 compute 的时间/空间上限或增量/聚合策略（如按日预聚合再汇总），避免全表扫描导致不可验收。
- **审计**：评估报告为只读产出，不修改策略或参数；所有报告可查可追溯；实现须保证 Evaluator 无写 Phase 1.2 的代码路径（依赖只读 Repository + 代码评审/验收）。
- **实现选择（写死）**：若存在多种实现方式，采用**最保守、最可验证、最不易越权**的一种；例如：Evaluator 必须通过 MetricsCalculator 或 metrics_snapshot 获取指标，不得直接读 trade 表算数；所有写操作仅限 Phase 2.0 表，在数据访问层显式禁止 Phase 1.2 写权限。

---

## H. 交付物清单

| 类别 | 交付物 |
|------|--------|
| **代码/配置** | metrics_snapshot 迁移与 C.1 schema；MetricsRepository（仅写 Phase 2.0 表）；MetricsCalculator（仅读 Phase 1.2、按 B.2 算数、不产出结论）；Evaluator 及 evaluation_report 迁移（仅写 evaluation_report）；StrategyVersion 只读访问与 EvaluationReportRepository；历史数据假设与硬性待办章节（T2.0-5）。 |
| **文档** | 指标口径表（B.2）与 metrics_snapshot/evaluation_report schema（C.1/C.2，满足 0.2）；与 Phase 1.2 只读边界说明；历史数据假设、硬性待办与触发条件；接口约束「MUST NOT mutate any Phase 1.2 data」的落点列表。 |

---

## 附录：历史数据假设与硬性待办（T2.0-5 交付内容）

- **历史数据假设**：责任方（谁提供历史导出、谁落地导入）；TradingView 侧可行方式（CSV/手动/API 等）；与实盘 Webhook 格式的一致性要求。
- **硬性待办**：2.1 结束前必须约定历史数据格式、至少一条导入路径（如 CSV/API）及责任方。
- **触发条件**：当实盘评估闭环跑通且需与历史回测对比时，启动历史管道；若 2.0 启动时责任方未定，则写明「2.1 结束前由产品/技术共同确认来源与格式」。
- **Phase 2.0 边界**：本 Phase **不实现**历史数据导入；仅交付假设与待办文档，供 2.1 或后续阶段使用。

---

**文档结束**
