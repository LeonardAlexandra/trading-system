# Phase 2.1 开发交付包（全文版）

**版本**: v2.0.0（全文扩写）  
**创建日期**: 2026-02-07  
**基于**: Phase划分与实现顺序-需求清单.md v2.0.0、Phase2.0开发交付包.md（全文版）、Phase1.2开发交付包.md（全文版）

**定位**：Phase 2.1 是**系统中唯一允许“学习 / 写回 / 发布 / 回滚”的 Phase**。本文档为学习系统的安全边界文档：学习能力严格限制在白名单参数内，学习结果不能绕过评估与门禁直接上线，发布与回滚可被 QA/运维验证，学习失败或异常时可自动停用并回到稳定态。**不得**修改或削弱 Phase 2.0 的 Evaluator Contract 与评估语义；Phase 2.1 **只能**消费 Phase 2.0 的 evaluation_report 作为学习与决策依据，严禁直接从 Phase 1.2 的 trade/decision_snapshot 做“自评估”。

---

## A. 概述

### A.1 目标

系统具备**可学习、可发布**能力：至少跑通一次「**评估（2.0）→ 基于评估结果的参数建议（仅白名单）→ 候选态 → 门禁 → 上线 → 再评估**」闭环，并具备**一键回滚**与**自动停用异常版本（熔断）**。参数修改**仅限 0.1 参数白名单**，白名单来自**单一事实源**（B.4）；默认 **Human-in-the-loop**（人工确认路径），自动写回须**显式配置开启**且必须经发布门禁；学习输入**只能**来自 Phase 2.0 的 evaluation_report，禁止自建“第二套评估”。

### A.2 完成判定

以下条件**全部**满足时，Phase 2.1 视为完成；**任一条未达成则禁止进入后续 Phase（如完整智能 BI 或更高级学习）**。

- （1）T2.1-1、T2.1-2、T2.1-4 全部验收通过（T2.1-3 按需）；E 节每项具备输入/输出/可验证断言且已执行验收。
- （2）**学习边界（Learning Surface）**：可学习参数清单（B.1）与禁止修改项清单已在交付包中显式列出；**白名单事实源**（B.4）已明确且文档与代码/ schema 一致已验收；Optimizer/Learner **仅**接受白名单内参数，**未**修改策略执行逻辑、风控核心、下单流程、幂等/去重/对账机制。
- （3）**学习输入仅来自 Phase 2.0**：Optimizer/Learner 的输入**仅**为 Phase 2.0 的 evaluation_report 及关联的 strategy_version_id/param_version_id；**未**出现直接扫描 trade 表重算指标或基于 decision_snapshot 的“私有评估”；验收可验证（接口约束 + 测试）。
- （4）**至少一次完整闭环验证**：评估(2.0) → 参数建议(2.1) → 提交 candidate → 门禁(人工或规则) → approved → 生效为 active → 再评估并可查询新报告；且执行一次一键回滚并验证回滚记录。
- （5）**发布状态机**（B.3）：candidate / approved / active / stable / disabled 已实现；各状态允许/禁止行为、迁移条件、触发方（系统/人工）已写死并可验收；**仅 active 允许交易**已落实。
- （6）**写回规则**：写回对象**仅**为 param_version（不写 strategy_version）；写回路径**仅**为 candidate → approved → active；**禁止**跳过 candidate、跳过审批、覆盖 stable；自动写回默认关闭、配置开启且有审计记录。
- （7）**回滚与异常停用**（B.2）：回滚粒度为参数级（回到 stable param_version）；异常触发条件与默认阈值已实现；触发时自动切回 stable、active→disabled、强告警+审计；验收包含人工确认路径、自动写回关闭、自动写回开启但被门禁拦截、异常触发后自动回滚。
- （8）**Phase 2.0 不被污染**：Phase 2.1 **未**修改 evaluation_report、**未**写入 metrics_snapshot、**未**更改 Phase 2.0 的 schema 或指标口径；仅追加 param_version、release_audit/learning_audit、发布状态等 Phase 2.1 自有数据。

### A.3 Phase 2.1 终止条件与禁止进入后续 Phase 的情形（写死）

- **视为完成**：A.2 全部达成且 F 节端到端用例通过。
- **禁止进入后续 Phase** 的情形（任一条即禁止）：
  - 学习结果可绕过评估直接上线（未以 2.0 evaluation_report 为唯一学习输入，或未经 candidate→门禁→active）。
  - 无法回滚（无 stable 标记或 rollback_to_stable 不可用、无审计）。
  - 白名单参数被越权修改（写回或建议中出现白名单外键，或白名单事实源与文档不一致）。
  - 发布状态不可追溯（release_audit 缺失或状态迁移无记录）。
  - Phase 2.0 被污染（2.1 写入了 evaluation_report/metrics_snapshot 或修改了 2.0 口径）。

