# Phase1.1 B2 工程级校验证据包（GET /strategy/{id}/status · 只读状态查询）

**模块**: B2 - GET /strategy/{id}/status（只读状态查询，可选但推荐）  
**依据**: 《Phase1.1 开发交付包》B2 条款（§211–239）、验收口径  
**日期**: 2026-02-05  

**说明**: 本证据包仅覆盖 B2「只读状态查询」接口，不涉及 C5 信号拒绝语义；PAUSED 状态信号拒绝回归验证见 C5 / D3 相关证据包。

---

## 0. 条款对齐与任务范围

| 条款来源 | 原文要点 | 本任务实现/验证方式 |
|----------|----------|----------------------|
| B2 开发范围 | 路径参数 `id` 为策略 ID | `GET /strategy/{id}/status`，id 校验空则 422 |
| B2 开发范围 | 返回至少包含策略状态（RUNNING/PAUSED）、与恢复相关的摘要（如是否可 resume、最后对账时间等） | 200 JSON：`strategy_id`, `status`, `can_resume`, `last_reconcile_at` |
| B2 硬性约束 | 返回状态与 DB/运行时真理源一致，不得返回过期状态 | 只读查询 `strategy_runtime_state` + `position_reconcile_log`，无缓存 |
| B2 硬性约束 | 接口为只读，不改变策略状态 | 无写 DB、无调用 resume/reconcile/risk，仅 SELECT |
| B2 验收 | 存在的 strategy id 返回 200 及包含状态与必要摘要的 JSON | test_b2_strategy_status.py: 200 + body 含 status/can_resume/last_reconcile_at |
| B2 验收 | 不存在的 strategy id 返回 404 或约定错误码 | test_b2_strategy_status.py: 404 + detail "strategy not found" |
| B2 验收 | 响应与 DB 当前策略状态一致 | 直查 DB 与 API 返回对比（test_b2_get_status_read_only_no_side_effects） |
| B2 验收 | 接口无副作用（多次调用不改变状态） | 同一 id 连续两次 GET，响应一致且 DB 状态未变 |

---

## 1. 接口约定与响应结构

- **方法/路径**: `GET /strategy/{id}/status`
- **路径参数**: `id` — 策略 ID（必填；空串/仅空白返回 422）
- **真理源**: `strategy_runtime_state`（及 Phase1.1 允许的与状态相关表，如 `position_reconcile_log` 用于最后对账时间）
- **只读**: 不写 DB、不触发 reconcile/risk、不改变任何状态；禁止全量 dump 或敏感/过大 payload

**响应（200）**  
- `strategy_id` (string): 策略 ID  
- `status` (string): 策略状态，`RUNNING` 或 `PAUSED`  
- `can_resume` (boolean): 是否可恢复，`true` 仅当 `status == "PAUSED"`  
- `last_reconcile_at` (string|null): 最近一条对账相关日志时间（ISO8601），无则 `null`  

**错误**  
- 404: 策略不存在，body 含 `detail: "strategy not found"`, `strategy_id`  
- 422: `id` 为空或无效，body 含 `detail`, `code: "INVALID_ID"`  

---

## 2. 目标校验矩阵

| 验证项 | Phase1.1 对应 | 测试位置（文件:用例） | 校验方式 | 结果 |
|--------|----------------|------------------------|----------|------|
| 存在 id 返回 200 + 状态与摘要 | B2 验收 | test_b2_strategy_status.py: test_b2_get_status_200_when_exists_running / _paused | GET 后 assert status_code==200, body 含 strategy_id, status, can_resume, last_reconcile_at | 通过 |
| RUNNING 时 can_resume 为 false | B2 开发范围 | test_b2_strategy_status.py: test_b2_get_status_200_when_exists_running | assert data["can_resume"] is False | 通过 |
| PAUSED 时 can_resume 为 true | B2 开发范围 | test_b2_strategy_status.py: test_b2_get_status_200_when_exists_paused | assert data["can_resume"] is True | 通过 |
| 不存在 id 返回 404 | B2 验收 | test_b2_strategy_status.py: test_b2_get_status_404_when_not_exists | assert status_code==404, detail=="strategy not found" | 通过 |
| 响应与 DB 一致、无副作用 | B2 验收 | test_b2_strategy_status.py: test_b2_get_status_read_only_no_side_effects | 两次 GET 响应一致；直查 state_repo 与 API status 一致 | 通过 |

---

## 3. 关键实现与测试快照

### 3.1 生产实现（仅引用）

**src/app/routers/resume.py**  
- `GET /{id}/status` → `get_strategy_status(id)`  
- 只读：`StrategyRuntimeStateRepository.get_by_strategy_id` + `PositionReconcileLogRepository.list_by_strategy(strategy_id, limit=1)`  
- 无 `session.begin()` 写事务、无调用 `resume_strategy`/reconcile/risk  
- 不存在 → 404；存在 → 200 + `strategy_id`, `status`, `can_resume`, `last_reconcile_at`  

### 3.2 集成测试入口

```bash
cd trading_system && python -m pytest tests/integration/test_b2_strategy_status.py -v --tb=short
```

---

## 4. 测试与实跑输出（原始证据）

```bash
cd trading_system && python -m pytest tests/integration/test_b2_strategy_status.py -v --tb=short
```

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
...
tests/integration/test_b2_strategy_status.py::test_b2_get_status_200_when_exists_running PASSED [ 25%]
tests/integration/test_b2_strategy_status.py::test_b2_get_status_200_when_exists_paused PASSED [ 50%]
tests/integration/test_b2_strategy_status.py::test_b2_get_status_404_when_not_exists PASSED [ 75%]
tests/integration/test_b2_strategy_status.py::test_b2_get_status_read_only_no_side_effects PASSED [100%]

============================== 4 passed in 0.44s ===============================
```

---

## 5. 变更清单（Change Manifest）

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| src/app/routers/resume.py | 新增 | B2 GET /{id}/status 路由，只读查 strategy_runtime_state + position_reconcile_log |
| tests/integration/test_b2_strategy_status.py | 新增 | B2 集成测试：200 RUNNING/PAUSED、404、只读与 DB 一致 |
| docs/Phase1.1_B2_工程级校验证据包.md | 重写 | B2 仅覆盖 GET /strategy/{id}/status，不引入 C5 信号拒绝语义 |

---

## 6. 放行自检

- [x] 严格对齐《Phase1.1 开发交付包》B2（GET /strategy/{id}/status），未引入 C5 信号拒绝语义  
- [x] 存在 id 返回 200 及 status、can_resume、last_reconcile_at 等摘要  
- [x] 不存在 id 返回 404  
- [x] 响应与 DB 一致、接口只读无副作用  
- [x] 工程级校验证据包完整、可复现  

**结论**：B2 GET /strategy/{id}/status（只读状态查询）满足 Phase1.1 交付包与验收口径，可放行。
