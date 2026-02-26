# Phase 2.1 模块化开发交付包

**版本**: v1.0.0  
**创建日期**: 2026-02-07  
**最后修订**: 2026-02-07  
**基于**: Phase2.1 开发蓝本（系统宪法，不可改写语义）

---

## 一、推荐执行顺序（强制）

以下顺序为 Cursor/开发者的**推荐执行顺序**，不可调整。开发项必须按此顺序实施，以降低依赖冲突与返工风险。

| 步骤 | 开发项 | 说明 |
|------|--------|------|
| 1 | A1 / A2 / A3 | 数据库迁移（ReleaseGate 状态扩展、release_audit、learning_audit，可并行或按 A1→A2→A3 顺序） |
| 2 | B1 | 可学习参数白名单事实源（B.4：单一事实源、与 schema 同源、文档与代码一致） |
| 3 | C1 | 学习输入只读边界（仅读 Phase2.0 evaluation_report，禁止 trade/decision_snapshot 自评估） |
| 4 | C2 | Optimizer/Learner（仅白名单参数建议，输入仅 2.0 报告，默认不写回） |
| 5 | C3 | 实盘反馈与评估触发（仅触发 2.0 评估、只读 2.0 报告，不写 2.0 表） |
| 6 | B2 | ReleaseGate 状态机（B.3：五态、写回路径 candidate→approved→active、仅 active 允许交易） |
| 7 | B3 | 发布门禁与写回（submit_candidate、confirm_manual、apply_approved、release_audit 必写） |
| 8 | B4 | 一键回滚（rollback_to_stable、参数级回滚到 stable、release_audit 含 ROLLBACK） |
| 9 | B5 | 自动停用与异常回滚（B.2 条件与阈值、active→disabled、回滚到 stable、强告警+审计） |
| 10 | C4 | 写回规则与审计（仅 param_version、禁止覆盖 stable、自动写回默认关闭） |
| 11 | D1～D6 | 端到端与回归可验证点（E2E-2.1、人工确认、自动写回关闭/门禁拦截、Rollback、AutoDisable、回归清单） |
| 12 | D7-D8 | 技术债专项修复（ALARM/PERF 专项） |

### 模块级执行规则（强制）

1. Phase2.1 的开发必须严格按模块逐一推进。
2. 任一时刻，只允许存在 **一个「活跃开发模块」**。
3. 当正在开发某一模块时：
   - 禁止修改、实现、重构任何非本模块定义范围内的代码；
   - 禁止提前实现后续模块的任何逻辑；
   - 禁止为「后续模块方便」而预埋代码、接口或占位实现。
4. 当前模块在 **未通过验收** 前，不得进入下一模块。
5. 若某模块验收失败，只允许在该模块范围内返工，不得牵连其他模块。

---

## 二、开发项与交付

### A. 数据库迁移（Migrations）

#### A1. ReleaseGate 状态扩展（param_version / strategy_runtime_state，Phase 2.1 扩展）

**模块目标（Goal）**  
- 在 Phase 2.0 的 strategy_version/param_version 之上支持 **ReleaseGate 状态**（B.3）：candidate | approved | active | stable | disabled；为「仅 active 允许交易」与回滚目标提供存储基础。

**开发范围（Scope）**  
- 在 param_version 或 strategy_runtime_state / param_version 关联表上，**仅**在 Phase 2.1 侧扩展状态相关列（如 release_state）；**禁止**修改 Phase 2.0 已有列语义。  
- 至少一个字段表示当前状态（如 release_state）；可选 effective_from、replaced_at 等供门禁与回滚查询。  
- 迁移脚本：仅新增 Phase 2.1 自有列或关联表，**禁止**修改 evaluation_report、metrics_snapshot 及 Phase 2.0 表结构或指标口径。

**输入 / 输出**  
- 输入：无（迁移无业务输入）。  
- 输出：param_version 或关联表上的 release_state（及可选时间字段）；为 B2、B3、B4、B5 提供状态存储。

**强制约束（Strong Constraints）**  
- Phase 2.1 **不修改** Phase 2.0 的 schema 或已有列语义；**不**在 evaluation_report、metrics_snapshot 上新增列。  
- 写回对象**仅**为 param_version（不直接改写 strategy_version 的策略逻辑或非白名单配置）；本迁移仅扩展 2.1 自有状态字段。  
- 迁移必须支持 alembic upgrade/downgrade，不破坏已有表。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行（upgrade/downgrade 无报错，幂等）。  
- [ ] 表中存在 release_state 或等价字段，可存储 candidate/approved/active/stable/disabled 五态之一。  
- [ ] 文档或注释明确本扩展为 Phase 2.1 自有，未改动 Phase 2.0 表语义。

**绑定说明**  
本模块覆盖蓝本 C.1 策略版本与 ReleaseGate 状态扩展；为 B2、B3、B4、B5 提供表结构基础。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### A2. release_audit 表（发布/门禁/回滚审计，Phase 2.1 自有）

**模块目标（Goal）**  
- 为每次 submit_candidate、门禁通过/拒绝、apply、rollback、自动停用提供不可绕过审计；满足蓝本 C.2 字段与约束。

**开发范围（Scope）**  
- 新增表 `release_audit`，字段与约束严格按蓝本 C.2：  
  - id（BIGINT/UUID, PK）、strategy_id（string, NOT NULL）、param_version_id（string, NOT NULL）、action（enum: APPLY | ROLLBACK | AUTO_DISABLE | SUBMIT_CANDIDATE | REJECT, NOT NULL）、gate_type（enum: MANUAL | RISK_GUARD, NULLABLE）、passed（boolean, NULLABLE）、operator_or_rule_id（string, NULLABLE）、created_at（timestamptz, NOT NULL）、payload（JSONB, NULLABLE）。  
  - 索引：按 strategy_id、created_at 等查询需求。  