### A.4 前置依赖

- Phase 2.0 已完成（Evaluator、evaluation_report 可查、按 strategy_version_id/param_version_id/evaluated_at 查询就绪）。

### A.5 In-Scope / Out-of-Scope（写死）

| 类别 | 内容 |
|------|------|
| **In-Scope** | Optimizer/Learner（**仅**读 2.0 evaluation_report，仅白名单参数建议）；实盘反馈驱动 2.0 评估闭环（2.0 能力，2.1 仅触发与消费）；发布门禁（人工确认或风控护栏）；candidate→approved→active 写回路径；一键回滚到 stable；自动停用异常版本（B.2 条件与阈值）；可学习参数清单与禁止修改项清单（B.1/B.4）；release_audit/learning_audit。 |
| **Out-of-Scope** | 修改策略执行逻辑、风控核心、下单流程、信号代码、幂等/对账（0.1 禁止）；未显式启用或未过门禁的自动写回；完整智能 BI（独立交付包）；ShadowExecutor/MarketSimulator/PromotionEngine/EliminationEngine 为按需占位（T2.1-3）。 |

---

## B. 架构级硬约束（0.1～0.4 在本 Phase 的落地）

**Learning Surface（学习边界）**为全文主轴：Phase 2.1 **只能学习参数**；参数学习**仅限白名单字段**；白名单必须来自**单一事实源**（B.4）；**禁止**修改：策略执行逻辑、风控核心逻辑、下单流程、幂等/去重/对账机制。上述约束必须体现在 B、A.2、E、F 中。

| 约束 | 在本 Phase 的落地 |
|------|------------------|
| **0.1 学习边界** | **必须落地**。**可修改**：仅限「可学习参数清单」（B.1），与策略配置 schema 对齐，白名单来自单一事实源（B.4）。**禁止修改**：策略执行逻辑与代码、风控核心逻辑与规则引擎、下单流程与幂等、信号接收/解析/路由、对账机制。默认 **Human-in-the-loop**；自动写回为可选且须**显式配置开启**并过 0.3 门禁。 |
| **0.2 Evaluator Contract** | **只读依赖，不得修改或削弱**。本 Phase **仅消费** Phase 2.0 的 evaluation_report 与可查询结果；**不**改变 Evaluator 输出 schema、**不**写入 evaluation_report、**不**写入 metrics_snapshot、**不**更改 Phase 2.0 指标口径。学习输入**只能**来自 2.0 评估结果（见 B.5）。 |
| **0.3 发布门禁与回滚** | **必须落地**。参数变更生效前须经门禁（人工确认或风控护栏）；写回路径 candidate→approved→active，**禁止**跳过 candidate 或审批；支持一键回滚到 stable；支持自动停用异常版本（B.2）。 |
| **0.4 决策输入快照** | **只读依赖**。本 Phase 不写入决策快照；若需读 1.2 决策快照仅用于展示或审计，不用于“自评估”或替代 2.0 评估。 |

### B.5 学习输入仅来自 Phase 2.0（写死，防第二套评估）

- **Optimizer / Learner 的输入只能为**：
  - Phase 2.0 的 **evaluation_report**（按 strategy_version_id、param_version_id、evaluated_at 查询）；
  - 以及与之关联的 strategy_version_id / param_version_id（用于版本对比与回滚目标）。
- **禁止**：
  - 直接扫描 Phase 1.2 的 **trade** 表重新计算指标；
  - 直接基于 **decision_snapshot** 做“私有评估”或自建评估结论；
  - 任何绕过 Phase 2.0 Evaluator 的“第二套评估系统”。
- **实现约束**：Optimizer/Learner 的接口入参中，评估数据**仅**接受「evaluation_report 的 ID 或查询结果集」，或由调用方传入已从 2.0 查询到的报告；**禁止**传入 trade/execution 原始表或 raw 查询权限用于“自己算指标”。验收须可验证：学习路径未直接读 trade 表做指标聚合、未用 decision_snapshot 产出评估结论。

### B.6 Phase 2.1 不得污染 Phase 2.0（写死）

