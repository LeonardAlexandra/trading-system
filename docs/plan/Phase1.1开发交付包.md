# Phase 1.1 开发交付包

**版本**: v1.0.0  
**创建日期**: 2026-02-05  
**最后修订**: 2026-02-05  
**基于**: Phase1.0 开发交付包 v1.3.1 + Phase1.1 技术设计范围（已确定且不可变更）

---

## 一、推荐执行顺序（强制）

以下顺序为 Cursor/开发者的**推荐执行顺序**，不可调整。开发项必须按此顺序实施，以降低依赖冲突与返工风险。

| 步骤 | 开发项 | 说明 |
|------|--------|------|
| 1 | A1 / A2 / A3 | 数据库迁移（可并行或按 A1→A2→A3 顺序） |
| 2 | C1 | ReconcileLock（DB 原子锁 + TTL） |
| 3 | C2 | 下单路径互斥保护 |
| 4 | C3 | PositionManager.reconcile → EXTERNAL_SYNC（含定价优先级） |
| 5 | C4 | RiskManager post-sync full check |
| 6 | C5 / C6 | 超仓挂起（C5）与 STRATEGY_PAUSED 终态日志（C6），可同序或 C5 先 C6 后 |
| 7 | B1 | POST /strategy/{id}/resume（强校验恢复 + diff 标准公式） |
| 8 | C7 | STRATEGY_RESUMED 终态日志 |
| 9 | D1 ~ D6 | 测试（TTL 锁、EXTERNAL_SYNC 定价、超仓挂起事务、Resume 强校验、对账/下单互斥） |
| 10 | B2 | GET /strategy/{id}/status（可选但推荐） |

---

## 二、开发项与交付

### A. 数据库迁移（Migrations）

#### A1. 扩展 `strategy_runtime_state`：互斥锁字段 + TTL 支撑

**目标**  
- 解决对账/恢复与下单路径的并发冲突，避免死锁与状态不一致；通过 TTL 保证锁在崩溃或异常后自动失效，系统可恢复。

**开发范围（必须明确）**  
- 在 `strategy_runtime_state` 表中新增或扩展字段：  
  - 互斥锁相关：如 `lock_holder_id`（或等效）、`locked_at`（锁获取时间）。  
  - TTL 支撑：如 `lock_ttl_seconds` 或等价配置，且锁过期时间 = `locked_at + TTL`，用于判定锁是否失效。  
- 迁移脚本：新增上述列及必要索引，不删除、不修改既有业务字段语义。

**硬性约束（Strong Constraints）**  
- 必须使用数据库原子操作实现加锁/续期/释放；具体实现范式以 C1 为准（仅允许基于单条原子 UPDATE 的租约锁，禁止 SELECT FOR UPDATE）。  
- 必须实现 30 秒 TTL（或配置化，默认 30 秒）：超过 TTL 未续期的锁视为失效，可被其他会话抢占。  
- 不允许无限期占锁；所有占锁路径必须支持显式释放或 TTL 过期。  
- 崩溃或进程退出后，仅依赖 DB 状态与 TTL 即可恢复（无外部协调器依赖）。

**逻辑真理源（Source of Truth）**  
- 以数据库表 `strategy_runtime_state` 中与锁、TTL 相关的字段为准；锁是否有效由“当前时间与 locked_at + TTL 比较”及“lock_holder_id 一致性”判定。

**交付物（Deliverables）**  
- Alembic 迁移脚本：新增/扩展 `strategy_runtime_state` 的锁与 TTL 字段。  
- 与 ReconcileLock（C1）对接所需的模型/Repository 层字段定义或文档说明。  
- 日志：加锁成功/失败、锁过期、锁释放时记录关键信息（不含敏感数据）。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行（upgrade/downgrade 无报错，幂等）。  
- [ ] 表中存在明确的锁持有者与锁时间、TTL 相关字段。  
- [ ] 文档或注释中明确 TTL 默认值为 30 秒及计算方式（locked_at + TTL）。  
- [ ] 无新增无限期锁语义；所有锁均可通过 TTL 或显式释放失效。

---

#### A2. trade：EXTERNAL_SYNC 支持

**目标**  
- 支持来自“外部同步”（交易所或外部系统）的成交写入，使对账与持仓校正能落库为可追溯的 trade 记录，并与信号驱动成交区分。

**开发范围（必须明确）**  
- 在 `trade` 表或关联模型中新增“来源”区分：如 `source_type` 或 `trade_source`，取值包含至少 `EXTERNAL_SYNC`（与既有信号驱动来源区分）。  
- 若存在 `execution_id` / `decision_id` 等字段，需明确 EXTERNAL_SYNC 场景下的可空或默认规则。  
- 迁移脚本：新增列或枚举，不破坏既有 trade 写入逻辑。

**EXTERNAL_SYNC 幂等性与唯一性（写死）**  
- **幂等键定义**：EXTERNAL_SYNC 的幂等键为 `(strategy_id, external_trade_id)`，其中 `external_trade_id` 为外部/交易所成交 ID，必须在表或唯一约束中体现。  
- **唯一性约束组合**：表上必须存在唯一约束，保证同一 `strategy_id` + `external_trade_id`（或等价字段组合）仅能插入一条 EXTERNAL_SYNC 记录；若表主键为 `trade_id`，则需额外唯一约束 `UNIQUE(strategy_id, external_trade_id)` 或等价实现，插入前按该组合判重。

