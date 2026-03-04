# Phase 2.2 A1 证据包：完整交易统计与权益曲线只读 API

**模块**: Phase 2.2 A1
**交付日期**: 2026-03-04
**验收状态**: ✅ 通过

---

## 一、变更文件清单

| 类型 | 文件路径 |
|------|----------|
| 新增 | `src/app/routers/bi.py` |

## 二、核心实现代码

### 端点

```
GET /api/bi/stats?from=&to=&group_by=&strategy_id=
GET /api/bi/equity_curve?strategy_id=&from=&to=&granularity=
```

**数据来源**（写死）：
- `/api/bi/stats` ← `Phase 2.0: metrics_snapshot` 只读查询
- `/api/bi/equity_curve` ← `Phase 1.2: trade` 表只读累积聚合（realized_pnl）

### 关键实现（`src/app/routers/bi.py`）

```python
@router.get("/stats", summary="完整交易统计 [只读]")
async def get_stats(from_=None, to=None, group_by=None, strategy_id=None):
    async with get_db_session() as session:
        stmt = select(MetricsSnapshot)
        if strategy_id: stmt = stmt.where(MetricsSnapshot.strategy_id == strategy_id)
        if from_dt: stmt = stmt.where(MetricsSnapshot.period_end >= from_dt)
        if to_dt: stmt = stmt.where(MetricsSnapshot.period_start <= to_dt)
        # 只读查询，不写任何表
    return {"note": "本 API 为只读...", "items": [...]}

@router.get("/equity_curve", summary="权益曲线 [只读]")
async def get_equity_curve(strategy_id=None, from_=None, to=None, granularity="day"):
    async with get_db_session() as session:
        stmt = select(Trade).where(Trade.realized_pnl.isnot(None))
        # 累积 realized_pnl，按时间排序
    cumulative += pnl  # 服务端累积，仅只读聚合
```

## 三、可复现实跑步骤

```bash
# 运行 A1 相关测试
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p1_stats_returns_snapshot -v
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p2_equity_curve_cumulative -v
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p8_stats_filter_strategy_id -v
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p11_equity_curve_time_filter -v
```

**测试结果**：4 passed

## 四、只读边界证据

- 所有端点均为 `GET` 方法（`test_p7_all_bi_endpoints_are_get_only` 验证）
- `bi.py` 文件头注释明确写死：「不写入任何 Phase 1.2/2.0/2.1 业务表」「不调用任何写接口」
- 代码中无 `INSERT`/`UPDATE`/`DELETE` 调用，无 `Evaluator.evaluate`、`Optimizer.suggest`、`ReleaseGate` 写接口调用
- 仅使用 `select(MetricsSnapshot)` / `select(Trade)` 只读查询

## 五、验收口径逐条对照

| 验收条目 | 状态 | 说明 |
|----------|------|------|
| 可查完整统计（多维度 from/to/group_by/strategy_id） | ✅ | test_p1, test_p8 通过 |
| 可查资金/权益曲线（strategy_id、from、to、granularity） | ✅ | test_p2, test_p11 通过 |
| 数据一致性：与 2.0 同条件查询结果一致 | ✅ | 直接从 metrics_snapshot 读取，无中间计算 |
| 只读：未调用任何写接口、未写业务表 | ✅ | test_p7 验证 GET-only；代码审查无写操作 |
| 口径：未在 BI 层新增或修改计算公式 | ✅ | 统计数据直接来自 metrics_snapshot 原始字段 |

---

**证据包状态**: 完整 ✅