- Phase 2.1 **不修改** evaluation_report（不 UPDATE/DELETE，不新增 2.0 语义字段）。
- Phase 2.1 **不写入** metrics_snapshot（指标计算与存储仅由 Phase 2.0 负责）。
- Phase 2.1 **不更改** Phase 2.0 的 schema 或指标口径（不扩展 2.0 表结构、不改变 B.2 口径语义）。
- Phase 2.1 **仅追加**：param_version 记录、release_audit、learning_audit、发布状态（candidate/approved/active/stable/disabled）等 **Phase 2.1 自有**表或字段；若与 2.0 共用 strategy_version 表，则**仅**在 2.1 侧扩展“状态”等 2.1 专属列或关联表，不改动 2.0 已定义的列语义。

---

### B.1 可学习参数清单与禁止修改项（写死）

以下为**必须在本交付包中显式列出**的键名（与当前策略配置 schema 一致，实现时与 B.4 事实源锁定）：

| 参数键 | 类型 | 说明 |
|--------|------|------|
| max_position_size | number | 最大持仓量 |
| fixed_order_size | number | 固定下单量 |
| stop_loss_pct | number | 止损比例 |
| take_profit_pct | number | 止盈比例 |
| （其他数值/枚举型可调参数） |  | 在实现时与策略配置 schema 对齐并补充列表；**仅**可学习参数清单内键可被 Optimizer 建议或写回 |

- **禁止修改项（不可变核心）**：除上表及 B.4 同源扩展白名单外的**所有**配置键；**策略执行逻辑与代码**；**风控核心逻辑与规则引擎**；**下单流程**（OrderManager/ExecutionEngine/交易所适配）；**幂等 / 去重 / 对账机制**；**信号接收 / 解析 / 路由**。Optimizer 与写回链路**禁止**写入或覆盖上述任何一项。
- **事实源与一致性**：见 **B.4**；本表与代码/schema **必须**一致，禁止文档与代码白名单不一致。

### B.2 异常条件与阈值（自动停用，写死）

**默认阈值**（保守默认值；以下均可通过配置覆盖，配置项在实现文档中列明）：

| 条件 | 默认阈值 | 配置键示例 | 说明 |
|------|----------|------------|------|
| 连续亏损笔数 | **5 笔** | auto_disable.consecutive_loss_trades | 同一 strategy 下连续 N 笔 trade 为亏损即触发 |
| 连续亏损金额 | **策略级 1 个名义单位或绝对值（如 1000）** | auto_disable.consecutive_loss_amount | 连续亏损累计超过 M 即触发；单位与实现一致 |
| 回撤超过 | **10%** | auto_disable.max_drawdown_pct | 当前周期内最大回撤超过该比例即触发 |
| 系统健康检查失败 | **DB/交易所/关键组件不可用** | 与 HealthChecker 一致 | 健康检查失败即触发 |

- **触发异常时的系统行为**（写死，三者均执行）：
  1. **停用**：当前生效版本（active）置为 **disabled**，该策略**不再接收新信号、不产生新决策**，直至人工恢复或回滚。
  2. **回滚**：若存在已标记为 **stable** 的版本，则**自动将当前生效版本回退到该 stable 版本**（即 active 指向该 stable），并写 release_audit（action=AUTO_DISABLE，并记录回滚目标）；若不存在 stable，则仅停用、不回滚目标。
  3. **告警**：**必须**触发强告警（高优先级），并写入 release_audit 与审计日志（含 strategy_id、触发条件、阈值、时间戳、回滚目标若有）。

---

### B.3 发布状态机 ReleaseGate（写死）

策略/参数版本在 ReleaseGate 下的**状态**、**允许/禁止行为**、**迁移条件**、**触发方**如下。实现时版本记录**必须**携带以下五态之一；**禁止**省略 approved 或合并为“门禁通过即 active”（必须先 approved 再 apply 为 active，或实现上合并但语义上等价“门禁通过→生效”且留审计）。