**硬性约束（Strong Constraints）**  
- EXTERNAL_SYNC 的 trade 必须可被对账与 PositionManager 正确识别并用于持仓更新。  
- 必须保留与既有 trade 的同一套唯一性/幂等性约束（如按 trade_id），不得因 EXTERNAL_SYNC 引入重复写入。  
- 所有写入 trade 的路径（含 EXTERNAL_SYNC）必须在同一套事务与一致性边界内。

**逻辑真理源（Source of Truth）**  
- 以数据库 `trade` 表为准；EXTERNAL_SYNC 记录与信号驱动记录均以表中 `source_type`（或等价字段）区分，下游以该字段识别来源。

**交付物（Deliverables）**  
- Alembic 迁移脚本：`trade` 表增加 EXTERNAL_SYNC 来源支持（字段定义与默认值）。  
- 模型/Repository 更新：创建或更新 trade 时支持传入 `source_type=EXTERNAL_SYNC`。  
- 简短说明：EXTERNAL_SYNC 的适用场景与写入时机（对账路径）。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行且可回滚。  
- [ ] 可插入一条 `source_type=EXTERNAL_SYNC` 的 trade 且通过唯一约束与业务校验。  
- [ ] 既有信号驱动 trade 写入不受影响，且来源字段可区分。  
- [ ] 文档或注释中明确 EXTERNAL_SYNC 的语义与使用边界。

---

#### A3. position_reconcile_log：external_trade_id + event_type

**目标**  
- 为对账与审计提供可追溯日志：记录每次对账涉及的外部成交与事件类型，便于排查差异与恢复。

**开发范围（必须明确）**  
- 在 `position_reconcile_log` 表中新增或确认存在：  
  - `external_trade_id`：关联外部/交易所成交 ID（可空，非 EXTERNAL_SYNC 场景可空）。  
  - `event_type`：对账事件类型，取值**仅允许**下述封闭枚举。  
- 迁移脚本：新增上述列，不删除既有关键列。

**event_type 枚举（唯一真理源）**  
本文档为 `event_type` 的**唯一真理源**；实现阶段**不允许**自行新增或改名。完整、封闭的枚举列表及触发条件如下：

| event_type | 触发条件（一句话） |
|------------|---------------------|
| `RECONCILE_START` | 对账流程开始时写入。 |
| `RECONCILE_END` | 对账流程正常结束时写入。 |
| `SYNC_TRADE` | 写入一条 EXTERNAL_SYNC trade 时写入，关联 external_trade_id。 |
| `OVER_POSITION` | 风控判定超仓并触发挂起时写入。 |
| `STRATEGY_PAUSED` | 策略状态变更为 PAUSED 时写入（与 C5/C6 终态日志衔接）。 |
| `STRATEGY_RESUMED` | 策略通过 resume 恢复为 RUNNING 时写入（与 C7 衔接）。 |
| `RECONCILE_FAILED` | 对账过程中发生不可恢复错误时写入。 |

**硬性约束（Strong Constraints）**  
- 写入 `position_reconcile_log` 的操作必须与对账/挂起/恢复的关键步骤在同一事务或明确定义的一致性边界内，避免“有业务无日志”或“有日志无业务”。  
- `event_type` 取值**仅允许**上表枚举值，禁止自由文本或未列出的值。

**逻辑真理源（Source of Truth）**  
- 以数据库 `position_reconcile_log` 表为准；对账与外部同步行为以该表记录为审计依据，`external_trade_id` 与 `event_type` 为必填或条件必填（按事件类型定义）。

**交付物（Deliverables）**  
- Alembic 迁移脚本：`position_reconcile_log` 新增 `external_trade_id`、`event_type`（及必要索引/约束）。  
- 模型与 Repository 更新：写入 reconcile log 时填充上述字段。  
- 枚举或常量定义：`event_type` 的合法取值及含义**必须与本文档“event_type 枚举”表完全一致**，不得新增或改名。

**验收口径（Acceptance Criteria）**  
- [ ] 迁移可重复执行且可回滚。  
- [ ] 对账或 EXTERNAL_SYNC 路径可写入包含 `external_trade_id` 与 `event_type` 的日志记录。  
- [ ] `event_type` 仅接受预定义枚举值，无未定义取值。  
- [ ] 日志写入与对账/挂起逻辑的一致性边界在文档或代码注释中明确。

---

### B. API 层

#### B1. POST /strategy/{id}/resume（强校验恢复 + diff 标准公式）

**目标**  
- 在策略被挂起（如超仓）后，提供安全、可审计的恢复入口；仅当“当前状态与恢复条件”满足强校验时允许恢复，否则返回 400 及标准 diff，便于运维与自动化处理。

**开发范围（必须明确）**  
- 实现 `POST /strategy/{id}/resume`：  
  - 路径参数：`id` 为策略 ID。  
  - 强校验：在恢复前执行明确的状态与一致性检查（如持仓是否已校正、风控是否通过、策略状态是否为 PAUSED 等，以设计为准）。  
  - 失败时：返回 HTTP 400，响应体包含标准化的“差异”信息（diff），格式固定（如 DB 状态 vs 预期状态、或风控检查项 vs 通过条件）。  
  - 成功时：将策略状态置为可接收信号（如 RUNNING），并触发或记录 STRATEGY_RESUMED（由 C7 落库）。  
- diff 标准公式：文档中明确定义 diff 的字段名、结构与示例（如 JSON schema 或示例响应）。

**B1 差异判定与 diff 标准**（Phase1.x～Phase2.x 唯一标准，后续模块必须复用，不得另起格式）

