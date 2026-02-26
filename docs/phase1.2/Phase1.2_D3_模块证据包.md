# Phase1.2 D3 模块证据包：E2E-3 Dashboard 可验证点

## 模块名称与目标

| 项目 | 内容 |
|------|------|
| 模块编号 | D3 |
| 模块名称 | E2E-3 Dashboard 可验证点 |
| 目标 | 验证最小 Dashboard 页面展示与 API 一致，无前端自算指标。 |

---

## 本模块涉及的变更文件清单（新增 / 修改 / 删除）

| 类型 | 路径 |
|------|------|
| 新增 | `tests/integration/test_phase12_d3_dashboard_verification.py` |
| 新增 | `docs/runlogs/d3_e2e3_dashboard_pytest.txt` |
| 新增 | `docs/Phase1.2_D3_模块证据包.md`（本文件） |

无修改：最小 Dashboard 页面与 API 已由 B1/B2 实现并满足 D3 可验证点，本模块仅新增验收测试与证据包。

---

## 本模块的核心实现代码（关键函数或完整文件）

**无。** 本模块为可验证点定义，无代码变更。既有实现位于：

- **页面**：`src/app/routers/dashboard_page.py` — GET /dashboard 返回单页 HTML，内嵌 script 仅 fetch `/api/dashboard/decisions`、`/api/dashboard/executions`、`/api/dashboard/summary`、`/api/health/summary`，按 API 返回的数组/对象原样渲染表格与 JSON，不计算任何 pnl/笔数。
- **API**：`src/app/routers/dashboard.py` — GET /api/dashboard/decisions、executions、summary；`src/app/routers/health.py` — GET /api/health/summary。列表与汇总（trade_count、pnl_sum）均由后端计算并返回，前端仅展示。

---

## 本模块对应的测试用例与可复现实跑步骤

- **测试用例**：`tests/integration/test_phase12_d3_dashboard_verification.py`
  - `test_d3_dashboard_page_returns_200_and_shows_sections`：GET /dashboard 返回 200，HTML 含「决策列表」「执行/成交列表」「汇总」「健康状态」四区块，且含对上述四个 API 的 fetch。
  - `test_d3_dashboard_page_data_from_api_only`：页面汇总区展示 group_key、trade_count、pnl_sum（来自 API）；script 中无 `reduce(`，列表为 row 字段直接展示，无前端自算 pnl/笔数。
  - `test_d3_dashboard_apis_return_consistent_structure`：GET /api/dashboard/decisions、executions、summary 与 GET /api/health/summary 返回 200，结构与页面消费一致（decisions/executions 为数组，summary 为含 group_key/trade_count/pnl_sum 的数组，health 为含 overall_ok 的对象）。
- **可复现步骤**：在项目根目录 `trading_system/` 下执行：  
  `python3 -m pytest tests/integration/test_phase12_d3_dashboard_verification.py -v`

---

## 测试命令与原始输出结果

**实际执行的命令：**

```bash
python3 -m pytest tests/integration/test_phase12_d3_dashboard_verification.py -v
```

**命令的真实输出：**

见 **`docs/runlogs/d3_e2e3_dashboard_pytest.txt`**。内容为完整 pytest 输出：3 collected，3 passed，约 1.00s。

---

## 与本模块 Acceptance Criteria / 可验证点的逐条对照说明

### 验收口径（交付包原文）

- 打开最小 Dashboard 页面时，展示最近决策/执行/成交、汇总、健康指标。
- 页面数据与 GET /api/dashboard/* 及 GET /api/health/summary 返回数据一致。
- 禁止前端自算 pnl/笔数。

### 可验证点逐条对照

| 可验证点 | 结果 | 证据 |
|----------|------|------|
| 打开最小 Dashboard 页面，展示最近决策/执行/成交、汇总、健康指标 | YES | test_d3_dashboard_page_returns_200_and_shows_sections：GET /dashboard 200，HTML 含「决策列表」「执行/成交列表」「汇总」「健康状态」四区块，且含对 /api/dashboard/decisions、executions、summary 与 /api/health/summary 的 fetch。 |
| 页面数据与 GET /api/dashboard/* 及 GET /api/health/summary 返回一致 | YES | 页面 script 仅 fetch 上述接口并将返回结果传入 renderDecisions/renderExecutions/renderSummary/renderHealth，无二次计算；test_d3_dashboard_apis_return_consistent_structure 断言 API 返回数组/对象结构符合页面消费（decisions/executions 数组，summary 含 group_key/trade_count/pnl_sum，health 含 overall_ok）。 |
| 无前端自算 pnl/笔数 | YES | test_d3_dashboard_page_data_from_api_only：断言 HTML script 中无 `reduce(`，汇总区使用 API 返回的 group_key、trade_count、pnl_sum 直接展示；列表为 row[k] 展示 API 行数据，无前端聚合。 |

### 验收结论

- 打开最小 Dashboard 页面时展示最近决策/执行/成交、汇总、健康指标：**满足**（四区块 + 四 API 调用，测试通过）。
- 页面数据与 GET /api/dashboard/* 及 GET /api/health/summary 一致：**满足**（页面仅展示 API 返回，测试断言 API 结构与页面消费一致）。
- 禁止前端自算 pnl/笔数：**满足**（script 无 reduce，trade_count/pnl_sum 来自 API，测试通过）。

---

**证据包完成。D3 E2E-3 Dashboard 可验证点已逐条落实并可通过上述测试与 runlog 复现。**
