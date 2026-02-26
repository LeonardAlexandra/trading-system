# Phase1.2 C4 模块证据包

**模块**：监控与告警（SystemMonitor / HealthChecker / AlertSystem）（T1.2a-3）

---

## 【A】变更文件清单（新增/修改/删除 + 用途）

| 类型 | 路径 | 用途 |
|------|------|------|
| 新增 | `src/monitoring/__init__.py` | 监控包占位 |
| 新增 | `src/monitoring/models.py` | HealthResult、Alert 数据结构（蓝本 D.4） |
| 新增 | `src/monitoring/system_monitor.py` | SystemMonitor.get_metrics()，真实 DB 计数 |
| 新增 | `src/monitoring/health_checker.py` | HealthChecker.check_all()，db_ok/exchange_ok/strategy_status |
| 新增 | `src/monitoring/alert_system.py` | AlertSystem.evaluate_rules()，规则评估、写 log、可选邮件、冷却 60s、SMTP 降级 |
| 新增 | `config/alert_rules.example.yaml` | 告警规则配置示例（YAML） |
| 新增 | `tests/integration/test_phase12_c4_monitoring.py` | C4 验收测试（metrics/check_all/evaluate_rules/冷却/SMTP 降级） |
| 新增 | `docs/Phase1.2_C4_模块证据包.md` | 本证据包 |

**未修改**：A1～A3、C1、C2、C3；未实现 /api/health/summary（C5）；未新增 DB 迁移/表。

---

## 【B】核心实现代码全文

### B.1 SystemMonitor 全文

见仓库文件：`src/monitoring/system_monitor.py`。

- `get_metrics(session, window_seconds=None)`：在时间窗口内对 `dedup_signal`、`trade`、`log`（level=ERROR）做 `count()` 查询，返回 `signals_received_count`、`orders_executed_count`、`error_count`、`error_rate`（每小时错误数）、`window_seconds`、`since`、`until`。默认窗口 `DEFAULT_METRICS_WINDOW_SECONDS = 3600`，可配置。

### B.2 HealthChecker 全文

见仓库文件：`src/monitoring/health_checker.py`。

- `check_all(session, exchange_adapter)`：  
  - `db_ok`：执行 `SELECT 1` 验证 DB 连通性。  
  - `exchange_ok`：调用 `exchange_adapter.get_account_info()`，异常则 False。  
  - `strategy_status`：查询 `strategy_runtime_state` 表，返回 `strategies`（strategy_id -> status）与 `summary`。  
- 仅只读检查，不修改业务/风控/执行逻辑。

### B.3 AlertSystem 全文（含冷却去重、SMTP 降级）

见仓库文件：`src/monitoring/alert_system.py`。

- `AlertSystem(rules, send_email=None)`：规则为 list[dict]（rule_id, condition, level, component, title, message_template 等）；可选 `send_email(to, subject, body)`。  
- `evaluate_rules(session, metrics, health, log_repo)`：  
  - 用 `_eval_condition(condition, metrics, health)` 求值（支持 `db_ok == false`、`exchange_ok == false`、`error_rate > 0.1`、`error_count > N`）。  
  - 触发时：生成 Alert，写入 LogRepository（level=ERROR/WARNING 按规则），可选调用 `send_email`。  
- **冷却（写死）**：`ALERT_COOLDOWN_SECONDS = 60`；同 `rule_id` 在 60 秒内只触发一次（`_last_fired[rule_id]` 记录时间戳，超过 60 秒才再次写 log/发邮件并加入返回列表）。  
- **SMTP 降级**：`send_email` 若抛异常，仅捕获不抛，不崩溃，log 已在上方写入。

---

## 【C】告警规则配置

### 配置文件示例（YAML）全文

见仓库文件：`config/alert_rules.example.yaml`。

```yaml
# Phase1.2 C4 告警规则示例（YAML）
rules:
  - rule_id: db_down
    condition: db_ok == false
    level: CRITICAL
    component: health
    title: 数据库不可用
    message_template: 健康检查发现 db_ok=false，请检查数据库连通性。

  - rule_id: exchange_down
    condition: exchange_ok == false
    level: CRITICAL
    component: health
    title: 交易所/适配器不可达
    message_template: 健康检查发现 exchange_ok=false。

  - rule_id: error_rate_high
    condition: error_rate > 0.1
    level: WARNING
    component: metrics
    title: 错误率过高
    message_template: 窗口内 error_rate={error_rate}，error_count={error_count}。

  - rule_id: error_count_threshold
    condition: error_count > 5
    level: IMPORTANT
    component: metrics
    title: 错误条数超阈值
    message_template: 窗口内 error_count={error_count}。
```

### 规则解释（阈值、level、触发条件）

| rule_id | condition | level | 触发条件 |
|---------|-----------|--------|----------|
| db_down | db_ok == false | CRITICAL | HealthChecker 检测到 DB 不可用 |
| exchange_down | exchange_ok == false | CRITICAL | 交易所/适配器 get_account_info 失败 |
| error_rate_high | error_rate > 0.1 | WARNING | 窗口内每小时错误数 > 0.1 |
| error_count_threshold | error_count > 5 | IMPORTANT | 窗口内 ERROR 条数 > 5 |

---

## 【D】数据来源说明（禁止假数据的证明）

### metrics 四字段分别从哪里来

