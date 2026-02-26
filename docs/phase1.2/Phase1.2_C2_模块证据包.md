# Phase1.2 C2 模块证据包

**模块**：全链路追溯（TraceQueryService + TraceResult + HTTP 路由）（T1.2a-1）

---

## 【A】变更文件清单（新增/修改/删除 + 用途）

| 类型 | 路径 | 用途 |
|------|------|------|
| 新增 | `src/schemas/trace.py` | TraceResult、DecisionSummary、trace_status/missing_nodes 常量（蓝本 D.2） |
| 新增 | `src/services/__init__.py` | 服务包占位 |
| 新增 | `src/services/trace_query_service.py` | TraceQueryService：get_trace_by_signal_id、get_trace_by_decision_id、list_decisions、list_decisions_by_time、get_recent_n |
| 新增 | `src/app/routers/trace.py` | HTTP 路由 GET /api/trace/signal/{signal_id}、GET /api/trace/decision/{decision_id} |
| 修改 | `src/app/main.py` | 注册 trace 路由 |
| 新增 | `tests/integration/test_phase12_c2_trace.py` | C2 验收测试（COMPLETE/PARTIAL/NOT_FOUND、HTTP 404/200、list/get_recent_n） |
| 新增 | `docs/Phase1.2_C2_模块证据包.md` | 本证据包 |

**未修改**：A1～A3、C1（表结构/迁移/Repository/写入失败策略）；未新增迁移或表。

---

## 【B】核心实现代码全文

### B.1 TraceQueryService 全文

见仓库文件：`src/services/trace_query_service.py`（约 375 行）。  
要点摘要：

- `get_trace_by_signal_id(signal_id)`：先查 dedup_signal，无则 NOT_FOUND；再按 signal_id 查 decision_order_map，无则 PARTIAL（仅 signal）；再查 decision_snapshot、判 execution（RESERVED 且无 order_id 视为缺 execution）、trade，拼 TraceResult。
- `get_trace_by_decision_id(decision_id)`：先查 decision_order_map，无则 NOT_FOUND；再按 signal_id 查 signal、snapshot、execution、trade，拼 TraceResult。
- execution 节点：不是独立表；来自 decision_order_map 同一行（与 decision 同行字段）。判定规则：若 (local_order_id 或 exchange_order_id 非空) 或 (status != RESERVED) ⇒ 视为存在 execution；否则（status==RESERVED 且两个 order_id 均为空）⇒ missing_nodes 加 execution。
- `list_decisions(strategy_id, start_ts, end_ts, limit, offset)`、`list_decisions_by_time(start_ts, end_ts, limit, offset)`、`get_recent_n(n, strategy_id?)`：均查 decision_order_map，映射为 DecisionSummary 列表。

### B.2 TraceResult / DecisionSummary 数据结构定义全文

见仓库文件：`src/schemas/trace.py`。

```python
# 常量（写死）
TRACE_STATUS_COMPLETE = "COMPLETE"
TRACE_STATUS_PARTIAL = "PARTIAL"
TRACE_STATUS_NOT_FOUND = "NOT_FOUND"
MISSING_NODE_SIGNAL = "signal"
MISSING_NODE_DECISION = "decision"
MISSING_NODE_DECISION_SNAPSHOT = "decision_snapshot"
MISSING_NODE_EXECUTION = "execution"
MISSING_NODE_TRADE = "trade"
ALL_MISSING_NODES = ["signal", "decision", "decision_snapshot", "execution", "trade"]

@dataclass
class DecisionSummary:
    decision_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: Optional[Any] = None
    created_at: Optional[datetime] = None
    status: Optional[str] = None
    signal_id: Optional[str] = None

@dataclass
class TraceResult:
    trace_status: str
    missing_nodes: List[str]
    missing_reason: Optional[Dict[str, str]] = None
    signal: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    decision_snapshot: Optional[Dict[str, Any]] = None
    execution: Optional[Dict[str, Any]] = None
    trade: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]: ...
```

### B.3 HTTP 路由实现全文

见仓库文件：`src/app/routers/trace.py`。

```python
router = APIRouter(prefix="/api/trace", tags=["trace"])

@router.get("/signal/{signal_id}")
async def get_trace_by_signal(signal_id: str):
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_signal_id(signal_id)
    if result.trace_status == TRACE_STATUS_NOT_FOUND:
        return Response(content="", status_code=404)
    return result.to_dict()

@router.get("/decision/{decision_id}")
async def get_trace_by_decision(decision_id: str):
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_decision_id(decision_id)
    if result.trace_status == TRACE_STATUS_NOT_FOUND:
        return Response(content="", status_code=404)
    return result.to_dict()
```

---

## 【C】数据映射说明（signal/decision/snapshot/execution/trade 的来源与关联键）