- **diff JSON 顶层结构**（固定字段名，全部必须出现）：
  - `code`：string，失败原因枚举值（如 `RESUME_CHECK_FAILED`、`POSITION_NOT_RECONCILED`、`RISK_CHECK_FAILED` 等，由实现固定枚举）。
  - `checks`：array，每一项为 object，包含固定字段：
    - `field`：string，检查项名称（如 `position_reconciled`、`risk_passed`、`state_is_paused`）。
    - `expected`：任意类型，期望值或描述。
    - `actual`：任意类型，当前实际值或描述。
    - `pass`：boolean，该项是否通过。
  - `snapshot`：object，仅包含用于审计的关键状态摘要（如 `strategy_id`、`status`、`last_reconcile_at`、关键持仓/风控摘要等；不可过大，禁止全量 dump）。

- **校验失败示例**（400 响应体）：
```json
{
  "code": "RESUME_CHECK_FAILED",
  "checks": [
    { "field": "position_reconciled", "expected": true, "actual": false, "pass": false },
    { "field": "risk_passed", "expected": true, "actual": false, "pass": false }
  ],
  "snapshot": {
    "strategy_id": "MOCK_STRATEGY_V1",
    "status": "PAUSED",
    "last_reconcile_at": "2026-02-05T10:00:00Z"
  }
}
```

- **校验通过示例**（2xx，可无 diff）：恢复成功时响应体可不包含 diff，或仅包含 `code: "OK"`、`checks: []`、`snapshot` 为可选摘要；若包含则结构同上，不得新增其他顶层字段。

**硬性约束（Strong Constraints）**  
- 不允许在强校验未通过时执行恢复或变更策略状态。  
- 400 响应必须包含可被调用方解析的 diff 结构，不得仅返回纯文本描述。  
- 恢复成功与 STRATEGY_RESUMED 终态日志必须在同一一致性边界内（同一事务或等价保证）。

**逻辑真理源（Source of Truth）**  
- 恢复是否允许：以服务端当前 DB 状态与风控/对账结果为准；diff 内容以当前 DB 状态与“恢复通过所需状态”的对比为准。

**交付物（Deliverables）**  
- `POST /strategy/{id}/resume` 路由实现（含参数校验、强校验逻辑、状态更新）。  
- 标准化 diff 响应格式文档（字段、结构、示例）及在 400 响应中的使用方式。  
- 与 C7 的衔接：恢复成功时触发 STRATEGY_RESUMED 终态日志写入。  
- 日志：请求入参、校验结果（通过/失败）、diff 摘要（不包含敏感信息）。

**验收口径（Acceptance Criteria）**  
- [ ] 强校验未通过时返回 400，且响应体包含符合“diff 标准公式”的结构化 diff。  
- [ ] 强校验通过时返回 2xx，策略状态变为可接收信号，且 STRATEGY_RESUMED 已落库。  
- [ ] 对不存在的 strategy id 返回 404 或约定错误码。  
- [ ] diff 字段与文档描述一致，可被自动化脚本解析。

---

#### B2. GET /strategy/{id}/status（可选但推荐）

**目标**  
- 提供策略运行时状态的查询接口，便于运维、监控与恢复前检查；与 B1 配合使用时可先查 status 再决定是否调用 resume。

**开发范围（必须明确）**  
- 实现 `GET /strategy/{id}/status`：  
  - 路径参数：`id` 为策略 ID。  
  - 返回内容：至少包含策略状态（如 RUNNING / PAUSED）、与恢复相关的摘要信息（如是否可 resume、最后对账时间等，以设计为准）。  
- 不要求包含敏感或过大 payload；可引用已有 `strategy_runtime_state` 或等价数据源。

**硬性约束（Strong Constraints）**  
- 返回的状态必须与数据库/运行时真理源一致，不得返回过期或与 DB 不一致的状态。  
- 接口为只读，不改变策略状态。

**逻辑真理源（Source of Truth）**  
- 以数据库 `strategy_runtime_state`（及与状态相关的表）为准；接口为上述状态的只读投影。

**交付物（Deliverables）**  
- `GET /strategy/{id}/status` 路由实现及响应模型（字段说明）。  
- 简短文档：响应字段含义与使用场景（含与 B1 的配合说明）。

**验收口径（Acceptance Criteria）**  
- [ ] 对存在的 strategy id 返回 200 及包含状态与必要摘要的 JSON。  
- [ ] 对不存在的 strategy id 返回 404 或约定错误码。  
- [ ] 响应与 DB 中当前策略状态一致（可通过对 DB 的直查对比验证）。  
- [ ] 接口无副作用（多次调用不改变状态）。

---

### C. 核心逻辑

#### C1. ReconcileLock（DB 原子锁 + TTL）

**目标**  
- 在对账与恢复流程中提供进程内/跨请求的互斥，避免多请求或定时任务并发对账导致状态错乱；通过 DB 原子锁 + TTL 保证崩溃后可恢复且无无限占锁。

**开发范围（必须明确）**  
- 实现 ReconcileLock：**只允许一种实现范式——基于数据库的租约锁（lease lock）**，使用**单条原子 UPDATE** 进行抢占与续期，禁止 SELECT FOR UPDATE、禁止长事务持锁期间做外部 I/O。  
  - **acquire（加锁）**：条件为“当前无锁”或“锁已过期”（当前时间 > locked_at + TTL）。实现方式：单条 `UPDATE strategy_runtime_state SET lock_holder_id=?, locked_at=NOW() WHERE strategy_id=? AND (lock_holder_id IS NULL OR locked_at + TTL < NOW())`，若 affected rows = 1 则成功，否则抢占失败。  
  - **renew（续期）**：条件为“当前锁持有者为本实例且未过期”。实现方式：单条 `UPDATE strategy_runtime_state SET locked_at=NOW() WHERE strategy_id=? AND lock_holder_id=? AND locked_at + TTL > NOW()`，affected rows = 1 则续期成功。  
  - **release（释放）**：条件为“当前锁持有者为本实例”。实现方式：单条 `UPDATE strategy_runtime_state SET lock_holder_id=NULL, locked_at=NULL WHERE strategy_id=? AND lock_holder_id=?`，affected rows = 1 则释放成功。  
  - **抢占失败时的处理策略**：**仅允许两种**——（1）立即失败返回，或（2）有限重试（重试次数与间隔由配置固定，如最多 3 次、间隔 100ms）；禁止无限等待或自旋。  