| 字段 | 来源 | 说明 |
|------|------|------|
| signals_received_count | DB 表 `dedup_signal` | `SELECT count(*) FROM dedup_signal WHERE created_at >= since`（since = now - window_seconds） |
| orders_executed_count | DB 表 `trade` | `SELECT count(*) FROM trade WHERE created_at >= since` |
| error_count | DB 表 `log` | `SELECT count(*) FROM log WHERE created_at >= since AND created_at <= now AND level = 'ERROR'` |
| error_rate | 由 error_count 与窗口折算 | `error_count / max(window_seconds/3600, 1/3600)`，即每小时错误数 |

窗口默认 3600 秒，可配置；返回中带 `window_seconds`、`since`、`until` 便于复现。

### db_ok / exchange_ok 的真实检查方式

- **db_ok**：在传入的 `session` 上执行 `SELECT 1`，成功则 True，异常则 False。  
- **exchange_ok**：调用 `exchange_adapter.get_account_info()`，无异常则 True，异常则 False（真实调用适配器，Paper 或真实交易所一致）。

---

## 【E】测试用例/可复现实跑步骤

- **用例 1**：get_metrics() 返回 dict 且含 signals_received_count、orders_executed_count、error_count、error_rate、window_seconds。  
- **用例 2**：插入 dedup_signal/trade/ERROR log 后再次 get_metrics()，计数增加，证明非硬编码。  
- **用例 3**：check_all() 在 DB 正常、PaperExchangeAdapter 正常时 db_ok=True、exchange_ok=True，strategy_status 含 strategies。  
- **用例 4**：Adapter 的 get_account_info 抛异常时 exchange_ok=False。  
- **用例 5**：strategy_status 有 strategies 与 summary 结构。  
- **用例 6**：规则 db_ok==false 触发 CRITICAL Alert，且 LogRepository 中可查到对应 ERROR 日志。  
- **用例 7**：规则 error_rate > 0.1 触发 WARNING Alert，且 log 表有记录。  
- **用例 8**：send_email 抛异常时 evaluate_rules 不抛，log 仍写入（SMTP 降级）。  
- **用例 9**：同 rule_id 在 60 秒内第二次 evaluate_rules 不再次触发（返回 0 条），证明冷却。

**可复现步骤**：在项目根目录执行：

```bash
cd trading_system
python -m pytest tests/integration/test_phase12_c4_monitoring.py -v
```

---

## 【F】测试命令与原始输出（完整，不总结）

```text
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && python -m pytest tests/integration/test_phase12_c4_monitoring.py -v 2>&1

============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0 -- /Users/zhangkuo/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 9 items

tests/integration/test_phase12_c4_monitoring.py::test_get_metrics_returns_required_fields PASSED [ 11%]
tests/integration/test_phase12_c4_monitoring.py::test_get_metrics_data_from_real_queries PASSED [ 22%]
tests/integration/test_phase12_c4_monitoring.py::test_check_all_db_ok PASSED [ 33%]
tests/integration/test_phase12_c4_monitoring.py::test_check_all_exchange_down_when_adapter_raises PASSED [ 44%]
tests/integration/test_phase12_c4_monitoring.py::test_check_all_strategy_status_structure PASSED [ 55%]
tests/integration/test_phase12_c4_monitoring.py::test_evaluate_rules_fires_on_db_down PASSED [ 66%]
tests/integration/test_phase12_c4_monitoring.py::test_evaluate_rules_error_rate_threshold PASSED [ 77%]
tests/integration/test_phase12_c4_monitoring.py::test_smtp_failure_fallback_only_log PASSED [ 88%]
tests/integration/test_phase12_c4_monitoring.py::test_alert_cooldown_same_rule_once_per_minute PASSED [100%]

============================== 9 passed in 0.36s ==============================
```

---

## 【G】Acceptance Criteria 逐条对照（YES/NO + 证据）

| 验收口径 | 结果 | 证据 |
|----------|------|------|
| get_metrics() 返回含 signals_received_count 等 | YES | test_get_metrics_returns_required_fields：断言 dict 含 signals_received_count、orders_executed_count、error_count、error_rate、window_seconds。 |
| get_metrics() 数据非硬编码 | YES | test_get_metrics_data_from_real_queries：插入 signal/trade/ERROR log 后计数增加。 |
| check_all() 返回各组件状态（db_ok, exchange_ok, strategy_status） | YES | test_check_all_db_ok、test_check_all_exchange_down_when_adapter_raises、test_check_all_strategy_status_structure：db_ok/exchange_ok 与 strategy_status 含 strategies/summary。 |
| 触发规则后存在 Alert 与 log | YES | test_evaluate_rules_fires_on_db_down、test_evaluate_rules_error_rate_threshold：返回 list[Alert] 非空，且 LogRepository.query 可查到对应 ERROR/WARNING 日志。 |
| 邮件失败降级（SMTP 失败仅写 log，不崩溃） | YES | test_smtp_failure_fallback_only_log：send_email 抛异常时 evaluate_rules 不抛，log 仍写入。 |
| 冷却去重（同类型 1 分钟内只告警一次） | YES | test_alert_cooldown_same_rule_once_per_minute：同一 rule 连续两次 evaluate_rules 第二次返回 0 条；新实例或 60s 后可再次触发。 |

---

以上为 Phase1.2 C4 模块证据包全文。C4 仅实现 SystemMonitor、HealthChecker、AlertSystem，未实现 /api/health/summary（C5），未新增迁移/表，数据均来自真实查询与检查。