| 节点 | 来源表/来源 | 关联键 | 说明 |
|------|-------------|--------|------|
| **signal** | `dedup_signal` | `signal_id` (PK) | 通过 DedupSignalRepository.get(signal_id)；按 signal 查时直接查；按 decision 查时用 decision.signal_id 反查。 |
| **decision** | `decision_order_map` | `decision_id` (PK)、`signal_id` | 按 signal_id 查：`select(DecisionOrderMap).where(signal_id=signal_id)`；按 decision_id 查：DecisionOrderMapRepository.get_by_decision_id(decision_id)。 |
| **decision_snapshot** | `decision_snapshot` (A1 表) | `decision_id` (unique) | DecisionSnapshotRepository.get_by_decision_id(decision_id)。 |
| **execution** | `decision_order_map` 同一行 | `decision_id` | 与 decision 同表同行；字段：execution_id=decision_id, order_id=local_order_id 或 exchange_order_id, status。视为“存在”当且仅当：local_order_id 或 exchange_order_id 非空，或 status != RESERVED。 |
| **trade** | `trade` | `decision_id` | `select(Trade).where(Trade.decision_id == decision_id).limit(1)`；trade 表字段含 decision_id、execution_id、symbol、side、quantity、price、realized_pnl 等。 |

**关联链**：signal_id → dedup_signal(signal)；signal_id → decision_order_map(decision)；decision_id → decision_snapshot、decision_order_map(execution)、trade。

---

## 【D】测试用例/可复现实跑步骤

- **用例 1**：完整链路（signal + decision + snapshot + execution + trade）→ trace_status=COMPLETE，missing_nodes=[]，五节点均有。  
- **用例 2**：缺 execution 与 trade（decision 保持 RESERVED、无 order_id，无 trade 记录）→ PARTIAL，missing_nodes 含 execution、trade，返回 signal/decision/snapshot。  
- **用例 3**：缺 decision_snapshot（有 decision、execution、trade，无 snapshot）→ PARTIAL，missing_nodes 含 decision_snapshot。  
- **用例 4**：缺 trade（有 decision、snapshot、execution，无 trade）→ PARTIAL，missing_nodes 含 trade。  
- **用例 5**：不存在的 signal_id → NOT_FOUND，missing_nodes 为五节点，无任何节点对象。  
- **用例 6**：不存在的 decision_id → NOT_FOUND。  
- **用例 7**：HTTP GET /api/trace/signal/non-existent-id → 404。  
- **用例 8**：HTTP GET /api/trace/decision/non-existent-id → 404。  
- **用例 9**：HTTP GET /api/trace/signal/{signal_id} 且该 signal 存在但缺 snapshot/execution/trade → 200，body 含 trace_status=PARTIAL、missing_nodes、signal、decision。  
- **用例 10**：按 decision_id 查询且 decision 存在、signal 缺失 → PARTIAL，missing_nodes 含 signal。  
- **用例 11**：list_decisions、list_decisions_by_time、get_recent_n 返回 DecisionSummary 列表。

**可复现步骤**：在项目根目录执行：

```bash
cd trading_system
python -m pytest tests/integration/test_phase12_c2_trace.py -v
```

测试使用临时 SQLite 库（tmp_path），不依赖线上数据。

---

## 【E】测试命令与原始输出（完整，不总结）

```text
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && python -m pytest tests/integration/test_phase12_c2_trace.py -v 2>&1

============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0 -- /Users/zhangkuo/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 11 items

tests/integration/test_phase12_c2_trace.py::test_trace_complete_full_chain PASSED [  9%]
tests/integration/test_phase12_c2_trace.py::test_trace_partial_missing_execution_and_trade PASSED [ 18%]
tests/integration/test_phase12_c2_trace.py::test_trace_partial_missing_decision_snapshot PASSED [ 27%]
tests/integration/test_phase12_c2_trace.py::test_trace_partial_missing_trade PASSED [ 36%]
tests/integration/test_phase12_c2_trace.py::test_trace_not_found_signal_id PASSED [ 45%]
tests/integration/test_phase12_c2_trace.py::test_trace_not_found_decision_id PASSED [ 54%]
tests/integration/test_phase12_c2_trace.py::test_http_trace_signal_404_when_not_found PASSED [ 63%]
tests/integration/test_phase12_c2_trace.py::test_http_trace_decision_404_when_not_found PASSED [ 72%]
tests/integration/test_phase12_c2_trace.py::test_http_trace_200_with_trace_status_when_partial PASSED [ 81%]
tests/integration/test_phase12_c2_trace.py::test_list_decisions_and_get_recent_n PASSED [ 90%]
tests/integration/test_phase12_c2_trace.py::test_get_trace_by_decision_id_partial PASSED [100%]

============================== 11 passed in 0.73s ==============================
```

---

## 【F】Acceptance Criteria 逐条对照（YES/NO + 证据）