| 状态 | 含义 | 进入条件 | 退出条件 | 是否允许交易 | 允许行为 | 禁止行为 | 谁可触发迁移 |
|------|------|----------|----------|--------------|----------|----------|--------------|
| **candidate** | 学习产出的候选参数版本，待门禁 | submit_candidate 提交新 param_version（或参数快照） | 门禁通过 → **approved**；或被拒绝（保持 candidate 或标记拒绝，不进入 approved） | **否** | 被人工/规则审核、被拒绝 | 直接生效、直接写回策略运行时、接收交易信号 | 系统（Optimizer 产出后提交）；人工（提交候选） |
| **approved** | 人工或规则审批通过，待生效 | 人工 confirm_manual 或风控护栏 risk_guard 通过 | apply 生效 → **active**；或超时/撤销（回退为 candidate，按实现约定） | **否** | 被 apply 为 active、被撤销 | 直接接收交易信号、覆盖 stable | 人工（确认）；系统（风控规则通过） |
| **active** | 当前生效版本，允许交易 | approved 后执行 apply；或回滚后某 stable 被置为 active | 被回滚 → 该版本脱离 active，stable→active；或异常触发 → **disabled** | **是** | 接收新信号、产生新决策、被标记为 stable（人工） | 被任意覆盖、跳过门禁再次修改 | 系统（apply/回滚/异常处理）；人工（标记 stable） |
| **stable** | 历史稳定基线，回滚目标 | 人工标记当前 active 为 stable；或约定“运行满 N 周期无异常”后人工/自动标记 | 被新 stable 替代（策略维度通常仅保留一个当前 stable 或按策略约定）；状态可保留用于回滚 | **仅当同时为 active 时**允许交易；仅 stable 非 active **不允许**交易 | 作为回滚目标、被 rollback_to_stable 选为新的 active | 被学习结果或 candidate 覆盖、被直接改写参数 | 人工（标记 stable）；可选系统（按约定自动标记，若实现） |
| **disabled** | 被自动或人工停用 | 异常条件触发（B.2）后，原 active 置为 disabled | 不自动恢复；仅人工重新提交门禁或人工恢复流程（若实现） | **否** | 无（仅审计与恢复流程） | 接收信号、产生决策、被自动重新启用 | 系统（异常检测）；人工（若实现恢复） |

- **允许交易**的充要条件：当前策略的「生效版本」为 **active** 且非 disabled。candidate、approved、disabled、以及仅作回滚目标的 stable（非 active）**均不允许**接收新信号或产生新决策。
- **写回路径（写死）**：candidate → approved → active。**禁止**：跳过 candidate（学习结果直接写 active）；跳过 approved（未过门禁即生效）；覆盖 stable（不得把 stable 版本覆盖为新参数）。
- **回滚**：rollback_to_stable 将当前 active 置为「非生效」，将**上一 stable**（param_version）置为 **active**，并写 release_audit（action=ROLLBACK）。回滚粒度：**参数级**（回到 stable param_version），不涉及策略代码回滚（策略代码回滚不在 Phase 2.1 范围）。

---

### B.4 可学习参数白名单的事实源（写死）

- **白名单来源于哪个 schema / 配置文件**：**唯一事实源**为**代码中的策略配置 schema**（如 StrategyConfig 或等价 DTO/模型的字段定义，或经 CI/构建生成的 schema 文件）。交付包中的「可学习参数清单」表格（B.1）**必须**与该 schema 或由该 schema 导出的配置文件（如 `learnable_params.yaml` 或等价）**一致**；若使用独立配置文件，则**该文件必须由构建或部署流程从同一 schema 生成或校验**，禁止手写一份、代码一份两套来源。
- **白名单变更是否需要门禁与审计**：**需要**。可学习参数清单的变更（增删键）视为**策略/配置契约变更**，须经**与发布门禁同级的审批**（人工确认或变更流程），变更后须写审计记录（谁、何时、变更内容）；实现上可在 release_audit 或专用 config_change_audit 中记录。**禁止**在未经过门禁与审计的情况下修改白名单来源（schema 或生成后的配置文件）。
- **禁止文档白名单与代码白名单不一致**：**禁止**。本文档 B.1 表格与代码中实际用于 Optimizer/写回校验的白名单列表**必须**一致；实现须满足：要么代码在启动/测试时读取文档或与文档同源的配置并校验，要么文档由代码/schema 自动生成。验收时**必须**检查：文档所列键与代码中白名单集合一致（可通过测试或脚本比对）。

---

## C. 数据模型与 Schema

**约定**：Phase 2.1 **不**在 Phase 2.0 表上新增列或改 2.0 语义；仅新增或扩展 Phase 2.1 自有表/字段（param_version、release_audit、learning_audit、发布状态）。

### C.1 策略版本与 ReleaseGate 状态（Phase 2.1 扩展）