- 与 C2、C3 的衔接：对账路径与下单路径使用同一套 ReconcileLock，在文档中说明。

**硬性约束（Strong Constraints）**  
- **禁止**使用 SELECT FOR UPDATE 或长事务持锁后再做加锁/续期。  
- **禁止**在持锁期间发起外部 HTTP、外部 IO 或长时间计算；持锁内仅允许短时 DB 写与内存操作。  
- 必须使用上述单条原子 UPDATE 实现 acquire/renew/release，禁止仅内存锁。  
- TTL 默认 30 秒，超时未续期则锁失效。  
- 不允许无限期占锁；持有锁的代码路径必须在有限时间内释放或续期。

**逻辑真理源（Source of Truth）**  
- 以数据库 `strategy_runtime_state` 中锁相关字段为准；锁的归属与有效期仅由 DB 状态决定。

**交付物（Deliverables）**  
- ReconcileLock 类或模块：acquire（含 TTL）、release、renew（可选）、以及“当前是否被本实例持有”的查询接口。  
- 使用 ReconcileLock 的调用约定文档（如 with 上下文用法、异常时是否自动释放）。  
- 日志：加锁/释放/过期事件。

**验收口径（Acceptance Criteria）**  
- [ ] 同一 strategy 下，仅一个会话可持有锁；其他会话加锁失败或等待后失败。  
- [ ] 锁超过 TTL 未续期后，其他会话可成功获取锁。  
- [ ] 显式释放后，其他会话可立即获取锁。  
- [ ] 加锁/释放均在 DB 事务内完成，无仅内存状态。  
- [ ] D1 中 TTL 锁超时测试通过。

---

#### C2. 下单路径互斥保护

**目标**  
- 保证“信号驱动下单”与“对账/恢复”等写持仓路径互斥，避免并发写导致持仓或订单状态不一致。

**开发范围（必须明确）**  
- 在信号驱动下单的入口（如 ExecutionEngine.execute 或调用其的上层）与对账/恢复写持仓的入口，使用同一套 ReconcileLock（C1）。  
- 明确“持锁范围”：从“决策执行前”到“订单与持仓落库完成”或“明确失败并回滚”为止。  
- 不扩大锁粒度到不必要的读路径；仅对“会写 position_snapshot / trade / strategy_runtime_state”的路径加锁。

**执行边界规范（强制性）**  
- **必须在锁外执行**（禁止放入持锁块内）：  
  - 外部 HTTP 请求（交易所 API 调用）；  
  - 数据拉取（交易所持仓/成交、账户等）；  
  - 差异计算（本地 vs 外部对比、风控计算等）。  
- **必须在锁内执行**（持锁后、释放前）：  
  - trade / position_snapshot / position_reconcile_log 的写入；  
  - strategy_runtime_state 的更新（含状态、锁字段）。  
- **标准执行顺序**（对账路径示例）：  
  1. 锁外：拉取交易所数据 → 计算差异；  
  2. acquire 锁；  
  3. 锁内：写 EXTERNAL_SYNC trade、更新 position_snapshot、写 position_reconcile_log、更新 strategy_runtime_state（如需）；  
  4. release 锁。  
  下单路径同理：锁外可做决策与风控计算；acquire 后仅做 DB 写入与 state 更新，再 release。  
- **明确禁止**：任何外部 I/O（HTTP、RPC、文件、其他进程）放入锁内，均视为实现错误；若因此导致线上死锁或长阻塞，视为违反本规范。

**硬性约束（Strong Constraints）**  
- 下单路径与对账/EXTERNAL_SYNC 写持仓路径不能同时持有写锁；必须串行化。  
- 持锁期间发生异常时，锁必须被释放（finally 或上下文管理器），避免死锁。  
- 不允许在未持锁的情况下写入会与对账冲突的持仓或状态。  
- 持锁块内不得包含外部 I/O。

**逻辑真理源（Source of Truth）**  
- 互斥的真理源与 C1 一致：以 DB 锁状态为准；业务上以“同一时刻仅一条写路径生效”为可接受状态。

**交付物（Deliverables）**  
- 在下单路径与对账路径中集成 ReconcileLock（C1）的调用代码。  
- 文档：持锁边界、与 C1 的配合、异常时释放保证。  
- 日志：持锁开始/结束、超时或失败。

**验收口径（Acceptance Criteria）**  
- [ ] 并发执行“下单”与“对账写持仓”时，无数据竞争导致的错误或重复写入。  
- [ ] 异常或超时后锁被释放，可被 D6 对账/下单互斥测试验证。  
- [ ] 持锁范围在代码或文档中明确，且不包含不必要的长时间 I/O（如外部 HTTP 可考虑在锁外）。

---

#### C3. PositionManager.reconcile → EXTERNAL_SYNC（含定价优先级）