- 迁移脚本：仅建表与索引，**禁止**修改 Phase 2.0 表。

**输入 / 输出**  
- 输入：无（迁移无业务输入）。  
- 输出：表 `release_audit` 及索引；为 B3、B4、B5 及 D 系列提供审计存储。

**强制约束（Strong Constraints）**  
- 本表为 Phase 2.1 自有表；Phase 2.1 **不写入** evaluation_report、metrics_snapshot；**不更改** Phase 2.0 schema 或指标口径。  
- 每次 submit_candidate、confirm_manual/apply、rollback_to_stable、自动停用**必须**写入一条 release_audit；**禁止**绕过审计的写回或状态变更（该约束在 B3、B4、B5 模块中再次落实）。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行且可回滚。  
- [ ] 表中存在 C.2 全部字段及必要索引。  
- [ ] 文档明确 action 枚举及「每次写回/门禁/回滚/停用必写」的约定。

**绑定说明**  
本模块覆盖蓝本 C.2；为 B3、B4、B5 及 E2E-2.1、E2E-2.1-Rollback、E2E-2.1-AutoDisable 提供审计基础。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### A3. learning_audit 表（学习/优化审计，Phase 2.1 自有，可选但推荐）

**模块目标（Goal）**  
- 追溯「学习输入来自哪份 Phase 2.0 evaluation_report」；仅存 ID 或引用，**禁止**在此表或任何 2.1 表写入 Phase 2.0 的 evaluation_report 或 metrics_snapshot 内容。

**开发范围（Scope）**  
- 新增表 `learning_audit`，字段与约束严格按蓝本 C.3：  
  - id（BIGINT/UUID, PK）、strategy_id（string, NOT NULL）、evaluation_report_id（string, NULLABLE）、param_version_id_candidate（string, NULLABLE）、suggested_params（JSONB, NULLABLE）、created_at（timestamptz, NOT NULL）。  
  - evaluation_report_id 仅存 Phase 2.0 evaluation_report 的 ID；suggested_params 仅白名单内键。  
- 迁移脚本：仅建表及必要索引，**禁止**修改 Phase 2.0 表。

**输入 / 输出**  
- 输入：无（迁移无业务输入）。  
- 输出：表 `learning_audit`；为 C2 Optimizer 产出追溯提供存储（可选）。

**强制约束（Strong Constraints）**  
- Phase 2.1 **不写入** evaluation_report、**不写入** metrics_snapshot；本表**仅**存 evaluation_report_id 或引用，**禁止**存储 2.0 报告内容或指标快照。  
- suggested_params 若存在则**仅**含 B.1/B.4 白名单内键；**禁止**越权键。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行且可回滚。  
- [ ] 表中存在 C.3 全部字段；evaluation_report_id 为引用型，无 2.0 报告内容存储。  
- [ ] 文档明确「仅存 ID、不存 2.0 内容」的边界。

**绑定说明**  
本模块覆盖蓝本 C.3；与 T2.1-1 可选 learning_audit 衔接。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

### B. 白名单与发布门禁（危险能力单独成模块）

#### B1. 可学习参数白名单事实源（B.4）

**模块目标（Goal）**  
- 确立可学习参数清单的**单一事实源**（代码中的策略配置 schema 或由其生成的配置文件）；交付包中「可学习参数清单」与禁止修改项**必须**与该事实源一致；白名单变更须门禁与审计。

**开发范围（Scope）**  
- **事实源定义**：唯一事实源为代码中的策略配置 schema（如 StrategyConfig 或等价 DTO/模型字段定义），或经 CI/构建生成的 schema 文件；若使用独立配置文件（如 learnable_params.yaml），则该文件**必须**由同一 schema 生成或校验，**禁止**手写一份、代码一份两套来源。  
- **可学习参数清单（B.1）**：在交付包中显式列出与 schema 一致的键名（如 max_position_size、fixed_order_size、stop_loss_pct、take_profit_pct 等）；**仅**该清单内键可被 Optimizer 建议或写回。  
- **禁止修改项清单**：显式列出除白名单外的所有不可变核心（策略执行逻辑、风控核心、下单流程、幂等/去重/对账、信号接收/解析/路由等）；Optimizer 与写回链路**禁止**写入或覆盖上述任何一项。  
- **白名单变更**：可学习参数清单的增删键视为策略/配置契约变更，须经与发布门禁同级的审批，变更后须写审计记录（release_audit 或 config_change_audit）。

**输入 / 输出**  
- 输入：策略配置 schema 或由 schema 生成/校验的配置文件。  
- 输出：交付包中的可学习参数清单表、禁止修改项清单、事实源说明文档；为 C2、B3、C4 提供校验依据。

**强制约束（Strong Constraints）**  
- **禁止**文档白名单与代码白名单不一致：本文档 B.1 表格与代码中实际用于 Optimizer/写回校验的白名单列表**必须**一致；实现须满足：要么代码在启动/测试时读取与文档同源的配置并校验，要么文档由代码/schema 自动生成。  
- 验收时**必须**检查：文档所列键与代码中白名单集合一致（可通过测试或脚本比对）。  
- 学习结果与写回**仅限白名单参数**；写回对象**只能是 param_version**；**禁止**修改策略执行逻辑、风控核心、下单流程、幂等/对账机制。