- 在 2.0 的 strategy_version/param_version 之上，或通过 strategy_runtime_state / param_version 关联表，需支持 **ReleaseGate 状态**（B.3）：**candidate | approved | active | stable | disabled**。至少一个字段表示当前状态（如 release_state）；若与 2.0 共用表，则**仅**在 2.1 侧扩展状态相关列，不改 2.0 已有列语义。
- 「上一稳定版本」回滚目标：即状态为 **stable** 的 param_version（若有多个则按策略约定取最新或指定一个）；回滚后将该 stable 置为 active，原 active 脱离生效。
- 版本生效/生效历史：effective_from、replaced_at 等可选，供门禁与回滚查询；写回对象**仅**为 **param_version**（不直接改写 strategy_version 的策略逻辑或非白名单配置）。

### C.2 发布/门禁/回滚审计（release_audit，Phase 2.1 自有）

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | BIGINT/UUID | PK | 主键 |
| strategy_id | string | NOT NULL | 策略标识 |
| param_version_id | string | NOT NULL | 本次操作涉及的参数版本（写回仅针对 param_version） |
| action | enum | NOT NULL | APPLY \| ROLLBACK \| AUTO_DISABLE \| SUBMIT_CANDIDATE \| REJECT |
| gate_type | enum | NULLABLE | MANUAL \| RISK_GUARD；门禁通过时记录 |
| passed | boolean | NULLABLE | 是否通过（拒绝时为 false） |
| operator_or_rule_id | string | NULLABLE | 人工操作员 ID 或规则/风控 ID |
| created_at | timestamptz | NOT NULL | 操作时间 |
| payload | JSONB | NULLABLE | 触发条件、阈值、回滚目标等扩展信息 |

- 每次 submit_candidate、confirm_manual/apply、rollback_to_stable、自动停用**必须**写入一条 release_audit；**禁止**绕过审计的写回或状态变更。

### C.3 学习/优化审计（learning_audit，Phase 2.1 自有，可选但推荐）

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | BIGINT/UUID | PK | 主键 |
| strategy_id | string | NOT NULL | 策略标识 |
| evaluation_report_id | string | NULLABLE | 本次学习所依据的 Phase 2.0 evaluation_report 的 ID（**仅读 2.0，不写 2.0**） |
| param_version_id_candidate | string | NULLABLE | 产出的候选 param_version |
| suggested_params | JSONB | NULLABLE | 白名单内参数建议（仅白名单键） |
| created_at | timestamptz | NOT NULL | 产出时间 |

- 用于追溯「学习输入来自哪份 2.0 报告」；**禁止**在此表或任何 2.1 表写入 Phase 2.0 的 evaluation_report 或 metrics_snapshot 内容（仅存 ID 或引用）。

### C.4 写回规则（工程级可验证，写死）

- **写回对象**：**只能是 param_version**（参数版本），**不能是 strategy_version**（策略逻辑版本）。即：学习结果仅生成新的 param_version 或更新参数快照，不修改 strategy_version 的代码或非白名单配置。
- **写回路径**：candidate → approved → active。**禁止**：跳过 candidate（学习结果直接写 active）；跳过审批（未过门禁即生效）；覆盖 stable（不得把已标记 stable 的版本覆盖为新参数）。
- **自动写回**：默认**关闭**；须通过配置显式开启（如 `auto_apply_after_gate=false` 为默认）；若开启，仍须经门禁（人工或风控护栏）通过后方可 apply；**必须**有审计记录（release_audit）。

---

## D. 接口与边界

**边界**：Phase 2.1 **不修改、不写入** Phase 2.0 的 evaluation_report、metrics_snapshot，不更改 2.0 schema 或口径；学习输入**仅**来自 2.0 评估结果（B.5）；写回**仅**为 param_version，路径 candidate→approved→active（C.4）。

### D.1 Optimizer / Learner（仅白名单参数，输入仅来自 Phase 2.0）

- **输入**：**只能**为 Phase 2.0 的 **evaluation_report**（或 report 的 ID/查询结果集）及关联的 strategy_version_id/param_version_id；**禁止**传入 trade/execution/decision_snapshot 用于“自评估”或重算指标。
- **输出**：ParamSuggestion（**仅**白名单内键的建议值）；不写回，除非显式配置开启且经门禁后写入 param_version。

```text
Optimizer.suggest(strategy_id, evaluation_report_ids[] | evaluation_period, param_space) -> ParamSuggestion
# evaluation_report_ids 或 period：仅允许从 Phase 2.0 查询得到的 evaluation_report；禁止传入 trade 表或 raw 指标
# param_space：仅允许 B.1 可学习参数清单内的键；否则拒绝或过滤
# ParamSuggestion：白名单内参数的建议值；不写回，除非显式启用并过门禁（见 D.3）
# 实现必须禁止：直接扫描 trade 表、基于 decision_snapshot 产出评估结论

Optimizer.backtest(strategy_id, params, period) -> BacktestReport  # 可选；params 仅限白名单键
```

