# Phase 2.2 B1 证据包：版本与评估历史展示只读 API

**模块**: Phase 2.2 B1
**交付日期**: 2026-03-04
**验收状态**: ✅ 通过

---

## 一、变更文件清单

| 类型 | 文件路径 |
|------|----------|
| 新增 | `src/app/routers/bi.py`（B1 部分） |

## 二、核心实现代码

### 端点

```
GET /api/bi/version_history?strategy_id=&limit=
GET /api/bi/evaluation_history?strategy_id=&from=&to=&limit=
```

**数据来源**（写死）：
- `version_history` ← `Phase 2.1: param_version` 只读查询
- `evaluation_history` ← `Phase 2.0: evaluation_report` 只读查询

### 关键实现

```python
@router.get("/version_history")
async def get_version_history(strategy_id=None, limit=50):
    async with get_db_session() as session:
        stmt = select(ParamVersion)
        # 只读查询，返回字段与 2.1 schema 一致
    return {"items": [{"param_version_id": ..., "release_state": ..., ...}]}

@router.get("/evaluation_history")
async def get_evaluation_history(strategy_id=None, from_=None, to=None, limit=50):
    async with get_db_session() as session:
        stmt = select(EvaluationReport)
        # 只读查询，字段与 2.0 schema 一致
    return {"items": [{"conclusion": ..., "period_start": ..., ...}]}
```

## 三、可复现实跑步骤

```bash
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p4_version_history -v
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py::test_p5_evaluation_history -v
```

**测试结果**：2 passed

## 四、只读边界证据

- `version_history`：仅 `select(ParamVersion)`，无写入
- `evaluation_history`：仅 `select(EvaluationReport)`，无 `Evaluator.evaluate` 调用
- 返回字段严格对齐 2.0/2.1 schema，无 BI 层自造字段
- 无「综合评分」「自动结论」等派生计算

## 五、验收口径逐条对照

| 验收条目 | 状态 | 说明 |
|----------|------|------|
| 可查并展示版本变更列表 | ✅ | test_p4 通过；返回 param_version_id、release_state 等字段 |
| 可查并展示评估报告历史列表 | ✅ | test_p5 通过；返回 conclusion、period_start/end 等字段 |
| 数据一致性：与 2.0/2.1 同条件查询结果一致 | ✅ | 直接从对应表读取，无转换 |
| 只读：未调用评估/发布/回滚/门禁接口 | ✅ | 代码审查：仅 select 查询 |
| 展示内容与 schema 一致，无 BI 自造字段或结论 | ✅ | 字段列表对应 ORM 原始字段 |

---

**证据包状态**: 完整 ✅