**验收口径（Acceptance Criteria）**  
- [ ] 可学习参数清单表格与策略配置 schema（或同源配置）一致，已文档化。  
- [ ] 禁止修改项清单已显式列出，Optimizer/写回链路无写入或覆盖上述项。  
- [ ] 白名单事实源已明确（schema 或生成文件路径），文档与代码/配置一致。  
- [ ] 验收可验证：文档所列键与代码中白名单集合一致（测试或脚本比对通过）。  
- [ ] 白名单变更流程已约定（门禁+审计）。

**绑定说明**  
本模块覆盖蓝本 B.1、B.4；对应 T2.1-1 中「白名单事实源：Optimizer 使用的白名单与 B.4 一致」。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### B2. ReleaseGate 状态机（B.3）

**模块目标（Goal）**  
- 实现策略/参数版本在 ReleaseGate 下的五态（candidate | approved | active | stable | disabled）、各状态允许/禁止行为、迁移条件、触发方；**仅 active 允许交易**；写回路径**仅**为 candidate → approved → active，**禁止**跳过 candidate 或审批、**禁止**覆盖 stable。

**开发范围（Scope）**  
- **状态定义与存储**：版本记录**必须**携带五态之一；状态存储使用 A1 扩展的 release_state（或等价）。  
- **状态语义（写死）**：  
  - **candidate**：学习产出的候选参数版本，待门禁；**不允许**交易；进入条件 submit_candidate；退出条件门禁通过→approved 或被拒绝。  
  - **approved**：人工或规则审批通过，待生效；**不允许**交易；进入条件 confirm_manual 或 risk_guard 通过；退出条件 apply→active 或撤销。  
  - **active**：当前生效版本；**允许**接收新信号、产生新决策；进入条件 approved 后 apply 或回滚后 stable→active；退出条件被回滚或异常→disabled。  
  - **stable**：历史稳定基线，回滚目标；**仅当同时为 active 时**允许交易；**禁止**被学习结果或 candidate 覆盖。  
  - **disabled**：被自动或人工停用；**不允许**交易。  
- **允许交易的充要条件**：当前策略的「生效版本」为 **active** 且非 disabled。candidate、approved、disabled、以及仅作回滚目标的 stable（非 active）**均不允许**接收新信号或产生新决策。  
- **写回路径（写死）**：candidate → approved → active；**禁止**跳过 candidate、跳过 approved、覆盖 stable。

**输入 / 输出**  
- 输入：param_version 及 A1 状态字段；查询请求（如 get_current_and_stable）。  
- 输出：当前状态、stable 版本标识；为 B3、B4、B5 及交易入口提供「是否允许交易」判定依据。

**强制约束（Strong Constraints）**  
- **仅 active 允许交易**：candidate、approved、disabled、仅 stable 非 active **均不允许**接收新信号或产生新决策；实现与交易入口必须按 release_state 判定。  
- 写回路径**仅** candidate → approved → active；**禁止**学习结果直接写 active、**禁止**未过门禁即生效、**禁止**覆盖已标记 stable 的版本。  
- Phase 2.1 **不修改** evaluation_report、**不写入** metrics_snapshot、**不更改** Phase 2.0 schema 或指标口径。

**验收口径（Acceptance Criteria）**  
- [ ] 五态可区分，状态迁移条件与触发方符合 B.3 表。  
- [ ] 仅当 release_state=active 时策略可接收信号/产生决策；其他状态不可。  
- [ ] 写回路径仅 candidate→approved→active，无跳过 candidate/approved 或覆盖 stable 的代码路径。  
- [ ] get_current_and_stable(strategy_id) 可返回 current_param_version_id、current_state、stable_param_version_id（无 stable 时为 null）。

**绑定说明**  
本模块覆盖蓝本 B.3、C.4 写回路径；对应 T2.1-4、E2E-2.1、E2E-2.1-人工确认路径、E2E-2.1-自动写回关闭、E2E-2.1-自动写回开启但被门禁拦截、E2E-2.1-Rollback、E2E-2.1-AutoDisable。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### B3. 发布门禁与写回（submit_candidate、confirm_manual、apply_approved、release_audit）

**模块目标（Goal）**  
- 实现 ReleaseGate.submit_candidate、confirm_manual、apply_approved；每次操作**必须**写 release_audit；写回对象**仅**为 param_version；自动写回默认关闭，显式配置开启后仍须经门禁。

**开发范围（Scope）**  
- **ReleaseGate.submit_candidate(strategy_id, param_version_id_or_param_snapshot) -> GateResult**：提交后该 param_version 状态为 candidate；写 release_audit（action=SUBMIT_CANDIDATE）；GateResult 含 requires_manual_confirm | risk_guard_passed | rejected。  
- **ReleaseGate.confirm_manual(strategy_id, param_version_id, operator_id) -> ApplyResult**：人工确认后 candidate→approved；写 release_audit（action=APPLY, gate_type=MANUAL）；可选同调用中 approved→active（apply）或分步 apply。  
- **ReleaseGate.apply_approved(strategy_id, param_version_id) -> ApplyResult**：approved → active；**仅当**当前状态为 approved 时可调用；写 release_audit。  
- **写回对象**：**仅** param_version；**禁止**写 strategy_version 的策略逻辑或非白名单配置。  
- **自动写回**：默认**关闭**；须通过配置显式开启（如 auto_apply_after_gate=false 为默认）；若开启，仍须经门禁通过后方可 apply；**必须**有 release_audit 记录。  
- 错误码：403 未过门禁、404 版本不存在等。

**输入 / 输出**  
- 输入：strategy_id、param_version_id 或参数快照、operator_id（人工）；Phase 2.0 只读（不写）。  
- 输出：GateResult/ApplyResult；release_audit 表新增记录；param_version 的 release_state 更新。