### D.2 实盘反馈与评估触发（仅触发 2.0，不写 2.0）

- 实盘 trade/decision 由 **Phase 2.0** 的 MetricsCalculator/Evaluator 消费（2.0 能力）；Phase 2.1 仅**触发**评估或**读取** 2.0 的评估结果，**不**写入 metrics_snapshot 或 evaluation_report。

```text
SchedulerOrTrigger.evaluate_on_schedule(strategy_id, cron_or_interval) -> void
# 触发 Phase 2.0 执行评估；评估结果存于 2.0 表，2.1 仅只读查询
# 基于评估结果的参数更新：2.1 读 2.0 报告 → 产出建议 → 提交 candidate → 经门禁 → approved → active
```

### D.3 发布门禁与回滚（0.3）

**状态机**：遵守 B.3。版本状态为 candidate | approved | active | stable | disabled；**仅 active** 允许交易。写回路径：candidate → approved → active；**禁止**跳过 candidate 或审批。

```text
ReleaseGate.submit_candidate(strategy_id, param_version_id_or_param_snapshot) -> GateResult
# 提交后该 param_version 状态为 candidate；GateResult: requires_manual_confirm | risk_guard_passed | rejected
# 写 release_audit（action=SUBMIT_CANDIDATE）

ReleaseGate.confirm_manual(strategy_id, param_version_id, operator_id) -> ApplyResult
# 人工确认后 candidate→approved；可选：同调用中 approved→active（apply），或分步 apply
# 写 release_audit（action=APPLY, gate_type=MANUAL）

ReleaseGate.apply_approved(strategy_id, param_version_id) -> ApplyResult
# approved → active，写 release_audit；仅当当前状态为 approved 时可调用

ReleaseGate.rollback_to_stable(strategy_id) -> RollbackResult
# 当前 active 脱离，上一 stable（param_version）→ active；写 release_audit（action=ROLLBACK）
# 无 stable 时返回 409 或等价错误

ReleaseGate.get_current_and_stable(strategy_id) -> (current_param_version_id, current_state, stable_param_version_id?)
# current_state 为 active|disabled|candidate|approved|stable；用于判断是否允许交易；无 stable 时 stable_param_version_id 为 null
```

- **自动停用**：后台检测 B.2 条件，触发时当前 active→disabled；若有 stable 则自动回滚到 stable（stable→active），写 release_audit（action=AUTO_DISABLE）+ 强告警。
- 错误码：403 未过门禁、404 版本不存在、409 无稳定版本可回滚等。

---

## E. 任务拆分

每项任务均给出**输入（表/接口）**、**输出（表/状态）**、**可验证断言**；验收须覆盖：**人工确认路径**、**自动写回关闭**、**自动写回开启但被门禁拦截**、**异常触发后自动回滚**。

