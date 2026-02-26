# Phase1.2 C8～D2 蓝本符合性检查报告

**检查依据**：`trading_system/docs/plan/Phase1.2_模块化开发交付包.md`（唯一真理源）  
**检查范围**：C8、C9、D1、D2 四个模块  
**检查目的**：识别未开发、错误开发、未完整开发的部分（因 Context 遗失导致未严格按蓝本开展）

---

## 一、总览结论

| 模块 | 蓝本要求摘要 | 符合性 | 问题类型 |
|------|--------------|--------|----------|
| **C8** | list_traces + TraceSummary(trace_status/missing_nodes) + 审计界面(CLI/Web，start_ts/end_ts/component/level) + 错误码 400/404/500 + 列表上限 100 | **基本符合，2 处待补** | 未完整开发 |
| **C9** | 压力测试报告+结论通过、故障恢复记录、备份恢复文档+演练 | **结构符合，结论需按 Gate 判定** | 待确认 |
| **D1** | E2E-1 **完整链路**：1 条 trade + 1 条 decision_snapshot + trace_status=COMPLETE + 五节点 | **不符合** | 错误开发/未完整开发 |
| **D2** | E2E-2 **审计可验证点**：风控拒绝/执行失败后审计日志可查、query 按 start_ts/end_ts/component/level 筛选 | **不符合** | 错误开发（语义偏离） |

---

## 二、C8 模块

### 2.1 蓝本要求（摘录）

- **TraceQueryService.list_traces(start_ts, end_ts, strategy_id=None, limit=100, offset=0)** → list[TraceSummary]
- **TraceSummary**：trace_status（必填）、missing_nodes（PARTIAL 时非空）、signal_id、decision_id、strategy_id、created_at、summary 等
- **审计日志查询界面**：CLI 或 Web，筛选条件**至少** start_ts, end_ts, component, level；调用 LogRepository.query；与 1.2a 入库数据一致
- **错误码**：400 参数错误、404 未找到、500 服务错误；**列表单次上限 100 条**（或配置写死）

### 2.2 实际实现与缺口

| 项 | 蓝本 | 实现情况 | 结论 |
|----|------|----------|------|
| list_traces | TraceQueryService 提供，返回 list[TraceSummary] | ✅ 已实现于 `trace_query_service.list_traces`，audit_service 委托调用 | 符合 |
| TraceSummary | trace_status、missing_nodes（PARTIAL 非空）、signal_id、decision_id、strategy_id、created_at、summary | ✅ `schemas/trace.TraceSummary` 含上述字段，PARTIAL 由 C2 保证 missing_nodes 非空 | 符合 |
| 审计界面 | CLI 或 Web，筛选 start_ts, end_ts, component, level，调用 LogRepository.query | ✅ CLI `audit.py` 子命令 logs（--from/--to/--component/--level）；Web GET /api/audit/logs（from/to, component, level）；audit_service.query_logs → LogRepository.query(created_at_from, created_at_to, component, level) | 符合（参数名 from/to 等价 start_ts/end_ts） |
| 列表单次上限 100 | 写死 100 或配置 | ✅ GET /api/audit/traces 的 limit 为 Query(100, ge=1, **le=100**)；TraceQueryService.LIST_TRACES_MAX_LIMIT=100 | 符合 |
| **错误码 400/404/500** | 400 参数错误、404 未找到、500 服务错误 | ⚠️ **未显式实现**：audit 路由未对「参数错误」返回 400（FastAPI 默认 422）；trace 路由在 NOT_FOUND 时返回 404（符合）；无显式 500 约定。C8 交付包未要求 audit/traces 接口必须返回 400/404/500，但蓝本 C8 开发范围明确写了「错误码：400 参数错误、404 未找到、500 服务错误」 | **未完整开发**（建议补：参数非法 400，未找到 404，服务异常 500） |

### 2.3 C8 结论

- **list_traces、TraceSummary、审计界面（CLI+Web）、列表上限 100** 与蓝本一致，证据包与测试齐全。
- **缺口**：蓝本要求的「错误码 400/404/500」在 C8 的 **audit/traces API** 上未在交付包或实现中显式约定与实现（trace 单链路 404 已实现）；若严格按蓝本，需在 C8 范围内补充参数错误 400、未找到 404、服务错误 500 的约定与行为。

---

## 三、C9 模块

### 3.1 蓝本要求（摘录）

- 压力测试：负载与通过标准写死；**交付压力测试报告（含通过/不通过结论）**
- 故障恢复：故障恢复测试记录
- 备份与恢复：备份恢复流程文档及**至少一次演练成功记录**
- 验收口径：[ ] 压力测试报告存在且**结论通过**；[ ] 故障恢复测试有记录；[ ] 备份与恢复文档存在且至少一次演练成功

### 3.2 实际实现与缺口