**目标**  
- 将对账结果以 EXTERNAL_SYNC 的 trade 形式落库，并更新 position_snapshot；定价采用明确优先级（如交易所成交价 > 本地计算价 > 最后已知价），保证可复现与审计一致。

**开发范围（必须明确）**  
- 实现或扩展 `PositionManager.reconcile`（或等价对账入口）：  
  - 输入：策略 ID、可选 symbol/侧；与交易所（或外部系统）的持仓/成交差异。  
  - 行为：对“需同步的差异”生成 EXTERNAL_SYNC 类型的 trade 并写入 trade 表（A2），并更新 position_snapshot；同时写入 position_reconcile_log（A3）含 external_trade_id、event_type。  
- 定价优先级（必须明确写入文档与实现）：  
  - 第一优先：交易所（或外部）返回的成交价/结算价；  
  - 第二优先：本地计算或配置的参考价；  
  - 第三优先：最后已知价或兜底价。  
  - 若某层级无数据则降级到下一层级，且需在日志或 log 中记录使用的优先级档位。

**硬性约束（Strong Constraints）**  
- EXTERNAL_SYNC 的 trade 必须使用上述定价优先级，不得随意选用未定义来源的价格。  
- 对账写 trade 与 position_snapshot、position_reconcile_log 必须在同一事务或明确定义的一致性边界内。  
- 与 C1/C2 的互斥：reconcile 必须在持锁下执行（或与下单路径互斥）。

**逻辑真理源（Source of Truth）**  
- 对账前：以交易所/外部系统返回的持仓与成交为“外部真理”；以本地 position_snapshot 与 trade 为“本地真理”。  
- 对账后：以本次写入的 EXTERNAL_SYNC trade 与更新后的 position_snapshot 为新的本地真理；position_reconcile_log 为审计真理。

**交付物（Deliverables）**  
- `PositionManager.reconcile`（或等价方法）实现：生成 EXTERNAL_SYNC trade、更新持仓、写 reconcile log。  
- 定价优先级文档与代码注释；实现中严格按优先级取价并在日志中记录档位。  
- 与 A2、A3 的对接：使用 source_type=EXTERNAL_SYNC、external_trade_id、event_type。

**验收口径（Acceptance Criteria）**  
- [ ] 对账产生的 trade 的 source_type 为 EXTERNAL_SYNC，且定价来源符合优先级规则。  
- [ ] position_snapshot 与 trade、position_reconcile_log 在事务内一致更新。  
- [ ] D2 EXTERNAL_SYNC 定价优先级测试通过。  
- [ ] 优先级档位在日志或 log 中可追溯。

---

#### C4. RiskManager post-sync full check

**目标**  
- 在对账或 EXTERNAL_SYNC 同步完成后，对策略做一次完整风控检查（如仓位、资金、集中度等），确保同步后的状态仍满足风控策略；不通过时可触发挂起或拒绝后续信号。

**开发范围（必须明确）**  
- 在对账/EXTERNAL_SYNC 写入完成之后（同一请求或同一任务内），调用 RiskManager 的“全量检查”接口（如 full_check 或等价），传入当前策略 ID 及必要上下文（持仓、账户等）。  
- 检查结果：若未通过，与 C5 衔接——触发超仓挂起（拒绝信号 + PAUSED + 终态日志）；若通过，则允许后续信号或恢复。  
- 不改变 RiskManager 的输入输出契约以外的语义；仅增加“在对账后必须调用”的约束与调用点。

**硬性约束（Strong Constraints）**  
- 对账或 EXTERNAL_SYNC 同步后，必须执行一次 RiskManager 全量检查，不得跳过。  
- 全量检查的输入必须基于同步后的最新 position_snapshot 与账户数据，不得使用旧快照。

**逻辑真理源（Source of Truth）**  
- 风控结果以 RiskManager 的返回为准；是否挂起以“全量检查未通过 + 业务规则”为准，并与 C5 一致。

**交付物（Deliverables）**  
- 在对账/EXTERNAL_SYNC 流程末尾调用 RiskManager 全量检查的代码及调用顺序说明。  
- 与 C5 的衔接：检查不通过时触发挂起与终态日志的路径。  
- 日志：检查触发、通过/不通过、不通过原因摘要。

**验收口径（Acceptance Criteria）**  
- [ ] 每次对账/EXTERNAL_SYNC 同步完成后，可验证曾调用 RiskManager 全量检查。  
- [ ] 全量检查不通过时，与 C5 的挂起与终态日志行为一致。  
- [ ] 检查使用同步后的最新数据，无陈旧快照。

---

#### C5. 超仓挂起（拒绝信号 + PAUSED + 终态日志，同一事务）

**目标**  
- 当风控判定超仓或不可接受状态时，将策略挂起（PAUSED）、拒绝新信号，并在一笔事务内写入 STRATEGY_PAUSED 终态日志，保证“状态与日志”一致、可审计。

**开发范围（必须明确）**  
- 在“风控不通过”或“超仓”的判定点：  
  - 将策略状态更新为 PAUSED（写入 strategy_runtime_state 或等价表）。  
  - 拒绝当前及后续信号（直至 resume）；拒绝时行为见下“信号拒绝规范”。  
  - 在同一数据库事务内，写入 STRATEGY_PAUSED 终态日志（含差异快照，见 C6）。  
- 不允许“仅改状态不写日志”或“仅写日志不改状态”；不允许分属不同事务导致状态与日志不一致。