**强制约束（Strong Constraints）**  
- 写回对象**仅**为 param_version；**禁止**写 strategy_version。  
- 写回路径**仅** candidate → approved → active；**禁止**跳过 candidate、跳过审批、覆盖 stable。  
- 每次 submit_candidate、confirm_manual、apply**必须**写入 release_audit；**禁止**存在可生效但无审计记录的代码路径。  
- Phase 2.1 **不写入** evaluation_report、metrics_snapshot；**不更改** Phase 2.0 schema 或指标口径。

**验收口径（Acceptance Criteria）**  
- [ ] submit_candidate 后状态为 candidate，且 release_audit 含 SUBMIT_CANDIDATE。  
- [ ] confirm_manual 后 candidate→approved，release_audit 含 APPLY、gate_type=MANUAL（或等价）。  
- [ ] apply_approved 仅在状态为 approved 时可调用，执行后为 active，release_audit 有记录。  
- [ ] 默认配置下无自动 apply（自动写回关闭）；若开启自动写回，门禁未过时 candidate 不转为 approved/active。  
- [ ] 写回仅针对 param_version，未改写 strategy_version 或非白名单配置。

**绑定说明**  
本模块覆盖蓝本 D.3、C.4；对应 T2.1-4、E2E-2.1、E2E-2.1-人工确认路径、E2E-2.1-自动写回关闭、E2E-2.1-自动写回开启但被门禁拦截。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### B4. 一键回滚（rollback_to_stable）

**模块目标（Goal）**  
- 实现 ReleaseGate.rollback_to_stable(strategy_id)；当前 active 脱离，上一 stable（param_version）→ active；写 release_audit（action=ROLLBACK）；回滚粒度为**参数级**（回到 stable param_version），不涉及策略代码回滚。

**开发范围（Scope）**  
- **ReleaseGate.rollback_to_stable(strategy_id) -> RollbackResult**：当前 active 置为「非生效」，将状态为 **stable** 的 param_version 置为 **active**；写 release_audit（action=ROLLBACK）；无 stable 时返回 409 或等价错误。  
- **ReleaseGate.get_current_and_stable(strategy_id) -> (current_param_version_id, current_state, stable_param_version_id?)**：用于判断是否允许交易及回滚目标；无 stable 时 stable_param_version_id 为 null。  
- 回滚粒度：**参数级**（回到 stable param_version）；策略代码回滚不在 Phase 2.1 范围。

**输入 / 输出**  
- 输入：strategy_id；当前 active、stable 状态来自 A1/B2。  
- 输出：RollbackResult；release_audit 新增 action=ROLLBACK；param_version 的 release_state 更新。

**强制约束（Strong Constraints）**  
- 回滚**必须**写 release_audit（action=ROLLBACK）；**禁止**无审计回滚。  
- 仅当存在 stable param_version 时可执行回滚；无 stable 时返回 409 或等价，不得静默失败或改写非 stable 版本为 active。  
- Phase 2.1 **不修改** evaluation_report、**不写入** metrics_snapshot。

**验收口径（Acceptance Criteria）**  
- [ ] 存在 stable 时，rollback_to_stable 执行后当前生效为原 stable（stable→active），原 active 脱离；release_audit 含 action=ROLLBACK。  
- [ ] 无 stable 时调用返回 409 或约定错误码，无状态错误变更。  
- [ ] get_current_and_stable 返回的 current_state、stable_param_version_id 与执行结果一致。

**绑定说明**  
本模块覆盖蓝本 B.3 回滚、D.3 rollback_to_stable；对应 T2.1-4、E2E-2.1-Rollback。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### B5. 自动停用与异常回滚（B.2）

**模块目标（Goal）**  
- 实现 B.2 异常条件与默认阈值；触发时执行：当前 active→disabled；若有 stable 则自动回滚到 stable（stable→active）；强告警+写入 release_audit（action=AUTO_DISABLE）；无 stable 时仅停用、不回滚目标，告警中明确说明。

**开发范围（Scope）**  
- **异常条件与默认阈值（写死）**：  
  - 连续亏损笔数：默认 5 笔（auto_disable.consecutive_loss_trades）；  
  - 连续亏损金额：策略级默认 1 个名义单位或绝对值（如 1000）（auto_disable.consecutive_loss_amount）；  
  - 回撤超过：默认 10%（auto_disable.max_drawdown_pct）；  
  - 系统健康检查失败：DB/交易所/关键组件不可用（与 HealthChecker 一致）。  
- **触发时系统行为（写死，三者均执行）**：  
  1. **停用**：当前 active 置为 **disabled**，该策略不再接收新信号、不产生新决策。  
  2. **回滚**：若存在 **stable**，则自动将生效版本回退到该 stable（stable→active），写 release_audit（action=AUTO_DISABLE，payload 含回滚目标）；若不存在 stable，则仅停用、不回滚目标。  
  3. **告警**：**必须**触发强告警（高优先级），并写入 release_audit 与审计日志（含 strategy_id、触发条件、阈值、时间戳、回滚目标若有）。  
- 配置项在实现文档中列明，默认阈值可被配置覆盖。

**输入 / 输出**  
- 输入：策略运行数据（如 trade 亏损笔数/金额、回撤、健康检查结果）；B.2 配置与阈值。  
- 输出：active→disabled；若有 stable 则 stable→active；release_audit 含 AUTO_DISABLE；告警触发。

**强制约束（Strong Constraints）**  
- 异常触发后**必须**执行停用；若有 stable **必须**回滚到 stable 并写 release_audit（AUTO_DISABLE）；**必须**强告警。  
- **禁止**在未满足 B.2 条件时误触发；**禁止**跳过审计或告警。  
- Phase 2.1 **不写入** evaluation_report、metrics_snapshot；读取的指标或 trade 数据仅用于触发判断，**禁止**用 Phase 2.1 写入 2.0 表。