| 项 | 蓝本 | 实现情况 | 结论 |
|----|------|----------|------|
| 压力测试脚本与报告 | 可运行脚本、原始输出、汇总报告、结论 | ✅ scripts/c9_stress_test.py；runlogs/c9_stress_output.txt、c9_stress_report.json；证据包定义 Gate（success_rate_pct≥95%、error_rate_pct≤5%） | 结构符合 |
| 压力测试「结论通过」 | 报告存在且**结论通过** | ⚠️ 证据包示例中 stress run 为 64% 成功率，**未达 Gate 95%**。若实际封版时 runlogs 中 stress 未达 95%，则按 C9 自身 Gate 判定为**未通过** | **待确认**：需以实际 runlogs 与 Gate 判定表为准，未达则 C9 未完整通过 |
| 故障恢复 | 至少 2 类场景、可复现、有记录 | ✅ 场景1 DB 不可用、场景2 执行端不可用；scripts/c9_failure_recovery_drill.sh；runlogs 有记录 | 符合 |
| 备份与恢复 | 流程文档 + 至少一次演练成功 | ✅ scripts/c9_backup_restore.sh；runlogs 有备份/恢复/校验输出。证据包 E 节显示某次演练中 decision_snapshot/log 表不存在（Error: no such table），仅 trade 可查；若「演练成功」定义为「脚本执行完成且至少 2 项校验已执行」则满足 | 符合（以证据包 Gate 与 runlogs 为准） |

### 3.3 C9 结论

- 压力测试、故障恢复、备份恢复的**结构与交付物**与蓝本一致；Gate 判定标准清晰。
- **缺口/风险**：蓝本要求「压力测试报告存在且**结论通过**」。C9 证据包将「结论通过」具体化为 GATE-C9-SUCCESS-RATE（≥95%）。若历史 runlogs 中 stress 成功率未达 95%，则 C9 门禁为 **FAIL**，属**未完整通过**，需在达标后再封版。

---

## 四、D1 模块（与蓝本严重偏离）

### 4.1 蓝本要求（摘录）

**D1. E2E-1 完整链路可验证点**

- **目标**：验证端到端：Webhook 信号 → decision → 同事务 decision_snapshot → **执行并成交** → 按 signal_id/decision_id 查询得**完整链路**（含 decision_snapshot）；**trace_status=COMPLETE**。
- **可验证点**：
  - [ ] 发送一条 Webhook 信号后，**DB 有 1 条 trade、1 条 decision_snapshot**，且 decision_id 一致。
  - [ ] get_trace_by_signal_id / get_trace_by_decision_id 返回 TraceResult **含五节点**；**trace_status=COMPLETE**，missing_nodes **为空或不存在**。

即：蓝本 D1 是「**完整链路**」——必须有 **1 条 trade**，trace 必须是 **COMPLETE**。

### 4.2 实际实现（证据包与测试）

- D1 证据包与测试明确：
  - **不造 trade**；sandbox/mock 不写 trade 表；
  - 若无 trade，则 trace 为 **PARTIAL**（missing_nodes 含 "trade"），dashboard trade_count **允许为 0**；
  - 验收通过条件为：decision_snapshot 存在、执行状态已更新、trace_status ∈ {COMPLETE, **PARTIAL**}，**PARTIAL 时** missing_nodes 含 "trade"。
- 即：当前 D1 以「**无 trade 的 PARTIAL 链路**」为通过标准，**没有**要求「1 条 trade + trace_status=COMPLETE」。

### 4.3 偏差结论

| 蓝本 D1 | 当前 D1 | 结论 |
|---------|---------|------|
| DB 有 1 条 trade + 1 条 decision_snapshot | 不造 trade，允许 0 条 trade | **未开发/未完整开发**（完整链路含 trade 的路径未作为可验证点） |
| trace_status=COMPLETE，五节点，missing_nodes 为空或不存在 | 允许 trace_status=PARTIAL，missing_nodes 含 "trade" | **错误开发**（可验证点被放宽为 PARTIAL，与蓝本「完整链路」语义不符） |

**D1 结论**：当前 D1 实现的是「在**无 trade** 能力边界下的主链路回归」，与蓝本 D1「**E2E-1 完整链路**（1 条 trade + COMPLETE）」**不一致**。属于**错误开发/未完整开发**：要么在 D1 中增加「有 1 条 trade 且 trace_status=COMPLETE」的可验证路径（在能落 trade 的环境下），要么在蓝本/交付包中显式允许「D1 在无 trade 环境下仅验证 PARTIAL 路径」并修订 D1 条文，否则与蓝本不符。

---

## 五、D2 模块（与蓝本语义偏离）

### 5.1 蓝本要求（摘录）

**D2. E2E-2 审计可验证点**