**信号拒绝规范（写死）**  
- **Webhook 返回码**：策略处于 PAUSED 时，信号入口（如 `/webhook/tradingview`）收到新信号后**必须**返回 HTTP **200**，body 中通过业务字段区分“已拒绝”（例如 `status: "rejected"`、`reason: "STRATEGY_PAUSED"`）；禁止使用 4xx/5xx 作为“策略挂起导致拒绝”的语义，以避免 TradingView 端误判为失败重试。  
- **是否记录 rejection 事件**：**必须**记录。每次因 PAUSED 拒绝信号时，必须写入一条可审计记录（如 log 表或专用 rejection 表），字段至少包含：策略 ID、signal_id（若有）、拒绝原因 `STRATEGY_PAUSED`、时间戳。  
- **是否写入日志/表**：**必须**写入；上述 rejection 事件可写入 log 表（level=WARNING 或等价）或专用表，且与“不重复处理同一 signal”的语义一致（同一 signal 重复到达仍只记一条拒绝记录或按去重策略处理）。

**硬性约束（Strong Constraints）**  
- 状态更新为 PAUSED 与 STRATEGY_PAUSED 终态日志必须在同一事务中提交；任一步失败则整体回滚。  
- 挂起后，信号入口必须拒绝处理新信号（返回或记录拒绝原因），直至 B1 resume 成功。

**逻辑真理源（Source of Truth）**  
- 策略是否 PAUSED 以数据库 strategy_runtime_state 为准；挂起事件以 STRATEGY_PAUSED 终态日志为准；二者必须在同一事务内一致。

**交付物（Deliverables）**  
- 超仓/风控不通过时的处理逻辑：更新 PAUSED、写 STRATEGY_PAUSED 终态日志（含差异快照）、信号入口拒绝逻辑。  
- 事务边界文档：PAUSED 与终态日志在同一事务内的实现方式。  
- 日志：挂起触发原因、差异快照摘要。

**验收口径（Acceptance Criteria）**  
- [ ] 触发挂起时，DB 中策略状态为 PAUSED 且存在对应 STRATEGY_PAUSED 终态日志记录。  
- [ ] 状态与终态日志在同一事务内提交（可通过异常注入验证回滚一致性）。  
- [ ] 挂起后新信号被拒绝，且拒绝原因可追溯。  
- [ ] D3 超仓挂起事务性测试通过。

---

#### C6. STRATEGY_PAUSED 终态日志（含差异快照）

**目标**  
- 为每次策略挂起留下不可篡改的终态记录，并包含“差异快照”（如当前持仓 vs 风控上限、或导致挂起的检查项），便于事后分析与恢复决策。

**开发范围（必须明确）**  
- 在写入 STRATEGY_PAUSED 终态日志时，除必要元数据（策略 ID、时间、原因等）外，必须包含“差异快照”：  
  - 内容可为：当前持仓、风控阈值、超出项、或标准化 diff 结构（与 B1 diff 可复用部分结构）。  
  - 存储形式：数据库表（如 log 或专用 event 表）的 JSON 字段或结构化列；格式固定、可解析。  
- 与 C5 的衔接：该日志与 PAUSED 状态更新在同一事务内写入。

**硬性约束（Strong Constraints）**  
- STRATEGY_PAUSED 日志必须包含差异快照，不允许仅文本描述。  
- 差异快照格式固定、可被工具或 B1 的 diff 逻辑复用/对比。  
- 与 C5 同一事务约束不变。

**逻辑真理源（Source of Truth）**  
- 以数据库中的 STRATEGY_PAUSED 终态日志记录为准；差异快照内容以写入时的状态为准，不再事后修改。

**交付物（Deliverables）**  
- STRATEGY_PAUSED 终态日志的写入逻辑及差异快照的组装逻辑。  
- 差异快照的字段定义或 schema（与 B1 diff 的关联说明）。  
- 与 C5 在同一事务内调用的实现与验证说明。

**验收口径（Acceptance Criteria）**  
- [ ] 每次 STRATEGY_PAUSED 写入都包含非空差异快照。  
- [ ] 差异快照可解析且字段与文档一致。  
- [ ] 与 C5 同事务验证通过（D3 覆盖）。  
- [ ] 可通过查询终态日志还原挂起时的关键状态。

---

#### C7. STRATEGY_RESUMED 终态日志

**目标**  
- 为每次策略恢复留下终态记录，与 STRATEGY_PAUSED 成对，形成“挂起—恢复”的完整审计链。

**开发范围（必须明确）**  
- 在 B1 `POST /strategy/{id}/resume` 强校验通过并执行恢复时，在同一事务或一致性边界内写入 STRATEGY_RESUMED 终态日志。  
- 日志内容：至少包含策略 ID、恢复时间、触发方式（如 API）、可选恢复前状态摘要（如上次 PAUSED 原因）。  
- 与 B1 的衔接：仅当恢复成功并提交后写入，失败则不写。

**硬性约束（Strong Constraints）**  
- STRATEGY_RESUMED 必须在恢复成功并提交的同一事务或等价边界内写入。  
- 不允许在未执行恢复或强校验未通过时写入 STRATEGY_RESUMED。

**逻辑真理源（Source of Truth）**  
- 以数据库中的 STRATEGY_RESUMED 终态日志为准；恢复是否发生以该记录及策略状态为准。

**交付物（Deliverables）**  
- STRATEGY_RESUMED 终态日志的写入逻辑及字段定义。  
- 与 B1 的衔接：在恢复成功分支内调用写入。  
- 日志：恢复请求、校验结果、写入成功。

**验收口径（Acceptance Criteria）**  
- [ ] B1 恢复成功时，DB 中存在对应 STRATEGY_RESUMED 记录。  
- [ ] B1 恢复失败（400）时，不写入 STRATEGY_RESUMED。  
- [ ] 恢复与 STRATEGY_RESUMED 在同一事务或明确定义的一致性边界内。  
- [ ] D5 Resume 强校验成功用例可验证 STRATEGY_RESUMED 已落库。