**验收口径（Acceptance Criteria）**  
- [ ] 模拟满足 B.2 条件（如连续亏损 5 笔或回撤 10%）：原 active→disabled；若有 stable 则 stable→active；release_audit 含 action=AUTO_DISABLE；强告警已触发。  
- [ ] 无 stable 时：仅停用，不回滚目标；告警或 payload 中明确「无稳定版本可回滚」。  
- [ ] 触发后策略不再接收新信号直至人工恢复或回滚。

**绑定说明**  
本模块覆盖蓝本 B.2、D.3 自动停用；对应 T2.1-4、E2E-2.1-AutoDisable。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

### C. 核心逻辑（学习边界与建议生成）

#### C1. 学习输入只读边界（B.5）

**模块目标（Goal）**  
- 确立并实现「Optimizer/Learner 的输入**只能**来自 Phase 2.0 evaluation_report」的约束；**禁止**直接读 trade、decision_snapshot 做私有评估或自建第二套评估；接口与实现可被验收验证。

**开发范围（Scope）**  
- **接口约束**：Optimizer/Learner 的入参中，评估数据**仅**接受「evaluation_report 的 ID 或查询结果集」，或由调用方传入已从 Phase 2.0 查询到的报告；**禁止**传入 trade/execution 原始表或 raw 查询权限用于“自己算指标”。  
- **实现约束**：学习路径**禁止**直接读 trade 表做指标聚合、**禁止**用 decision_snapshot 产出评估结论；**禁止**任何绕过 Phase 2.0 Evaluator 的“第二套评估系统”。  
- 提供或依赖「按 strategy_version_id、param_version_id、evaluated_at 查询 evaluation_report」的只读接口（Phase 2.0 已提供）；不新增对 Phase 2.0 的写操作。

**输入 / 输出**  
- 输入：evaluation_report 的 ID 或 Phase 2.0 查询结果集；关联的 strategy_version_id/param_version_id。  
- 输出：本模块输出为「约束落地」与接口形态；为 C2 提供输入边界，不产出业务数据。

**强制约束（Strong Constraints）**  
- Optimizer/Learner 的输入**只能**为 Phase 2.0 的 **evaluation_report**（按 strategy_version_id、param_version_id、evaluated_at 查询）及关联的 strategy_version_id/param_version_id。  
- **禁止**：直接扫描 Phase 1.2 的 **trade** 表重新计算指标；直接基于 **decision_snapshot** 做“私有评估”或自建评估结论；任何绕过 Phase 2.0 Evaluator 的“第二套评估系统”。  
- Phase 2.1 **不修改** evaluation_report、**不写入** metrics_snapshot、**不更改** Phase 2.0 schema 或指标口径。

**验收口径（Acceptance Criteria）**  
- [ ] Optimizer/Learner 入参仅接受 evaluation_report 或 period（从 2.0 查询），无 trade 表/raw 指标入参；可通过接口签名与测试验证。  
- [ ] 验收可验证：学习路径未直接读 trade 表做指标聚合、未用 decision_snapshot 产出评估结论（代码审查或集成测试）。  
- [ ] Phase 2.0 未被写：Phase 2.1 未写入 evaluation_report/metrics_snapshot。

**绑定说明**  
本模块覆盖蓝本 B.5；对应 T2.1-1、T2.1-2、E2E-2.1「学习输入仅来自 2.0」。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### C2. Optimizer/Learner（仅白名单参数建议，输入仅 2.0，T2.1-1）

**模块目标（Goal）**  
- 实现 Optimizer.suggest：输入**仅**为 Phase 2.0 evaluation_report（或 report ID/查询结果）及 param_space（仅 B.1/B.4 白名单键）；输出 ParamSuggestion（**仅**白名单内键的建议值）；默认不写回，若显式开启写回须经门禁（B3）。

**开发范围（Scope）**  
- **Optimizer.suggest(strategy_id, evaluation_report_ids[] | evaluation_period, param_space) -> ParamSuggestion**：  
  - evaluation_report_ids 或 period：**仅**允许从 Phase 2.0 查询得到的 evaluation_report；**禁止**传入 trade 表或 raw 指标。  
  - param_space：**仅**允许 B.1 可学习参数清单内键；否则拒绝或过滤。  
  - ParamSuggestion：白名单内参数的建议值；不写回，除非显式配置开启并过门禁（见 B3）。  
- **禁止**：直接扫描 trade 表、基于 decision_snapshot 产出评估结论。  
- 可选：learning_audit 写入一条（evaluation_report_id、suggested_params 仅白名单键）；Optimizer.backtest 为可选。  
- 默认 **Human-in-the-loop**：仅产出建议；若开启自动写回则须经门禁且写 release_audit。

**输入 / 输出**  
- 输入：Phase 2.0 evaluation_report（ID 或查询结果）；strategy_id；param_space（仅 B.1 白名单键）。  
- 输出：ParamSuggestion（白名单内键）；可选 learning_audit 一条。

**强制约束（Strong Constraints）**  
- **学习输入仅来自 Phase 2.0**：入参仅接受 evaluation_report 或 period，无 trade/decision_snapshot 用于自评估；实现必须禁止直接读 trade 表、禁止用 decision_snapshot 产出评估结论。  
- **学习输出仅限白名单**：产出建议**仅**含 B.1 白名单键；**禁止**越权键；白名单与 B.4 事实源一致。  
- **写回对象仅 param_version**：若写回，仅生成/更新 param_version，不写 strategy_version。  
- Phase 2.1 **不写入** evaluation_report、**不写入** metrics_snapshot；**不更改** Phase 2.0 schema 或指标口径。

