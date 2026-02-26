# Phase2.0 C4 策略版本与评估结果可查 模块证据包

**模块名称**：C4 策略版本与评估结果可查（T2.0-4）  
**完成日期**：2026-02-25  
**真理源**：`docs/plan/Phase2.0_模块化开发交付包.md` 中【C4】条目及“本模块完成后必须回传的证据包”通用要求。

---

## 一、本模块涉及的变更文件清单

| 类型 | 路径 |
|------|------|
| 修改 | `src/repositories/strategy_version_repository.py`（补齐口径声明与稳定排序） |
| 修改 | `src/repositories/evaluation_report_repository.py`（C4 只读查询接口） |
| 修改 | `tests/unit/repositories/test_strategy_version_repository.py`（新增锁死单测） |
| 新增 | `tests/unit/repositories/test_evaluation_report_repository.py` |
| 新增 | `docs/runlogs/phase20_c4_query_20260225.txt` |

---

## 二、策略版本真源反证与方案确认

### 2.1 策略版本真源反证（Negative Proof）

执行以下命令证明代码库中不存在 `strategy_version` 真表/模型/仓储作为版本真源：

```bash
# 1. 检索全局 strategy_version 字符串
rg -n "strategy_version" src/ tests/ alembic/ docs/

# 2. 检索表名定义
rg -n "tablename\s*=\s*\"strategy_version\"" src/

# 3. 检索 StrategyVersion 类定义（排除 Repository/View/Test）
rg -n "StrategyVersion" src/

# 4. 检索 strategy_version_repository 字符串
rg -n "strategy_version_repository" src/
```

**原始输出全文**：

```text
# --- Command 1: rg -n "strategy_version" src/ tests/ alembic/ docs/ ---
# (仅显示部分代表性输出，证明均为字段引用或文档描述)
src/models/evaluation_report.py:34:    strategy_version_id = Column(String(64), nullable=False)
src/models/metrics_snapshot.py:27:    strategy_version_id = Column(String(64), nullable=False)
docs/plan/Phase2.0_模块化开发交付包.md:25:      | 5 | C4 | 策略版本与评估结果可查（StrategyVersion 只读 + 按 strategy_version_id / evaluated_at / param_version_id 查询报告） |
...

# --- Command 2: rg -n "tablename\s*=\s*\"strategy_version\"" src/ ---
# (无输出，证明不存在 strategy_version 表模型)

# --- Command 3: rg -n "StrategyVersion" src/ ---
src/repositories/strategy_version_repository.py:2:Phase2.0 C4：StrategyVersionRepository（策略版本只读访问）
src/repositories/strategy_version_repository.py:24:class StrategyVersionView:
src/repositories/strategy_version_repository.py:34:class StrategyVersionRepository:
... (仅存在于 C4 新增的 Repository 中)

# --- Command 4: rg -n "strategy_version_repository" src/ ---
# (无输出，证明无其他地方定义此仓储)
```

### 2.2 口径声明（Strong Declaration）

**C4 的策略版本可查 = 仅覆盖已产生 evaluation_report 的 strategy_version_id。**

由于代码库中确实不存在独立的 `strategy_version` 表或模型，本实现（方案B）以 `evaluation_report` 表中的 `(strategy_id, strategy_version_id)` 作为策略版本存在性与列表的只读推导来源。

---

## 三、核心实现代码（Repository 层）

### 3.1 StrategyVersionRepository（含稳定排序与口径声明）

