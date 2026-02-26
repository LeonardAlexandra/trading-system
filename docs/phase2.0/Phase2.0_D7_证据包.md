# Phase 2.0 D7 证据包：技术债专项修复 — TRACE（零写入强锁死整改版）

**模块 ID**: Phase2.0:D7  
**技术债 ID**: TD-TRACE-404-01  
**完成日期**: 2026-02-25

---

## 1. 变更文件与合规核证 (Task 2)

| 文件路径 | SHA256 指纹 | 变更说明 |
| :--- | :--- | :--- |
| `src/schemas/trace.py` | 86dcfe89073d48000944e6d8e9c263f7a51d4e9ddc3a8475fc43148d03226afa | 新增 `TRACE_STATUS_FAILED` 枚举。 |
| `src/services/trace_query_service.py` | 3543ab55d189fb664b9e7c1a29e203772eda67b8c209bac0439b18147ab91992 | 核心链路聚合逻辑重构，支持 FAILED 状态追溯。 |
| `src/app/routers/trace.py` | 1916d82e6e82b8c83e47311e4826c91eacef53ea6c15ebdee310fb5787ae46f5 | **彻底移除 PerfLog 写入**，确保请求链路 0 写入。 |
| `tests/integration/test_failed_trace.py` | (见下文单测代码) | 升级为“零写入”强拦截校验模型（移除白名单）。 |

---

## 2. 核心代码实现全文 (Task 2)

### 2.1 src/app/routers/trace.py (零写入路由实现)
```python
@router.get("/decision/{decision_id}")
async def get_trace_by_decision(decision_id: str):
    """
    按 decision_id 查询全链路追溯结果。
    查不到任何节点返回 404；查到部分或全部返回 200，body 为 TraceResult。
    """
    async with get_db_session() as session:
        svc = TraceQueryService(session)
        result = await svc.get_trace_by_decision_id(decision_id)
    
    if result.trace_status == TRACE_STATUS_NOT_FOUND:
        return Response(content="", status_code=404)
    # AC-D2-TRACE-404-01: FAILED decision 必须返回 200 而非 404
    return result.to_dict()
```

### 2.2 src/services/trace_query_service.py (链路聚合逻辑)
```python
    async def get_trace_by_decision_id(self, decision_id: str) -> TraceResult:
        # ... 数据库查询逻辑 (SELECT ONLY) ...
        # 视为“有 execution”仅当已提交且非 FAILED
        has_execution = (
            (decision_row.local_order_id is not None
             or decision_row.exchange_order_id is not None
             or decision_row.status != RESERVED)
            and decision_row.status != STATUS_FAILED
        )
        # ... 状态判定逻辑 ...
        if decision_row.status == STATUS_FAILED:
            final_status = TRACE_STATUS_FAILED
            fail_reason_val = getattr(decision_row, 'reason', None) or getattr(decision_row, 'last_error', None)
            missing_reason = {"failed_reason": fail_reason_val or "Decision marked as FAILED"}
```

---

## 3. 零写入强锁死单测 (Task 1 & 3)

### 3.1 tests/integration/test_failed_trace.py (全量写拦截)
```python
    # 2. 强锁死只读：注册事件钩子拦截任何写操作 (无白名单)
    write_detected = []
    engine = db_session_factory.kw['bind']
    
    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        stmt_upper = statement.upper().strip()
        # 任务 1: 移除 PERF_LOG 写入白名单，实现全量 SQL 写拦截
        if any(stmt_upper.startswith(prefix) for prefix in ["INSERT", "UPDATE", "DELETE", "REPLACE"]):
            write_detected.append(statement)

    try:
        # 3. 调用 Trace API
        response = client.get(f"/api/trace/decision/{decision_id}")
        
        # 5. 强锁死断言：API 调用期间不得有写操作
        assert len(write_detected) == 0, f"ReadOnly Violation! Detected writes: {write_detected}"
```

---

## 4. 原始测试输出全文 (Task 3)

### 4.1 Pytest 强锁死运行结果
**命令**: `pytest tests/integration/test_failed_trace.py -v`
```text
=============================== test session starts ===============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
collected 1 item                                                                  

tests/integration/test_failed_trace.py::test_failed_decision_trace_200_and_reason PASSED [100%]

================================ 1 passed in 0.36s ================================
```

### 4.2 写入检测输出 (Write Detection)
**验证状态**: `SUCCESS`  
**捕获到的写操作数量**: `0`  
**拦截日志**: `(None)`

---

## 5. 封版门禁状态

**命令**: `python3 scripts/check_tech_debt_gates.py --registry docs/tech_debt_registry.yaml --current-phase 2.0`

**输出实录**:
```text
--- Registry Source Verification ---
RealPath: /Users/zhangkuo/TradingView Indicator/trading_system/docs/tech_debt_registry.yaml
SHA256:   48a1d7d14e14d58531917fc672e609e97de8c509e8b51c4aa27f2a0b2c81ae95
------------------------------------

FAIL: The following blocking tech debt items or gates are NOT DONE (Current Phase: 2.0):
  - ID: TD-HEALTH-OBS-01
    Module: Phase2.0:D8-TECHDEBT-HEALTH
    Status: TODO
    Evidence: []
    Reason: Phase 2.0 item status must be DONE
```
*(证明：TD-TRACE-404-01 已通过 Gate 校验，不再出现在 FAIL 列表中)*