**验收口径（Acceptance Criteria）**  
- [ ] 入参仅接受 evaluation_report 或 period，无 trade 表/raw 指标入参。  
- [ ] 产出建议仅含 B.1 白名单键，抽检无越权键。  
- [ ] 白名单事实源：Optimizer 使用的白名单与 B.4 一致（代码与文档或同源配置）。  
- [ ] 人工路径：默认不写回，仅产出建议；若开启自动写回则须经门禁（T2.1-4）。  
- [ ] Phase 2.0 未被写：未写入 evaluation_report/metrics_snapshot。

**绑定说明**  
本模块覆盖蓝本 D.1、B.1、B.4、B.5；对应 T2.1-1、E2E-2.1。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### C3. 实盘反馈与评估触发（T2.1-2）

**模块目标（Goal）**  
- 实现评估触发（如 SchedulerOrTrigger.evaluate_on_schedule）；**仅触发** Phase 2.0 执行评估，评估结果存于 Phase 2.0 表；Phase 2.1 **仅只读查询** 2.0 报告，**不**写入 metrics_snapshot 或 evaluation_report；支撑「读 2.0 报告→参数建议→candidate→门禁→生效」闭环。

**开发范围（Scope）**  
- **SchedulerOrTrigger.evaluate_on_schedule(strategy_id, cron_or_interval) -> void**：触发 Phase 2.0 执行评估；评估结果存于 2.0 表，2.1 仅只读查询。  
- 基于评估结果的参数更新流程：2.1 读 2.0 报告 → C2 产出建议 → 提交 candidate → 经 B3 门禁 → approved → active。  
- 实盘 trade/decision 由 **Phase 2.0** 的 MetricsCalculator/Evaluator 消费（2.0 能力）；Phase 2.1 仅触发评估与读取 2.0 的评估结果。

**输入 / 输出**  
- 输入：触发配置（cron/间隔）；strategy_id；Phase 2.0 只读查询 API。  
- 输出：触发 2.0 评估；2.0 产出 evaluation_report；2.1 可读报告并驱动「建议→candidate→门禁→生效」。

**强制约束（Strong Constraints）**  
- Phase 2.1 **不写入** metrics_snapshot、**不写入** evaluation_report；**不更改** Phase 2.0 schema 或指标口径。  
- 2.1 仅**触发**评估与**读取** 2.0 报告；所有指标计算与报告写入由 Phase 2.0 完成。  
- 至少一次「读 2.0 报告→参数更新（白名单）→经门禁生效」可执行并验收。

**验收口径（Acceptance Criteria）**  
- [ ] 实盘可持续驱动 2.0 指标与评估（2.0 能力）；可配置评估周期。  
- [ ] 至少一次基于 2.0 评估结果的参数更新经门禁生效。  
- [ ] 人工确认路径：参数更新经 submit_candidate + confirm_manual/apply，有 release_audit。  
- [ ] 2.1 未写 2.0 表（evaluation_report、metrics_snapshot 无 2.1 写入）。

**绑定说明**  
本模块覆盖蓝本 D.2；对应 T2.1-2、E2E-2.1。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### C4. 写回规则与审计（C.4、B.6）

**模块目标（Goal）**  
- 在工程层面落实写回规则：写回对象**仅** param_version；写回路径 candidate→approved→active；**禁止**跳过 candidate、跳过审批、覆盖 stable；自动写回默认关闭、配置开启须过门禁且有审计；Phase 2.1 **不得污染** Phase 2.0（不写 evaluation_report/metrics_snapshot、不改 2.0 schema 或口径）。

**开发范围（Scope）**  
- **写回对象**：**仅** param_version；**禁止**写 strategy_version（策略逻辑或非白名单配置）。  
- **写回路径**：仅 candidate → approved → active；禁止跳过 candidate、跳过审批、覆盖 stable。  
- **自动写回**：默认关闭（如 auto_apply_after_gate=false）；显式开启后仍须经门禁；**必须**有 release_audit。  
- **Phase 2.0 不被污染**：Phase 2.1 **不修改** evaluation_report；**不写入** metrics_snapshot；**不更改** Phase 2.0 的 schema 或指标口径；仅追加 param_version、release_audit、learning_audit、发布状态等 Phase 2.1 自有数据。  
- 若与 2.0 共用 strategy_version 表，则**仅**在 2.1 侧扩展“状态”等 2.1 专属列或关联表，不改动 2.0 已定义的列语义。

**输入 / 输出**  
- 输入：所有写回与门禁路径（B3、B4、B5、C2 若写回）。  
- 输出：本模块为规则与校验层；确保各路径符合上述规则并写审计。

**强制约束（Strong Constraints）**  
- 写回对象**仅** param_version；写回路径**仅** candidate→approved→active；**禁止**跳过 candidate 或审批、**禁止**覆盖 stable。  
- Phase 2.1 **不修改** evaluation_report、**不写入** metrics_snapshot、**不更改** Phase 2.0 schema 或指标口径；**仅追加** Phase 2.1 自有表或字段。  
- 所有 submit_candidate、门禁通过/拒绝、apply、rollback、自动停用**必须**写 release_audit；**禁止**存在可生效但无审计记录的代码路径。