| 任务编号 | 目的 | 输入（表/接口） | 输出（表/状态） | 实现要点 | 可验证断言（验收 checkbox） | 交付物 |
|----------|------|-----------------|-----------------|----------|-----------------------------|--------|
| **T2.1-1** | Optimizer（仅白名单，输入仅 2.0） | Phase 2.0 evaluation_report（ID 或查询结果）；strategy_id；param_space（仅 B.1 白名单键） | ParamSuggestion（白名单内键）；可选 learning_audit 一条 | **输入仅来自 2.0**：禁止传入 trade/execution/decision_snapshot 做自评估；param_space 仅限 B.4 事实源白名单；默认不写回 | [ ] 入参仅接受 evaluation_report 或 period，无 trade 表/raw 指标入参；[ ] 产出建议仅含 B.1 白名单键，抽检无越权键；[ ] **白名单事实源**：Optimizer 使用的白名单与 B.4 一致（代码与文档或同源配置）；[ ] **人工路径**：默认不写回，仅产出建议；若开启自动写回则须经门禁（T2.1-4）；[ ] Phase 2.0 未被写：未写入 evaluation_report/metrics_snapshot | Optimizer 实现、可学习参数清单（与 schema 同源或可校验） |
| **T2.1-2** | 实盘反馈与评估闭环 | 触发配置（cron/间隔）；strategy_id；Phase 2.0 只读查询 API | 触发 2.0 评估；2.0 产出 evaluation_report；2.1 可读报告并驱动「建议→candidate→门禁→生效」 | 实盘数据由 2.0 消费；2.1 仅触发评估与读取 2.0 报告；至少一次「读 2.0 报告→参数更新（白名单）→经门禁生效」 | [ ] 实盘可持续驱动 2.0 指标与评估（2.0 能力）；[ ] 可配置评估周期；[ ] 至少一次基于 2.0 评估结果的参数更新经门禁生效；[ ] **人工确认路径**：参数更新经 submit_candidate + confirm_manual/apply，有 release_audit；[ ] 2.1 未写 2.0 表 | 实盘反馈与触发链路、评估与更新流程文档 |
| **T2.1-4** | 发布门禁与回滚 | ReleaseGate 接口；strategy_id；param_version_id；operator_id（人工）；B.2 异常条件 | release_state（candidate/approved/active/stable/disabled）；release_audit 记录；回滚后 active=stable | **状态机 B.3** 五态；仅 active 允许交易；写回路径 candidate→approved→active；一键回滚到 stable；B.2 异常触发停用+回滚+告警 | [ ] **人工确认**：submit_candidate 后须 confirm_manual 或 risk_guard 通过才能 approved→active；有 release_audit；[ ] **自动写回关闭**：默认配置下学习结果不自动生效，仅 candidate；[ ] **自动写回开启但被门禁拦截**：若配置自动 apply，门禁未过时 candidate 不转为 approved/active，可验证；[ ] **异常触发回滚**：模拟满足 B.2（如连续亏损 5 笔或回撤 10%），当前 active→disabled，若有 stable 则 stable→active，release_audit 含 AUTO_DISABLE，强告警；[ ] 回滚可执行且 release_audit 含 ROLLBACK；[ ] 状态机五态可区分，仅 active 时策略可接收信号 | 门禁与回滚实现、B.2 阈值配置、状态机说明 |
| **T2.1-3** | Shadow/Simulator/Promotion/Elimination（按需） | 占位 | 按需 | 若资源允许可细化；否则不交付 | [ ] 若纳入则按本包该部分验收；否则不要求 | 按需 |

### E.1 闭环验收任务（强制）

| 任务编号 | 目的 | 输入 | 输出 | 可验证断言 |
|----------|------|------|------|------------|
| **T2.1-E2E** | 至少一次完整闭环 | strategy_id、时间范围、2.0 已就绪 | 新 evaluation_report 可查、release_audit 可查、回滚后 active=stable | 执行评估(2.0)→读 2.0 报告→产出建议(2.1-1)→submit_candidate→confirm_manual/apply→新版本 active→再评估并查询到新报告；执行一次 rollback_to_stable，验证回滚记录与当前 active 为原 stable |

---

## F. 测试与验收

### F.1 端到端用例

- **E2E-2.1（主流程）**  
  - 步骤：执行评估(2.0) → 读取 2.0 evaluation_report → Optimizer.suggest（**仅**以报告为输入）→ 产出白名单参数建议 → submit_candidate → confirm_manual（或 risk_guard）→ approved → apply → active → 再次执行评估(2.0)并查询到新报告。  
  - 验证：新报告存在且与当前 active param_version 关联；release_audit 含 SUBMIT_CANDIDATE、APPLY；**学习输入仅来自 2.0**（无 trade 表/自评估路径）；写回对象仅为 param_version。

- **E2E-2.1-人工确认路径**  
  - 步骤：submit_candidate 后**不**调用 confirm_manual；或门禁配置为必须人工。  
  - 验证：candidate **不**自动变为 approved/active；仅在人工 confirm_manual（或等价）后 approved→active；release_audit 含 operator 或 gate_type=MANUAL。

- **E2E-2.1-自动写回关闭**  
  - 步骤：默认配置（自动写回关闭）；Optimizer 产出建议后若存在“自动 apply”逻辑则关闭。  
  - 验证：学习结果仅落为 candidate 或建议，**不**自动变为 active；需显式 confirm_manual/apply 后生效。

- **E2E-2.1-自动写回开启但被门禁拦截**  
  - 步骤：配置自动写回开启；风控护栏或人工拒绝该 candidate（或模拟门禁不通过）。  
  - 验证：candidate **不**转为 approved/active；release_audit 有拒绝或未通过记录；当前 active 保持不变。

- **E2E-2.1-Rollback**  
  - 步骤：当前 active 为 A，存在 stable B；调用 rollback_to_stable。  
  - 验证：当前生效为 B（stable→active）；A 脱离 active；release_audit 含 action=ROLLBACK。