- **目标**：验证**风控拒绝或执行失败时，审计日志可查**且可按时间/组件/级别筛选。
- **可验证点**：
  - [ ] 触发一次风控拒绝或执行失败后，**LogRepository.query(level=AUDIT 或 ERROR) 含该事件**。
  - [ ] **query 按 start_ts, end_ts, component, level 可筛选出对应记录**。

即：蓝本 D2 是「**审计**」可验证点——重点在**审计日志是否可查、是否支持按时间/组件/级别筛选**，而不是「异常场景 E2E 覆盖多少种」。

### 5.2 实际实现（证据包与测试）

- D2 证据包与测试标题为「**异常/降级链路回归测试（Failure & Degradation E2E）**」。
- 内容为 4 类**异常场景**：决策快照写入失败、执行端不可用、数据库短暂不可用、Trace 链路不完整；验证行为包括：系统不崩溃、错误决策未成交、log 有 ERROR/AUDIT、trace PARTIAL/missing、health 反映异常等。
- **没有**专门的可验证点：
  - 「触发风控拒绝或执行失败后，**用 LogRepository.query(level=AUDIT 或 ERROR)** 能查到该事件」；
  - 「**query 按 start_ts, end_ts, component, level 筛选**，结果与 log 表一致」。

即：当前 D2 做的是「异常与降级 E2E」，**没有**把蓝本 D2 的「**审计可验证点**」（审计日志可查 + 按时间/组件/级别筛选）作为独立、显式的验收项。

### 5.3 偏差结论

| 蓝本 D2 | 当前 D2 | 结论 |
|---------|---------|------|
| 风控拒绝/执行失败后，LogRepository.query(level=AUDIT/ERROR) 含该事件 | 测试中有查 log 表（如 assert cur.fetchone()），但**未**以「审计查询接口/LogRepository.query」为验收主体，未写成「审计可验证点」 | **未完整开发**（审计可查性未作为 D2 主验收项） |
| query 按 start_ts, end_ts, component, level 可筛选出对应记录 | **未**在 D2 测试或证据包中显式验证「用 query(created_at_from, created_at_to, component, level) 筛选出风控拒绝/执行失败对应记录」 | **未开发**（按时间/组件/级别筛选的审计能力未在 D2 验收） |

**D2 结论**：当前 D2 实现的是「Failure & Degradation E2E」，与蓝本 D2「**E2E-2 审计可验证点**」**语义不一致**。属于**错误开发/未完整开发**：蓝本 D2 的「审计日志可查 + 按 start_ts/end_ts/component/level 筛选」在 D2 模块内**未**作为独立、可判定的验收项实现与证据化。建议在 D2 范围内补充：① 触发风控拒绝或执行失败后，通过 LogRepository.query（或审计 API）能查到对应 AUDIT/ERROR 记录；② 通过 query 的 start_ts/end_ts/component/level 筛选能命中上述记录。

---

## 六、整改建议汇总

| 模块 | 建议 |
|------|------|
| **C8** | 在 C8 范围内显式约定并实现（或文档说明）：audit/traces 相关接口在参数错误时返回 400、未找到时 404、服务异常时 500（若蓝本强制要求）。 |
| **C9** | 以 C9 证据包 Gate 为准：若历史 runlogs 中 stress 成功率未达 95%，则需重新跑压测直至达标，或修订 Gate/蓝本并记录豁免理由。 |
| **D1** | 二选一：① 在 D1 中增加「完整链路」可验证路径：在能落 trade 的环境下，验证「1 条 trade + 1 条 decision_snapshot + trace_status=COMPLETE + 五节点」；或 ② 修订蓝本/交付包 D1 条文，明确在无 trade 环境下 D1 仅验证 PARTIAL 路径，并区分「完整链路可验证点」为另一环境或后续阶段。 |
| **D2** | 在 D2 范围内补充「审计可验证点」：① 触发风控拒绝或执行失败后，通过 LogRepository.query(level=AUDIT 或 ERROR) 或审计 API 能查到该事件；② 通过 query(start_ts, end_ts, component, level) 能筛选出对应记录；测试或证据包中显式覆盖上述两项并可复现。 |

---

## 七、检查方法说明

- **蓝本**：以 `Phase1.2_模块化开发交付包.md` 中 C8、C9、D1、D2 的「目标」「开发范围」「可验证点」为准。
- **实现**：代码与证据包以 `trading_system/` 下 `src/`、`tests/`、`docs/Phase1.2_*_模块证据包.md`、`scripts/`、`docs/runlogs/` 等为据。
- **符合性**：逐条对比「蓝本可验证点/验收口径」与「实现与证据包内容」，标注符合/不符合/待确认及缺口。

---

**报告结束。后续开发计划暂停期间，可按本报告对 C8～D2 进行补齐或蓝本修订后再继续。**