**验收口径（Acceptance Criteria）**  
- [ ] 所有写回路径仅针对 param_version；无对 strategy_version 策略逻辑或非白名单配置的写操作。  
- [ ] 无跳过 candidate/approved 或覆盖 stable 的路径。  
- [ ] 自动写回默认关闭；若开启则门禁与 release_audit 必现。  
- [ ] Phase 2.0 表（evaluation_report、metrics_snapshot）及 2.0 schema/口径未被 2.1 修改或写入；可通过对比 2.0 表与 2.1 代码/依赖验证。

**绑定说明**  
本模块覆盖蓝本 C.4、B.6；对应 T2.1-4、E2E-2.1、F.2 回归清单「Phase 2.0 不被污染」。验收通过后方可进入下一模块。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

### D. 测试与验收（可验证点）

以下仅描述**可验证点**，不要求编写测试代码；用于端到端与回归验收判定。每项须与蓝本 F 节用例对应，**仅引用、不新增**测试定义。

#### D1. E2E-2.1 主流程可验证点

**目标**  
- 验证 E2E-2.1（主流程）：执行评估(2.0) → 读取 2.0 evaluation_report → Optimizer.suggest（**仅**以报告为输入）→ 产出白名单参数建议 → submit_candidate → confirm_manual（或 risk_guard）→ approved → apply → active → 再次执行评估(2.0)并查询到新报告。

**可验证点**  
- [ ] 新报告存在且与当前 active param_version 关联；release_audit 含 SUBMIT_CANDIDATE、APPLY。  
- [ ] **学习输入仅来自 2.0**：无 trade 表/自评估路径；写回对象仅为 param_version。

**绑定说明**  
本模块对应蓝本 F.1 E2E-2.1；执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### D2. E2E-2.1-人工确认路径可验证点

**目标**  
- 验证 E2E-2.1-人工确认路径：submit_candidate 后**不**调用 confirm_manual（或门禁配置为必须人工）时，candidate 不自动变为 approved/active；仅在人工 confirm_manual 后 approved→active；release_audit 含 operator 或 gate_type=MANUAL。

**可验证点**  
- [ ] submit_candidate 后不调用 confirm_manual：candidate **不**自动变为 approved/active。  
- [ ] 仅在人工 confirm_manual（或等价）后 approved→active；release_audit 含 operator 或 gate_type=MANUAL。

**绑定说明**  
本模块对应蓝本 F.1 E2E-2.1-人工确认路径；执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### D3. E2E-2.1-自动写回关闭 / 门禁拦截可验证点

**目标**  
- 验证 E2E-2.1-自动写回关闭：默认配置下学习结果仅落为 candidate 或建议，不自动变为 active；须显式 confirm_manual/apply 后生效。  
- 验证 E2E-2.1-自动写回开启但被门禁拦截：配置自动写回开启时，风控或人工拒绝 candidate，candidate 不转为 approved/active；release_audit 有拒绝或未通过记录；当前 active 保持不变。

**可验证点**  
- [ ] 默认配置：学习结果仅 candidate 或建议，**不**自动变为 active；需显式 confirm_manual/apply 后生效。  
- [ ] 自动写回开启但门禁不通过：candidate **不**转为 approved/active；release_audit 有拒绝或未通过记录；当前 active 保持不变。

**绑定说明**  
本模块对应蓝本 F.1 E2E-2.1-自动写回关闭、E2E-2.1-自动写回开启但被门禁拦截；执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### D4. E2E-2.1-Rollback 可验证点

**目标**  
- 验证 E2E-2.1-Rollback：当前 active 为 A，存在 stable B；调用 rollback_to_stable 后，当前生效为 B（stable→active）；A 脱离 active；release_audit 含 action=ROLLBACK。

**可验证点**  
- [ ] 当前 active 为 A，存在 stable B；调用 rollback_to_stable。  
- [ ] 当前生效为 B（stable→active）；A 脱离 active；release_audit 含 action=ROLLBACK。

**绑定说明**  
本模块对应蓝本 F.1 E2E-2.1-Rollback；执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### D5. E2E-2.1-AutoDisable 可验证点

**目标**  
- 验证 E2E-2.1-AutoDisable（异常触发回滚）：模拟满足 B.2 条件（如连续亏损 5 笔或回撤 10%），触发自动停用；原 active→disabled；若有 stable 则 stable→active；release_audit 含 action=AUTO_DISABLE；强告警已触发；策略不再接收新信号直至人工恢复或回滚。

**可验证点**  
- [ ] 模拟满足 B.2 异常条件，触发自动停用。  
- [ ] 原 active→disabled；若有 stable 则 stable→active；release_audit 含 action=AUTO_DISABLE；强告警已触发；策略不再接收新信号直至人工恢复或回滚。

**绑定说明**  
本模块对应蓝本 F.1 E2E-2.1-AutoDisable；执行时须逐条满足。

### 本模块完成后必须回传的证据包

- 本模块涉及的变更文件清单（新增 / 修改 / 删除）
- 本模块的核心实现代码（关键函数或完整文件）
- 本模块对应的测试用例，或明确的可复现实跑步骤
- 测试命令与 **原始输出结果**
- 与本模块 Acceptance Criteria 的逐条对照说明

说明：
- 文档/配置类模块，可用文档或配置文件作为证据；
- 禁止使用「整体 E2E 已通过」替代本模块证据包。

---

#### D6. 回归清单可验证点
- [ ] 验证 Phase 2.0 产出的 evaluation_report 仍可被 Phase 2.1 读取且无口径偏移。
- [ ] 验证 Phase 1.2 订单执行路径未被 2.1 引入的「学习结果」干扰（在 auto_writeback=False 时）。

---

#### D7. 技术债专项修复：ALARM（T2.1-TD-1）

**模块目标（Goal）**  
- 实现分布式告警冷却去重与状态持久化；解决进程重启丢失冷却状态的问题。

