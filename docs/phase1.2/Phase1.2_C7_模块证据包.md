# Phase1.2 C7 模块证据包

**模块编号**: C7  
**模块名称**: 性能日志（PerfLogRepository + 关键路径打点）（1.2b-1）  
**模块目标**: 实现性能日志写入与分页查询能力，并在关键链路增加最小必要的性能打点；性能数据落库到 perf_log，与业务审计/错误日志严格分离。

---

## 风险点1 修复说明（perf_log 写入独立事务强落库）

**问题**：原实现中 perf_log 写入依赖调用方 session 生命周期（session.add 后由调用方 commit），若调用方不 commit 或 rollback，则 perf 记录未落库。

**修复**：  
- 新增 **PerfLogWriter**：构造参数为 `session_factory`（如 `get_db_session`），`write_once(component, metric, value, tags=None, created_at=None)` 内自建 session、插入 PerfLogEntry、**显式 `await session.commit()`**，不依赖外部事务。  
- 4 处打点全部改为使用 **PerfLogWriter.write_once**，不再使用 PerfLogRepository.write(session) 依赖调用方 commit。  
- **PerfLogRepository** 保留：仍用于分页 query（可用外部 session）；write 仍存在，供非打点场景或测试使用。  
- perf_log 与 log 表严格分离不变；未新增迁移/表/字段；未引入队列/worker/outbox（风险点2 留 Phase2.x）。

---

## 【A】变更文件清单

| 类型 | 文件路径 | 用途 |
|------|----------|------|
| 新增 | `src/repositories/perf_log_repository.py` | PerfLogRepository（write/query）+ **PerfLogWriter**（write_once 独立事务 commit） |
| 修改 | `src/app/routers/signal_receiver.py` | C7 打点改用 PerfLogWriter.write_once（finally 内）；SignalApplicationService 注入 perf_writer |
| 修改 | `src/application/signal_service.py` | C7 打点改用可选 perf_writer.write_once（决策生成 latency_ms） |
| 修改 | `src/execution/execution_engine.py` | C7 打点改用可选 _perf_writer.write_once（执行提交 latency_ms）；打点前 commit 当前 session 以避免 SQLite 锁 |
| 修改 | `src/execution/execution_worker.py` | 注入 PerfLogWriter(get_db_session) 到 ExecutionEngine |
| 修改 | `src/app/routers/trace.py` | C7 打点改用 PerfLogWriter(get_db_session).write_once（Trace 查询 latency_ms） |
| 新增 | `tests/integration/test_phase12_c7_perf_log.py` | 验收测试：write/query、limit 上限、与 log 分离、**write_once 独立 commit 强落库**、4 处打点 |
| 新增 | `docs/runlogs/c7_pytest.txt` | pytest 原始输出 |
| 新增 | `docs/Phase1.2_C7_模块证据包.md` | 本证据包 |

未新增数据库迁移、表、字段。未修改 A1~A3/C1~C6/B1~B2 既有语义。

---

## 【B】PerfLogRepository 与 PerfLogWriter 实现要点

**文件**: `src/repositories/perf_log_repository.py`

- **PerfLogRepository**：`write(component, metric, value, tags=None, created_at=None)` 仅 `session.add(entry)`，不 commit；`query(...)` 分页查询，limit 上限 QUERY_MAX_LIMIT=1000。  
- **PerfLogWriter**：  
  - 构造：`__init__(self, session_factory: Callable[..., Any])`，session_factory 为返回 async context manager（yield AsyncSession）的可调用对象，如 `get_db_session`。  
  - `write_once(component, metric, value, tags=None, created_at=None)`：  
    - `async with self._session_factory() as session:`  
    - 构造 PerfLogEntry 并 `session.add(entry)`  
    - **`await session.commit()`**  
  - 不写 log 表；与 log 语义分离不变。

（完整代码见仓库 `src/repositories/perf_log_repository.py`。）

---

## 【C】打点位置清单（文件/函数/metric/tags）与实现要点

| 打点位置 | 文件 | 函数/入口 | metric | tags | 实现要点 |
|----------|------|-----------|--------|------|----------|
| 信号接收/解析入口 | `src/app/routers/signal_receiver.py` | `receive_tradingview_webhook` | latency_ms | 无 | t0=time.perf_counter()，writer=PerfLogWriter(get_db_session)；finally 中 await writer.write_once("signal_receiver", "latency_ms", ...) |
| 决策生成 | `src/application/signal_service.py` | `handle_tradingview_signal` | latency_ms | strategy_id | 可选 perf_writer；返回前 await perf_writer.write_once("signal_service", "latency_ms", ..., tags={"strategy_id": ...}) |
| 执行提交 | `src/execution/execution_engine.py` | `execute_one` | latency_ms | decision_id, strategy_id | 可选 _perf_writer；finally 内先 await self._dom_repo.session.commit()，再 await self._perf_writer.write_once(...)；worker 注入 PerfLogWriter(get_db_session) |
| Trace 查询 | `src/app/routers/trace.py` | `get_trace_by_signal` / `get_trace_by_decision` | latency_ms | trace_status | 查询结束后 writer=PerfLogWriter(get_db_session)，await writer.write_once("trace_query", "latency_ms", ..., tags={"trace_status": result.trace_status}) |