---

### D. 测试

#### D1. TTL 锁超时测试

**目标**  
- 验证 ReconcileLock 在 TTL 过期后释放，其他会话可重新获取锁，且无无限占锁。

**开发范围（必须明确）**  
- 编写自动化测试：获取 ReconcileLock 后不释放、不续期，等待超过 TTL；验证另一会话在 TTL 后可成功获取锁。  
- 可选：验证续期可延长占用、显式释放后立即可被获取。

**TTL 测试可执行性（强制）**  
- **测试环境中 TTL 的配置方式**：必须通过**环境变量**或**配置文件**（如 `RECONCILE_LOCK_TTL_SECONDS` 或 config 中 `reconcile_lock.ttl_seconds`）在测试启动前注入，使测试使用短 TTL，**禁止**在测试中使用真实生产 TTL（30 秒）。  
- **测试推荐 TTL**：**1～2 秒**（如 1 秒或 2 秒），以便 CI 在数秒内完成锁过期断言。  
- **明确禁止**：不得通过 `sleep(30)` 或等价方式等待生产 TTL 过期；测试必须依赖上述可配置的短 TTL 或 mock 时间推进，保证测试在合理时间内结束。

**硬性约束（Strong Constraints）**  
- 测试不依赖人工等待；必须使用可配置短 TTL（1～2 秒）或 mock 时间以控制执行时间。  
- 测试必须可重复运行且结果稳定。  
- 测试中不得使用真实生产 TTL；不允许 sleep 30s 等方式等待锁过期。

**逻辑真理源（Source of Truth）**  
- 以 DB 中锁字段与当前时间（或测试时钟）为准判定锁是否失效。

**交付物（Deliverables）**  
- 自动化测试用例：TTL 过期后锁失效、其他会话可获取；可选续期与显式释放用例。  
- 测试说明：环境要求、TTL 配置方式（如测试用 2 秒）。

**验收口径（Acceptance Criteria）**  
- [ ] TTL 过期后，原持有者不再被视为持有锁，新会话可获取锁。  
- [ ] 显式释放后，新会话可立即获取锁。  
- [ ] 测试可在 CI 中稳定通过（无 flaky）。

---

#### D2. EXTERNAL_SYNC 定价优先级测试

**目标**  
- 验证 C3 中 EXTERNAL_SYNC 的定价优先级（交易所价 > 本地参考价 > 兜底价）被正确执行，且落库 trade 的价格与预期档位一致。

**开发范围（必须明确）**  
- 编写测试：构造不同数据场景（有交易所价、仅有本地价、仅有兜底价），执行 PositionManager.reconcile 或等价路径，断言生成的 EXTERNAL_SYNC trade 的 price 与预期优先级一致。  
- 可选：验证日志或 log 中记录了使用的优先级档位。

**硬性约束（Strong Constraints）**  
- 测试必须覆盖至少三档优先级中的每一档；边界情况（多档同时存在时取最高优先）需覆盖。  
- 不依赖真实交易所；使用 mock 或 fixture 数据。

**逻辑真理源（Source of Truth）**  
- 以 C3 文档中的定价优先级定义为准；测试断言与之一致。

**交付物（Deliverables）**  
- 自动化测试用例：多组输入对应不同优先级档位，断言 trade.price 与档位一致。  
- 测试数据或 mock 说明。

**验收口径（Acceptance Criteria）**  
- [ ] 有交易所价时，EXTERNAL_SYNC trade 使用交易所价。  
- [ ] 无交易所价有本地参考价时，使用本地参考价。  
- [ ] 仅兜底价时，使用兜底价。  
- [ ] 测试可重复运行且通过。

---

#### D3. 超仓挂起事务性测试

**目标**  
- 验证 C5：超仓挂起时，PAUSED 状态与 STRATEGY_PAUSED 终态日志在同一事务内提交；任一步失败则整体回滚。

**开发范围（必须明确）**  
- 编写测试：触发超仓挂起路径，验证 DB 中同时存在 PAUSED 状态与 STRATEGY_PAUSED 记录。  
- 可选：通过异常注入（如模拟日志写入失败）验证事务回滚后状态与日志均未提交。

**硬性约束（Strong Constraints）**  
- 测试必须验证“同事务”语义；回滚场景可用 mock 或可控异常触发。  
- 不依赖真实超仓业务数据；可构造 mock 风控不通过。

**逻辑真理源（Source of Truth）**  
- 以 C5 的“同一事务”约束为准；测试断言与之一致。

**交付物（Deliverables）**  
- 自动化测试：挂起成功时状态+日志同时存在；回滚时两者均不存在（若实现可测）。  
- 测试说明：如何构造超仓/风控不通过场景。

**验收口径（Acceptance Criteria）**  
- [ ] 挂起成功时，单次查询或同一事务内可读到 PAUSED 与 STRATEGY_PAUSED。  
- [ ] 若实现回滚测试：异常导致回滚后，无“仅有 PAUSED 无日志”或“仅有日志无 PAUSED”。  
- [ ] 测试可重复运行且通过。

---

#### D4. Resume 强校验失败（400 + diff）

**目标**  
- 验证 B1：在强校验不通过时，返回 400 且响应体包含符合“diff 标准公式”的结构化 diff。

