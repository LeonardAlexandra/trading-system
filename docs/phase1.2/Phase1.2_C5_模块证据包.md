# Phase1.2 C5 模块证据包

**模块编号**: C5  
**模块名称**: 健康仪表板（GET /api/health/summary）（T1.2a-4）  
**交付日期**: 2026-02-07

---

## 【A】变更文件清单（新增/修改/删除 + 用途）

| 类型 | 文件路径 | 用途 |
|------|----------|------|
| 新增 | `src/app/routers/health.py` | C5 健康汇总 API：GET /api/health/summary，聚合 SystemMonitor / HealthChecker / LogRepository 与 log 表告警 |
| 修改 | `src/app/main.py` | 注册 health 路由（include_router(health.router)） |
| 新增 | `tests/integration/test_phase12_c5_health_summary.py` | C5 验收测试：200、顶层字段、数据来源真实性、overall_ok 随 check_all 变化、limit 上限 |
| 新增 | `docs/phase1.2/Phase1.2_C5_模块证据包.md` | 本证据包 |

未修改：SystemMonitor、HealthChecker、AlertSystem、LogRepository（C4/C3 已冻结）。

---

## 【B】核心实现代码

### 1. 健康汇总路由与聚合逻辑

**文件**: `src/app/routers/health.py`

- **overall_ok 判定规则（写死）**：`overall_ok = db_ok && exchange_ok && error_rate < threshold`。其中：
  - `db_ok`、`exchange_ok` 来自 `HealthChecker.check_all(session, exchange_adapter)`；
  - `error_rate` 来自 `SystemMonitor.get_metrics(session)["error_rate"]`；
  - `threshold` 默认 `DEFAULT_ERROR_RATE_THRESHOLD = 0.1`，可在证据包说明中配置（当前未扩展 AppConfig，仅代码常量，可后续从配置读取）。
- **metrics**：直接来自 `SystemMonitor.get_metrics()`，至少含 `signals_received_count`、`orders_executed_count`、`error_count`、`error_rate`、`window_seconds`（及 `since`/`until`）。
- **recent_errors**：来自 `LogRepository.query(level="ERROR", limit=N, offset=0)`，N 默认 20；单条含 `created_at`、`component`、`message`（已脱敏，截断 500 字符）、`event_type`；禁止 payload 全量 dump。
- **recent_alerts**：来自 log 表 `event_type='alert_triggered'`（C4 AlertSystem 触发时写入），本模块直接查询 `LogEntry`，未改 LogRepository；条数默认 20；单条含 `level`、`component`、`title`（取 message 前 200 字符）、`message`、`timestamp`（created_at）。

（完整代码见仓库 `src/app/routers/health.py`。）

### 2. 响应模型说明（字段含义）

| 顶层字段 | 类型 | 数据来源 | 说明 |
|----------|------|----------|------|
| overall_ok | boolean | HealthChecker.check_all() + SystemMonitor.get_metrics().error_rate | db_ok && exchange_ok && error_rate < threshold |
| metrics | object | SystemMonitor.get_metrics() | signals_received_count, orders_executed_count, error_count, error_rate, window_seconds, since, until |
| recent_alerts | array | log 表 event_type=alert_triggered | 最近告警，每条含 level, component, title, message, timestamp；默认最多 20 条 |
| recent_errors | array | LogRepository.query(level=ERROR) | 最近 ERROR 日志，每条含 created_at, component, message, event_type；默认最多 20 条 |

### 3. recent_alerts 数据来源与筛选条件

- **优先**：AlertSystem 无“告警历史查询”接口，告警触发时通过 C4 写 log（event_type=`alert_triggered`）。
- **实现选择**：从 log 表按 `event_type='alert_triggered'` 查询，按 `created_at` 倒序，limit 20。筛选条件在证据包中写明：`event_type = 'alert_triggered'`。

### 4. threshold 与 limit 可配置说明

- **error_rate threshold**：默认 0.1，写死在 `src/app/routers/health.py` 的 `DEFAULT_ERROR_RATE_THRESHOLD`。若后续在 AppConfig 中增加 `health_summary.error_rate_threshold`，路由已支持从 `request.app.state.app_config.health_summary` 读取。
- **recent_alerts_limit / recent_errors_limit**：默认 20，常量 `DEFAULT_RECENT_ALERTS_LIMIT`、`DEFAULT_RECENT_ERRORS_LIMIT`；同上，可后续从配置读取。

---

## 【C】测试用例与可复现步骤

- **test_health_summary_200_and_top_level_keys**：GET /api/health/summary 返回 200，JSON 含 overall_ok、metrics、recent_alerts、recent_errors 及 metrics 内 signals_received_count、orders_executed_count、error_count、error_rate。
- **test_health_summary_200_with_same_db**：同上，通过 DATABASE_URL 使用同一测试库验证 200 与结构。
- **test_recent_errors_from_log_repository**：通过 LogRepository.write 写入一条 ERROR log，再调用 API，断言 recent_errors 中出现该条（证明非硬编码）。
- **test_overall_ok_false_when_db_ok_false**：mock HealthChecker.check_all 返回 db_ok=False，调用 _build_summary，断言 overall_ok 为 False。
- **test_overall_ok_false_when_exchange_ok_false**：mock HealthChecker.check_all 返回 exchange_ok=False，断言 overall_ok 为 False。
- **test_recent_errors_and_alerts_have_limit**：调用 API，断言 recent_errors 与 recent_alerts 条数均 ≤ 20。

---

## 【D】测试命令与原始输出

### 测试命令

```bash
cd /Users/zhangkuo/TradingView\ Indicator/trading_system
python -m pytest tests/integration/test_phase12_c5_health_summary.py -v
```

### 原始输出

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
...
tests/integration/test_phase12_c5_health_summary.py::test_health_summary_200_and_top_level_keys PASSED
tests/integration/test_phase12_c5_health_summary.py::test_health_summary_200_with_same_db PASSED
tests/integration/test_phase12_c5_health_summary.py::test_recent_errors_from_log_repository PASSED
tests/integration/test_phase12_c5_health_summary.py::test_overall_ok_false_when_db_ok_false PASSED
tests/integration/test_phase12_c5_health_summary.py::test_overall_ok_false_when_exchange_ok_false PASSED
tests/integration/test_phase12_c5_health_summary.py::test_recent_errors_and_alerts_have_limit PASSED

============================== 6 passed in 0.80s ===============================
```

---

## 【E】与验收口径逐条对照

| 验收口径 | 对应测试/说明 |
|----------|----------------|
| GET /api/health/summary 返回 200 | test_health_summary_200_* |
| JSON 顶层包含 overall_ok / metrics / recent_alerts / recent_errors | test_health_summary_200_and_top_level_keys |
| 通过写入 ERROR log 再调 API，recent_errors 可见变化（数据来源真实） | test_recent_errors_from_log_repository |
| mock HealthChecker.check_all 的 db_ok=false 或 exchange_ok=false，overall_ok 为 false | test_overall_ok_false_when_db_ok_false、test_overall_ok_false_when_exchange_ok_false |
| recent_errors 与 recent_alerts 均有明确 limit，不无上限返回 | test_recent_errors_and_alerts_have_limit（≤20） |
| 数据与 get_metrics/check_all/LogRepository 一致，禁止假数据 | 实现仅调用 SystemMonitor.get_metrics、HealthChecker.check_all、LogRepository.query、LogEntry(event_type=alert_triggered)；无硬编码列表 |

---

**文档结束**