| 验收口径 | 结果 | 证据 |
|----------|------|------|
| 完整链路：trace_status=COMPLETE，missing_nodes 为空，五节点均有 | YES | test_trace_complete_full_chain：插入 signal、decision(FILLED+order_id)、snapshot、trade，断言 result.trace_status==COMPLETE、missing_nodes==[]、五节点非空。 |
| 缺 execution：PARTIAL，missing_nodes 含 execution/trade，返回 signal/decision/snapshot | YES | test_trace_partial_missing_execution_and_trade：decision 保持 RESERVED、无 order_id，有 snapshot、无 trade；断言 PARTIAL、execution/trade in missing_nodes、signal/decision/snapshot 非空、execution/trade 为 None。 |
| 缺 decision_snapshot：PARTIAL，missing_nodes 含 decision_snapshot | YES | test_trace_partial_missing_decision_snapshot：有 decision、execution、trade，不写 snapshot；断言 PARTIAL、decision_snapshot in missing_nodes、decision_snapshot is None。 |
| 缺 trade：PARTIAL，missing_nodes 含 trade | YES | test_trace_partial_missing_trade：有 decision、snapshot、execution，不写 trade；断言 PARTIAL、trade in missing_nodes、trade is None。 |
| 不存在的 signal_id：404 或 NOT_FOUND+无节点 | YES | test_trace_not_found_signal_id：断言 trace_status==NOT_FOUND、五节点均为 None；test_http_trace_signal_404_when_not_found：GET 不存在的 signal_id 返回 404。 |
| 任一部分存在时 HTTP 200 且 body 非空、含 trace_status | YES | test_http_trace_200_with_trace_status_when_partial：插入 signal+decision（无 snapshot/execution/trade），GET /api/trace/signal/{id} 断言 status_code==200、body 含 trace_status、missing_nodes、signal、decision。 |

---

## 【G】“链路不完整规范”专项证据

至少 2 个 PARTIAL 场景的响应样例（含 trace_status 与 missing_nodes）。

### G.1 缺 execution 与 trade（PARTIAL）

**场景**：存在 signal、decision（RESERVED、无 order_id）、decision_snapshot；无 execution（未提交）、无 trade。

**响应 body 示例（200）**：

```json
{
  "trace_status": "PARTIAL",
  "missing_nodes": ["execution", "trade"],
  "signal": {
    "signal_id": "sig-no-exec",
    "received_at": "2025-02-07T12:00:00+00:00",
    "first_seen_at": "2025-02-07T12:00:00+00:00",
    "processed": false,
    "created_at": "2025-02-07T12:00:00+00:00",
    "symbol": "BTCUSDT",
    "action": "BUY"
  },
  "decision": {
    "decision_id": "dec-no-exec",
    "strategy_id": "strat-c2",
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": "0.01",
    "signal_id": "sig-no-exec",
    "status": "RESERVED",
    "created_at": "2025-02-07T12:00:00+00:00",
    "reserved_at": "2025-02-07T12:00:00+00:00",
    "reason": null
  },
  "decision_snapshot": {
    "id": 1,
    "decision_id": "dec-no-exec",
    "strategy_id": "strat-c2",
    "created_at": "2025-02-07T12:00:00+00:00",
    "signal_state": {"signal_id": "sig-no-exec"},
    "position_state": {},
    "risk_check_result": {"allowed": true},
    "decision_result": {"decision_id": "dec-no-exec"}
  }
}
```

（无 `execution`、`trade` 字段；missing_nodes 为 `["execution", "trade"]`。）

### G.2 缺 decision_snapshot（PARTIAL）

**场景**：存在 signal、decision、execution（FILLED+order_id）、trade；无 decision_snapshot。

**响应 body 示例（200）**：

```json
{
  "trace_status": "PARTIAL",
  "missing_nodes": ["decision_snapshot"],
  "signal": {
    "signal_id": "sig-no-snap",
    "received_at": "2025-02-07T12:00:00+00:00",
    "symbol": "BTCUSDT",
    "action": "BUY"
  },
  "decision": {
    "decision_id": "dec-no-snap",
    "strategy_id": "strat-c2",
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": "0.01",
    "signal_id": "sig-no-snap",
    "status": "FILLED"
  },
  "execution": {
    "execution_id": "dec-no-snap",
    "decision_id": "dec-no-snap",
    "order_id": "loc-2",
    "local_order_id": "loc-2",
    "exchange_order_id": "ex-2",
    "status": "FILLED"
  },
  "trade": {
    "trade_id": "tr-no-snap-1",
    "decision_id": "dec-no-snap",
    "execution_id": "dec-no-snap",
    "strategy_id": "strat-c2",
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": "0.01",
    "price": "50000",
    "realized_pnl": "0",
    "executed_at": "2025-02-07T12:00:00+00:00"
  }
}
```

（无 `decision_snapshot` 字段；missing_nodes 为 `["decision_snapshot"]`。）

---

以上为 Phase1.2 C2 模块证据包全文。C2 仅实现全链路追溯查询与 HTTP 路由，未修改 A1～A3、C1，未实现 C3～C9、B、D，未引入 Phase 2.x 能力。