**Strong Constraints**  
- **一致性**：分布式锁必须保证在网络分区时不会产生双重告警。

**验收口径 (AC)**  
- [ ] AC-RUN-MODEL-01: 多实例并发触发同一规则，仅产生一条告警。
- [ ] AC-RUN-MODEL-02: 进程重启后冷却状态不丢失。
- [ ] AC-RUN-MODEL-03: evaluate_rules 按固定周期自动触发。

**证据包要求**  
- 并发压力测试报告、审计日志、重启演练记录。

---

#### D8. 技术债专项修复：PERF（T2.1-TD-2）

**模块目标（Goal）**  
- 实现 Perf 写入故障隔离与 list_traces 性能优化。

**Strong Constraints**  
- **解耦**：Perf 模块的任何异常不得向上抛出至 Webhook 处理器。

**验收口径 (AC)**  
- [ ] AC-PERF-ISOLATION-01: Perf 写入失败不影响交易链路。
- [ ] AC-AUDIT-LISTTRACES-PERF-01: list_traces 消除 N+1 查询。

**证据包要求**  
- 故障注入测试报告、SQL 审计日志。

---

### 技术债模块级绑定清单

| TD ID | target_module | solution_plan 摘要 | acceptance 命令 | 证据包名称 |
|-------|---------------|-------------------|-----------------|------------|
| TD-RUN-MODEL-01 | Phase2.1:D7 | Redis 分布式冷却 | `pytest tests/integration/test_alarm_deduplication.py` | Phase2.1_D7_证据包.md |
| TD-RUN-MODEL-02 | Phase2.1:D7 | 冷却状态 DB 持久化 | `pytest tests/unit/test_alarm_persistence.py` | Phase2.1_D7_证据包.md |
| TD-RUN-MODEL-03 | Phase2.1:D7 | APScheduler 集成 | `python3 scripts/verify_scheduler.py` | Phase2.1_D7_证据包.md |
| TD-PERF-ISOLATION-01 | Phase2.1:D8 | 异步任务隔离 | `pytest tests/integration/test_perf_isolation.py` | Phase2.1_D8_证据包.md |

---

## 三、关键约束遵守检查清单

### ✅ 开发项唯一性
- [ ] Phase2.1 开发项仅包含 A1、A2、A3、B1、B2、B3、B4、B5、C1、C2、C3、C4、D1～D6，无合并、拆分、新增、遗漏或编号调整。
- [ ] 执行顺序与本文档「一、推荐执行顺序」一致。

### ✅ 学习输入边界（B.5）
- [ ] Optimizer/Learner 的输入**仅**为 Phase 2.0 evaluation_report 及关联 strategy_version_id/param_version_id；**未**出现直接扫描 trade 表重算指标或基于 decision_snapshot 的“私有评估”。
- [ ] 接口约束与验收可验证：学习路径未直接读 trade 表、未用 decision_snapshot 产出评估结论。

### ✅ 学习输出与写回边界
- [ ] 建议与写回**仅限白名单参数**（B.1/B.4）；写回对象**仅**为 param_version；**禁止**写 strategy_version 或非白名单配置。
- [ ] 写回路径**仅** candidate→approved→active；**禁止**跳过 candidate、跳过审批、覆盖 stable；自动写回默认关闭、配置开启须过门禁且有 release_audit。

### ✅ 发布与生效边界（B.3）
- [ ] 五态（candidate/approved/active/stable/disabled）已实现；**仅 active** 允许交易；状态迁移条件与触发方符合蓝本。
- [ ] 每次 submit_candidate、门禁通过/拒绝、apply、rollback、自动停用**必须**写 release_audit；**禁止**绕过审计的写回或状态变更。

### ✅ 回滚与异常（B.2）
- [ ] rollback_to_stable 可用；回滚粒度参数级（回到 stable param_version）；release_audit 含 ROLLBACK。
- [ ] 异常触发时：active→disabled；若有 stable 则回滚到 stable；强告警+release_audit（AUTO_DISABLE）；无 stable 时仅停用并告警说明。

### ✅ Phase 2.0 不被污染（B.6）
- [ ] Phase 2.1 **未**修改 evaluation_report、**未**写入 metrics_snapshot、**未**更改 Phase 2.0 的 schema 或指标口径；仅追加 param_version、release_audit、learning_audit、发布状态等 Phase 2.1 自有数据。

### ✅ 白名单事实源（B.4）
- [ ] 可学习参数清单与禁止修改项已在交付包中显式列出；白名单**单一事实源**已明确且文档与代码/schema 一致已验收；白名单变更须门禁与审计。

### ✅ Phase 2.1 终止条件与禁止进入后续 Phase
- [ ] 视为完成：A.2 全部达成且 F 节端到端用例（E2E-2.1、人工确认、自动写回关闭/门禁拦截、Rollback、AutoDisable）及回归清单通过。
- [ ] 禁止进入后续 Phase 的情形（任一条即禁止）：学习结果可绕过评估直接上线；无法回滚；白名单参数被越权修改；发布状态不可追溯；Phase 2.0 被污染（见蓝本 A.3、F.3）。

---

## 封版声明

> 本 Phase2.1 模块化开发交付包一经确认，即作为 Phase2.1 的**唯一开发真理源**。  
> 在后续开发、测试、验收过程中：  
> - 不允许新增开发项  
> - 不允许删除开发项  
> - 不允许调整模块顺序  
> - 不允许修改模块语义  
> - 不允许删减或弱化蓝本中的任何「必须/禁止/写死」规则  
>  
> 如需变更，必须基于 Phase2.1 开发蓝本（系统宪法）进行修订并同步本交付包。

---

**文档结束**