- **E2E-2.1-AutoDisable（异常触发回滚）**  
  - 步骤：模拟满足 B.2 异常条件（如连续亏损 5 笔或回撤 10%），触发自动停用。  
  - 验证：原 active→disabled；若有 stable 则 stable→active；release_audit 含 action=AUTO_DISABLE；强告警已触发；策略不再接收新信号直至人工恢复或回滚。

### F.2 回归清单

- Phase 2.0 评估与查询仍可用；Phase 1.2 追溯与决策快照只读无回归。
- **学习输入仅来自 2.0**：Optimizer 未直接读 trade 表做指标、未用 decision_snapshot 做私有评估；可通过接口约束与测试验证。
- **ReleaseGate 状态机**（B.3）：candidate/approved/active/stable/disabled 五态已实现，**仅 active** 允许交易；状态转换与回滚、异常停用行为可验证。
- **可学习参数白名单事实源**（B.4）：文档与代码白名单一致已验收；白名单变更须门禁与审计；Optimizer 未写入白名单外键（可通过审计或测试验证）。
- **Phase 2.0 不被污染**：Phase 2.1 未写入 evaluation_report、metrics_snapshot，未更改 2.0 schema 或口径。

### F.3 禁止进入后续 Phase 的失败情形（验收不通过即禁止）

以下任一条成立则**禁止**进入后续 Phase（如完整智能 BI 或更高级学习），须在 Phase 2.1 内修复并重新验收：

- 学习结果可绕过评估直接上线（未以 2.0 evaluation_report 为唯一学习输入，或未经 candidate→门禁→active）。
- 无法回滚（无 stable 标记或 rollback_to_stable 不可用、无 release_audit 记录）。
- 白名单参数被越权修改（建议或写回中出现白名单外键，或白名单事实源与文档不一致）。
- 发布状态不可追溯（release_audit 缺失或状态迁移无记录、五态不可区分）。
- Phase 2.0 被污染（2.1 写入了 evaluation_report/metrics_snapshot 或修改了 2.0 口径/schema）。

---

## G. 风险与非功能性要求

- **安全**：人工确认需可追溯操作员或会话（operator_id 或等价）；自动写回**仅在显式配置开启且过门禁**时执行；**禁止**绕过门禁或审计的实现（如“后台自动 apply 且不写 release_audit”）。
- **审计**：所有 submit_candidate、门禁通过/拒绝、回滚、自动停用**必须**写 release_audit；**禁止**存在可生效但无审计记录的代码路径。
- **回滚**：回滚后立即生效（stable→active），无中间态丢失；若实现上需“回滚后经同一门禁再生效”，则须在交付包中写死并验收。
- **实现选择（写死）**：若存在多种实现方式，采用**最保守、最可控、最易回滚**的一种；例如：默认不自动写回；门禁未过时 candidate 绝不转为 active；异常触发时先停用再回滚，再告警；学习输入仅接受 2.0 报告 ID 或查询结果，不在 2.1 内开放 trade 表写或“自评估”路径。
- **熔断**：异常条件触发后系统必须可自动停用并回到稳定态（stable）；无 stable 时仅停用、不回滚目标，且告警中明确说明“无稳定版本可回滚”。

---

## H. 交付物清单

| 类别 | 交付物 |
|------|--------|
| **代码/配置** | Optimizer/Learner（**仅**读 2.0 evaluation_report，白名单约束、与 B.4 同源）；实盘反馈与评估触发链路（仅触发 2.0、读 2.0 报告）；ReleaseGate（门禁、candidate→approved→active、一键回滚、自动停用）；release_audit、learning_audit（可选）表与写入；B.2 异常条件与默认阈值配置；**禁止**写入 Phase 2.0 表的约束落点。 |
| **文档** | 可学习参数清单（与策略 schema 同源或可校验，B.4）；禁止修改项清单（B.1）；学习输入仅来自 2.0 的接口说明（B.5）；异常条件与阈值及默认值（B.2）；ReleaseGate 五态状态机（B.3）；写回规则（仅 param_version、candidate→approved→active、自动写回默认关闭）（C.4）；评估触发与更新流程；门禁与回滚使用说明。 |
| **证据** | 至少一次完整闭环（评估(2.0)→读报告→建议→candidate→门禁→上线→再评估）的执行与查询证据；一次回滚操作及 release_audit 证据；人工确认路径与自动写回关闭/门禁拦截的验收证据。 |

---

**文档结束**