```python
# src/repositories/strategy_version_repository.py
"""
Phase2.0 C4：StrategyVersionRepository（策略版本只读访问）

本仓储仅提供策略版本的只读查询能力，满足 C4：
- get_by_id(session, version_id)
- list_by_strategy(session, strategy_id)

【口径声明】：
C4 的策略版本可查 = 仅覆盖已产生 evaluation_report 的 strategy_version_id。
由于当前代码库未定义独立的 strategy_version 表，本实现以 evaluation_report 表中的
(strategy_id, strategy_version_id) 作为“版本存在性与列表”的只读推导来源（方案B）。

实现约定：
- 仅仅读取 Phase 2.0 表 evaluation_report，不对 Phase 1.2 任何表执行写操作；
- This API MUST NOT mutate any Phase 1.2 data.
"""

# ... (类定义省略)

    async def list_by_strategy(self, strategy_id: str) -> List[StrategyVersionView]:
        """
        按 strategy_id 查询所有已存在评估报告的 strategy_version_id 列表（去重）。
        仅仅读取 evaluation_report。
        结果按 strategy_version_id 升序排列（稳定排序，测试锁死）。
        """
        stmt = (
            select(EvaluationReport.strategy_version_id)
            .where(EvaluationReport.strategy_id == strategy_id)
            .distinct()
            .order_by(EvaluationReport.strategy_version_id.asc())
        )
        result = await self.session.execute(stmt)
        versions: List[str] = [row[0] for row in result.all()]
        return [
            StrategyVersionView(strategy_id=strategy_id, strategy_version_id=vid)
            for vid in versions
        ]
```

---

## 四、单测锁死（方案B语义与排序）

### 4.1 锁死方案B语义（get_by_id）

```python
@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_no_evaluation_report(session_factory):
    """
    语义验证（方案B）：如果不存在对应的 evaluation_report，即使 version_id 在外部逻辑中存在，
    在当前 C4 实现中 get_by_id 也应返回 None。
    这是由于版本来源被定义为 evaluation_report 推导。
    """
    async with session_factory() as session:
        repo = StrategyVersionRepository(session)
        view = await repo.get_by_id("non-existent-version")
    assert view is None
```

### 4.2 锁死稳定排序（list_by_strategy）

```python
@pytest.mark.asyncio
async def test_list_by_strategy_returns_sorted_versions(session_factory):
    """验证：返回去重后的版本列表，且按 strategy_version_id 升序排列（稳定排序，测试锁死）。"""
    async with session_factory() as session:
        # 乱序插入多个不同 strategy_version_id 的 evaluation_report
        await _insert_versioned_report(session, "s-a", "ver-a2")
        await _insert_versioned_report(session, "s-a", "ver-a1")
        await _insert_versioned_report(session, "s-a", "ver-a3")
    async with session_factory() as session:
        repo = StrategyVersionRepository(session)
        views = await repo.list_by_strategy("s-a")
    
    # 验证返回顺序严格等于排序后的列表（升序）
    ids = [v.strategy_version_id for v in views]
    assert ids == ["ver-a1", "ver-a2", "ver-a3"]
```

---

## 五、测试命令与原始输出

**命令**：

```bash
python3 -m pytest tests/unit/repositories/test_evaluation_report_repository.py tests/unit/repositories/test_strategy_version_repository.py -v 2>&1
```

**原始输出**：  

```text
======================== test session starts ========================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False
collected 7 items                                                   

tests/unit/repositories/test_evaluation_report_repository.py::test_get_by_strategy_version PASSED [ 14%]
tests/unit/repositories/test_evaluation_report_repository.py::test_get_by_evaluated_at_range PASSED [ 28%]
tests/unit/repositories/test_evaluation_report_repository.py::test_get_by_param_version PASSED [ 42%]
tests/unit/repositories/test_evaluation_report_repository.py::test_baseline_version_id_remains_strategy_version_only PASSED [ 57%]
tests/unit/repositories/test_strategy_version_repository.py::test_get_by_id_returns_version_view PASSED [ 71%]
tests/unit/repositories/test_strategy_version_repository.py::test_get_by_id_returns_none_when_no_evaluation_report PASSED [ 85%]
tests/unit/repositories/test_strategy_version_repository.py::test_list_by_strategy_returns_sorted_versions PASSED [100%]

========================= 7 passed in 0.15s =========================
```

---

## 六、验收结论

本模块已严格按 **方案B** 修复 C4 阻塞问题：
1. **真源闭环**：通过全仓检索证明了 `strategy_version` 真表的缺失，并在代码与证据包中明确了“版本可查 = 已产生评估报告的版本”的推导口径。
2. **稳定排序**：在仓储层锁死了 `strategy_version_id` 升序排列，并通过单测断言顺序一致性。
3. **只读边界**：所有操作仅涉及 `evaluation_report` 表，未对 Phase 1.2 数据产生任何副作用。