---

## 【D】测试用例或可复现实跑步骤

1. **test_perf_log_repository_write_and_query**：PerfLogRepository.write 后 query，断言条数与 value；limit 生效。  
2. **test_perf_log_query_limit_cap**：query(limit=99999)，断言 ≤ QUERY_MAX_LIMIT。  
3. **test_perf_log_no_write_to_log_table**：PerfLogWriter.write_once("sep_test", ...) 后查 log 表，断言 0 条（语义分离）。  
4. **test_perf_log_writer_write_once_commits_independently**：**不显式 commit 外部 session**，仅调用 writer.write_once("strong_commit", "latency_ms", 99.0)；再用新 session query(component="strong_commit")，断言至少 1 条、value≈99（证明强落库）。  
5. **test_signal_receiver_writes_perf_log**：POST /webhook/tradingview，query(component="signal_receiver")，断言至少 1 条。  
6. **test_trace_query_writes_perf_log**：GET /api/trace/signal/xxx，query(component="trace_query")，断言至少 1 条。  
7. **test_execution_engine_writes_perf_log**：ExecutionEngine(..., perf_writer=PerfLogWriter(get_db_session))，execute_one 后 query(component="execution_engine")，断言至少 1 条。  
8. **test_signal_service_writes_perf_when_accepted**：同 webhook 请求，断言 signal_receiver 至少 1 条。

---

## 【E】测试命令与原始输出（完整）

**实际执行的命令**：

```bash
cd /Users/zhangkuo/TradingView\ Indicator/trading_system
python -m pytest tests/integration/test_phase12_c7_perf_log.py -v
```

**命令的真实输出**（见 `docs/runlogs/c7_pytest.txt`，完整 8 条）：

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0 -- /Users/zhangkuo/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 8 items

tests/integration/test_phase12_c7_perf_log.py::test_perf_log_repository_write_and_query PASSED [ 12%]
tests/integration/test_phase12_c7_perf_log.py::test_perf_log_query_limit_cap PASSED [ 25%]
tests/integration/test_phase12_c7_perf_log.py::test_perf_log_no_write_to_log_table PASSED [ 37%]
tests/integration/test_phase12_c7_perf_log.py::test_perf_log_writer_write_once_commits_independently PASSED [ 50%]
tests/integration/test_phase12_c7_perf_log.py::test_signal_receiver_writes_perf_log PASSED [ 62%]
tests/integration/test_phase12_c7_perf_log.py::test_trace_query_writes_perf_log PASSED [ 75%]
tests/integration/test_phase12_c7_perf_log.py::test_execution_engine_writes_perf_log PASSED [ 87%]
tests/integration/test_phase12_c7_perf_log.py::test_signal_service_writes_perf_when_accepted PASSED [100%]

============================== 8 passed in 0.68s ===============================
```

---

## 【F】验收标准逐条对照（YES/NO + 证据）

| 验收口径 | 结果 | 证据 |
|----------|------|------|
| PerfLogRepository 可写入 perf_log，且可按时间/组件/metric 分页查询 | YES | test_perf_log_repository_write_and_query；query 支持 created_at_from/to、component、metric、limit、offset。 |
| 关键路径至少 4 处打点均可产生 perf_log 记录（需可复现证明） | YES | test_signal_receiver_writes_perf_log、test_trace_query_writes_perf_log、test_execution_engine_writes_perf_log、test_signal_service_writes_perf_when_accepted；4 处均改用 PerfLogWriter.write_once。 |
| perf_log 与 log 语义严格分离（无写入 log 表的 perf 指标） | YES | test_perf_log_no_write_to_log_table（write_once 后查 log 表 0 条）；PerfLogWriter 仅写 perf_log。 |
| 单次查询必须有上限（limit 生效），无全表无上限返回 | YES | test_perf_log_query_limit_cap；QUERY_MAX_LIMIT=1000。 |
| perf 写入改为独立事务 commit，不依赖调用方 session | YES | PerfLogWriter.write_once 内自建 session 并 await session.commit()；test_perf_log_writer_write_once_commits_independently 在不 commit 外部 session 下调用 write_once，新 session query 可查到记录。 |

---

## 验收结论

是否满足模块目标：**是**。已实现 PerfLogRepository（write + 分页 query）与 **PerfLogWriter（write_once 独立事务强落库）**；4 处打点均通过 PerfLogWriter.write_once 显式 commit，不依赖调用方事务；perf_log 与 log 表严格分离；未新增迁移/表/字段。风险点1 已修复。测试 8 条全部通过。

**实际执行的命令（逐条）**：  
- `python -m pytest tests/integration/test_phase12_c7_perf_log.py -v`  
- 输出见 `docs/runlogs/c7_pytest.txt`。

**证据包文件路径**：`docs/Phase1.2_C7_模块证据包.md`

**文档结束**
