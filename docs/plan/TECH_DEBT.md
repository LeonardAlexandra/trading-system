# 技术债清单（TECH_DEBT）

本文件用于记录必须被后续阶段偿还的硬性技术债，并在封版验收时作为门禁依据。

---

## 技术债条目

### TD-C7-02：Perf logging isolation

- **说明**：perf logging 写入失败不得影响主链路（webhook/执行链路不可因 perf 失败而失败）；采用 outbox/queue/worker 等隔离方式实现；Phase2.x 完成。
- **验收**：AC-PERF-ISOLATION-01，AC-PERF-ISOLATION-02
- **状态**：OPEN

### TD-C8-01：Audit list_traces N+1 query optimization

- **说明**：/api/audit/traces 当前为 N+1（每条 decision 调一次 trace 查询）；当需要扩大时间窗、或 limit 可能提高、或多策略批量回放时必须优化为批量查询/联表/物化视图等，避免数据库压力与延迟飙升；Phase2.x 完成。
- **验收**：AC-AUDIT-LISTTRACES-PERF-01，AC-AUDIT-LISTTRACES-PERF-02
- **状态**：OPEN

### TD-C8-02：Audit web page XSS hardening

- **说明**：/audit 页面当前为服务端拼接 HTML 字符串插值，存在潜在 XSS 风险；若 Phase2.x 计划对外或多用户访问，必须改为 escape 输出或前端安全渲染（textContent/模板引擎自动转义等）；Phase2.x 完成。
- **验收**：AC-AUDIT-WEB-XSS-01，AC-AUDIT-WEB-XSS-02
- **状态**：OPEN

### TD-C9-01：C9 压测数据库（SQLite → 生产等价）

- **说明**：C9 压力测试当前以 SQLite 作为压测数据库，Phase1.2 可接受；生产就绪或容量评估需在与生产等价的数据库（如 PostgreSQL）上复现压测并满足 Gate。Phase2.x 完成。
- **验收**：AC-C9-STRESS-DB-01
- **状态**：OPEN

### TD-C9-02：C9 execution worker 故障演练为手工

- **说明**：C9 故障恢复演练中「执行端不可用」场景当前为手工 kill worker / 重启，无自动化脚本或可重复注入；生产就绪需可复现的自动化故障注入与恢复验证。Phase2.x 完成。
- **验收**：AC-C9-FAILURE-DRILL-01
- **状态**：OPEN

### TD-C9-03：C9 备份校验非 schema-aware

- **说明**：C9 备份与恢复演练的校验步骤（decision_snapshot、log、trade 条数）当前非 schema-aware，表不存在时仅报错或跳过；生产就绪需按当前迁移 schema 做一致性校验（或显式声明适用版本）。Phase2.x 完成。
- **验收**：AC-C9-BACKUP-VERIFY-01
- **状态**：OPEN

### D2-TRACE-404：执行失败场景下 trace 可返回 404

- **说明**：执行失败场景下，trace 接口当前允许返回 404，导致失败路径可能被「查询不存在」掩盖，不利于审计与回放。Phase2.x 中，执行失败的 decision 必须可 trace，trace 中必须明确失败节点与失败原因（不得依赖 404）。
- **验收**：AC-D2-TRACE-404-01（见 Phase2.0 交付包 C5 附）
- **状态**：OPEN

### D2-HEALTH-WEAK-OBSERVABILITY：health 异常可观测性无明确字段与阈值

- **说明**：D2 中 health 异常可观测性使用「log_ok OR recent_errors OR error_count>0」的弱或条件，无明确字段与阈值，无法作为生产门禁。Phase2.x 中需定义明确的 health 异常字段与判定标准（类似 C9 Gate）。
- **验收**：AC-D2-HEALTH-OBSERVABILITY-01（见 Phase2.0 交付包 C5 附）
- **状态**：OPEN

---

## 状态字段规范

- OPEN：未开始
- IN_PROGRESS：进行中
- DONE：已偿还并验收通过