**开发范围（必须明确）**  
- 编写测试：构造“不可恢复”的状态（如持仓未校正、风控仍不通过等），调用 `POST /strategy/{id}/resume`，断言 HTTP 400 且 body 中包含约定 diff 字段与结构。  
- 断言 diff 可解析且至少包含文档中规定的关键字段。

**硬性约束（Strong Constraints）**  
- 测试必须覆盖至少一种强校验失败场景；diff 结构必须与 B1 文档一致。  
- 不依赖真实生产数据；使用 fixture 或 mock 构造失败条件。

**逻辑真理源（Source of Truth）**  
- 以 B1 的 diff 标准公式与强校验规则为准。

**交付物（Deliverables）**  
- 自动化测试：一种或多种强校验失败场景，断言 400 + diff 结构与内容。  
- 测试说明：失败场景构造方式。

**验收口径（Acceptance Criteria）**  
- [ ] 强校验失败时返回 400。  
- [ ] 响应体包含 diff，且字段与 B1 文档一致、可解析。  
- [ ] 测试可重复运行且通过。

---

#### D5. Resume 强校验成功

**目标**  
- 验证 B1：强校验通过时，恢复成功、策略状态变为可接收信号，且 STRATEGY_RESUMED 终态日志已落库。

**开发范围（必须明确）**  
- 编写测试：构造“可恢复”的状态（如策略为 PAUSED、持仓已校正、风控通过），调用 `POST /strategy/{id}/resume`，断言 2xx、策略状态更新、且 DB 中存在 STRATEGY_RESUMED 记录。  
- 可选：断言后续信号可被正常处理。

**硬性约束（Strong Constraints）**  
- 测试必须验证状态更新与 C7 终态日志的落库。  
- 使用 fixture 或 test DB，不依赖生产。

**逻辑真理源（Source of Truth）**  
- 以 B1 与 C7 的契约为准。

**交付物（Deliverables）**  
- 自动化测试：恢复成功路径，断言 2xx、状态、STRATEGY_RESUMED 存在。  
- 测试说明：可恢复状态构造方式。

**验收口径（Acceptance Criteria）**  
- [ ] 强校验通过时返回 2xx。  
- [ ] 策略状态变为可接收信号（如 RUNNING）。  
- [ ] DB 中存在对应 STRATEGY_RESUMED 记录。  
- [ ] 测试可重复运行且通过。

---

#### D6. 对账 / 下单互斥测试

**目标**  
- 验证 C2：对账写持仓与下单写持仓互斥，并发时无数据竞争、无重复写入或状态错乱。

**开发范围（必须明确）**  
- 编写测试：并发执行“对账路径”（如 reconcile）与“下单路径”（如 execute decision），多次运行，断言：  
  - position_snapshot 与 trade 记录一致、无重复或丢失；  
  - 无死锁或长时间阻塞（可设超时）；  
  - 锁释放正常（如异常后再次请求可成功）。  
- 可使用多线程/多协程或顺序交替调用模拟并发。

**硬性约束（Strong Constraints）**  
- 测试必须同时触发对账与下单两条路径；断言结果一致性。  
- 不依赖真实交易所；使用 mock 或内存/测试 DB。

**逻辑真理源（Source of Truth）**  
- 以 C1/C2 的互斥语义为准；最终 DB 状态满足业务不变量（如持仓与 trade 一致）。

**交付物（Deliverables）**  
- 自动化测试：并发对账与下单，断言无竞争、无死锁、数据一致。  
- 测试说明：并发方式与断言要点。

**验收口径（Acceptance Criteria）**  
- [ ] 并发执行后，position_snapshot 与 trade 满足业务不变量（如数量、方向一致）。  
- [ ] 无死锁或未释放锁导致的后续请求永久阻塞。  
- [ ] 测试可重复运行且通过（可多次运行以暴露竞态）。

---

## 三、关键约束遵守检查清单

### ✅ 开发项唯一性
- [ ] Phase1.1 开发项仅包含 A1、A2、A3、B1、B2、C1～C7、D1～D6，无合并、拆分、新增、遗漏或编号调整。
- [ ] 执行顺序与本文档“一、推荐执行顺序”一致。

### ✅ 数据库与锁
- [ ] strategy_runtime_state 锁与 TTL 使用 DB 原子操作，默认 TTL 30 秒。
- [ ] trade 表支持 EXTERNAL_SYNC 来源；position_reconcile_log 含 external_trade_id、event_type。
- [ ] 对账与下单路径互斥，持锁边界明确，异常时锁可释放。

### ✅ 事务与一致性
- [ ] 超仓挂起：PAUSED 与 STRATEGY_PAUSED 终态日志同一事务。
- [ ] 恢复成功：状态更新与 STRATEGY_RESUMED 终态日志同一事务或明确定义一致性边界。
- [ ] EXTERNAL_SYNC trade 与 position_snapshot、position_reconcile_log 在同一事务内更新。

### ✅ API 与日志
- [ ] POST /strategy/{id}/resume 强校验未通过返回 400 且带标准 diff；通过则 2xx 并写 STRATEGY_RESUMED。
- [ ] GET /strategy/{id}/status 为只读，与 DB 状态一致。
- [ ] STRATEGY_PAUSED 终态日志含差异快照；STRATEGY_RESUMED 与恢复成功绑定。

---

## 封版声明

> 本 Phase1.1 开发交付包一经确认，即作为 Phase1.1 的**唯一开发真理源**。  
> 在后续开发、测试、验收过程中：  
> - 不允许新增开发项  
> - 不允许删除开发项  
> - 不允许调整模块顺序  
> - 不允许修改模块语义  
>  
> 如需变更，必须进入 Phase1.2 或更高版本。

---

**文档结束**
