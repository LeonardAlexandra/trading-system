# Phase2.0 C2 MetricsCalculator 模块证据包

**模块名称**：C2 MetricsCalculator（T2.0-2）  
**完成日期**：2026-02-25  
**真理源**：`docs/plan/Phase2.0_模块化开发交付包.md` 中【C2】条目及“本模块完成后必须回传的证据包”通用要求。

---

## 一、本模块涉及的变更文件清单

| 类型 | 路径 |
|------|------|
| 新增 | `src/phase2/__init__.py` |
| 新增 | `src/phase2/metrics_result.py` |
| 新增 | `src/phase2/metrics_calculator.py` |
| 新增 | `tests/unit/phase2/test_metrics_calculator.py` |
| 新增 | `docs/runlogs/phase20_c2_metrics_20260214.txt` |
| 新增 | `docs/runlogs/phase20_c2_metrics_20260225.txt` |
| 修改 | `src/repositories/trade_repo.py`（新增只读方法 `list_by_strategy_and_executed_time_range`，供 C2 只读 trade 表） |

无删除文件。

---

## 二、核心实现代码

### 2.1 MetricsResult（B.2 五指标，无 conclusion/baseline）

```python
# src/phase2/metrics_result.py
@dataclass(frozen=True)
class MetricsResult:
    trade_count: int
    win_rate: Optional[Decimal]
    realized_pnl: Decimal
    # max_drawdown：基于逐笔累计权益曲线的最大回撤；无 trade 或仅一笔 trade 时固定为 Decimal("0")。
    max_drawdown: Decimal
    avg_holding_time_sec: Optional[Decimal]
```

### 2.2 MetricsCalculator.compute 与 B.2 口径

```python
# src/phase2/metrics_calculator.py（关键片段）
async def compute(
    self,
    strategy_id: str,
    strategy_version_id: str,
    param_version_id: Optional[str],
    period_start: datetime,
    period_end: datetime,
) -> MetricsResult:
    trades = await self._trade_repo.list_by_strategy_and_executed_time_range(
        strategy_id, period_start, period_end
    )
    return _compute_b2_metrics(trades)
```

B.2 口径（写死，在 `_compute_b2_metrics` 中）：

- **trade_count** = len(trades)，无 trade 时为 0  
- **win_rate** = 盈利笔数/总笔数，无 trade 时为 None  
- **realized_pnl** = SUM(realized_pnl)，无 trade 时为 Decimal("0")  
- **max_drawdown** = 按 executed_at 排序后逐笔累计权益曲线，取 peak - running 的最大值；无 trade 或仅一笔时固定为 Decimal("0")  
- **avg_holding_time_sec** = Trade 表无 open_time/close_time，故为 None（B.2：缺少时间字段时为 NULL）

### 2.4 版本口径声明（Option B）

- 当前 Phase 1.2 `trade` 表模型中**不存在** `strategy_version_id` 或等价版本字段，无法在 trade 层按版本做过滤。  
- `MetricsCalculator.compute(strategy_id, strategy_version_id, param_version_id?, ...)` 接受版本入参，但在 C2 中仅作为“调用上下文”，**不参与 trade 查询条件**；版本维度将在后续写入 `metrics_snapshot`（C1/C3/C4）时由调用方落地。  
- 关键代码片段与测试：

```python
# src/phase2/metrics_calculator.py（关键片段）
async def compute(
    self,
    strategy_id: str,
    strategy_version_id: str,
    param_version_id: Optional[str],
    period_start: datetime,
    period_end: datetime,
) -> MetricsResult:
    """
    strategy_version_id / param_version_id 为入参（当前 trade 表无此列，仅按 strategy_id + 时间范围取 trade）。
    """
    trades = await self._trade_repo.list_by_strategy_and_executed_time_range(
        strategy_id, period_start, period_end
    )
    return _compute_b2_metrics(trades)
```

```python
# tests/unit/phase2/test_metrics_calculator.py 片段
calls = []

original_list = repo.list_by_strategy_and_executed_time_range

async def _spy_list_by_strategy_and_executed_time_range(
    strategy_id: str,
    period_start: datetime,
    period_end: datetime,
):
    calls.append((strategy_id, period_start, period_end))
    return await original_list(strategy_id, period_start, period_end)

repo.list_by_strategy_and_executed_time_range = _spy_list_by_strategy_and_executed_time_range

result = await calc.compute(
    "strat-1", "ver-1", None,
    _dt(2025, 1, 1), _dt(2025, 1, 31),
)

assert calls == [
    ("strat-1", _dt(2025, 1, 1), _dt(2025, 1, 31)),
]
```

### 2.3 TradeRepository 只读接口（C2 用）

```python
# src/repositories/trade_repo.py
async def list_by_strategy_and_executed_time_range(
    self, strategy_id: str, period_start: datetime, period_end: datetime
) -> List[Trade]:
    """只读：executed_at 在 [period_start, period_end]，按 executed_at 升序。不执行 INSERT/UPDATE/DELETE。"""
    stmt = select(Trade).where(
        Trade.strategy_id == strategy_id,
        Trade.executed_at >= period_start,
        Trade.executed_at <= period_end,
    ).order_by(Trade.executed_at)
    result = await self.session.execute(stmt)
    return list(result.scalars().all())
```

---

## 三、测试用例与可复现步骤

- **测试文件**：`tests/unit/phase2/test_metrics_calculator.py`
- **用例**：
  - `test_compute_returns_b2_five_metrics`：给定策略+版本+时间范围，断言返回 B.2 五指标，并通过 Spy 断言 compute 仅按 `strategy_id + 时间范围` 调用 `list_by_strategy_and_executed_time_range`（版本维度不参与 trade 查询）。
  - `test_compute_b2_fixed_trade_set`：固定 3 笔 trade（10, -5, 0），抽检 trade_count=3、realized_pnl=5、win_rate=1/3、max_drawdown=5（权益 10→5→5）、avg_holding_time_sec=None。
  - `test_compute_no_trades_only_rejections`：无 trade 周期，断言 trade_count=0、win_rate=None、realized_pnl=0、max_drawdown=0、avg_holding_time_sec=None。
  - `test_compute_single_trade_max_drawdown_zero`：仅一笔 trade，断言 max_drawdown=0。
  - `test_metrics_result_no_conclusion_baseline`：断言 MetricsResult 无 conclusion、comparison_summary、baseline 属性，仅含 B.2 五字段，且 `max_drawdown` 字段类型为 `Decimal`（非 Optional）。
  - `test_compute_read_only_no_write`：对 `AsyncSession.add/commit/flush` 做 Spy 计数，调用 compute 后断言写路径计数均为 0，且 trade 行数与内容无变化。

**可复现**：项目根目录执行  
`python3 -m pytest tests/unit/phase2/test_metrics_calculator.py -v 2>&1`

### 3.1 `test_compute_read_only_no_write` 关键实现片段

```python
@pytest.mark.asyncio
async def test_compute_read_only_no_write(session_factory):
    async with session_factory() as session:
        await _create_trade(session, "r1", "strat-r", _dt(2025, 5, 1), Decimal("1"))
    async with session_factory() as session:
        # 显式 Spy 写路径：若 compute 存在写操作，应触发 add/commit/flush。
        write_calls = {"add": 0, "commit": 0, "flush": 0}

        original_add = session.add

        def _spy_add(instance, *args, **kwargs):
            write_calls["add"] += 1
            return original_add(instance, *args, **kwargs)

        original_commit = session.commit

        async def _spy_commit(*args, **kwargs):
            write_calls["commit"] += 1
            return await original_commit(*args, **kwargs)

        original_flush = session.flush

        async def _spy_flush(*args, **kwargs):
            write_calls["flush"] += 1
            return await original_flush(*args, **kwargs)

        session.add = _spy_add
        session.commit = _spy_commit
        session.flush = _spy_flush

        repo = TradeRepository(session)
        calc = MetricsCalculator(repo)
        await calc.compute("strat-r", "v", None, _dt(2025, 5, 1), _dt(2025, 5, 31))

        # 只读保证：compute 过程中未触发任何写路径。
        assert write_calls == {"add": 0, "commit": 0, "flush": 0}
```

---

## 四、测试命令与原始输出

**命令**：

```bash
python3 -m pytest tests/unit/phase2/test_metrics_calculator.py -v 2>&1
```

**原始输出**（本次修复后重新执行，完整输出亦记录于 `docs/runlogs/phase20_c2_metrics_20260225.txt`）：

```
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0 -- /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 6 items

tests/unit/phase2/test_metrics_calculator.py::test_compute_returns_b2_five_metrics PASSED [ 16%]
tests/unit/phase2/test_metrics_calculator.py::test_compute_b2_fixed_trade_set PASSED [ 33%]
tests/unit/phase2/test_metrics_calculator.py::test_compute_no_trades_only_rejections PASSED [ 50%]
tests/unit/phase2/test_metrics_calculator.py::test_compute_single_trade_max_drawdown_zero PASSED [ 66%]
tests/unit/phase2/test_metrics_calculator.py::test_metrics_result_no_conclusion_baseline PASSED [ 83%]
tests/unit/phase2/test_metrics_calculator.py::test_compute_read_only_no_write PASSED [100%]

============================== 6 passed in 0.15s ===============================
```

---

## 五、B.2 口径说明（证据包内对照）

| 指标 | B.2 口径（写死） | 本模块实现 |
|------|------------------|------------|
| trade_count | 时间范围内 COUNT(trade_id)，无 trade 时为 0 | len(trades)；0 笔时为 0 |
| win_rate | 盈利笔数/总笔数，无 trade 时 0 或 NULL | winning_count/total；0 笔时为 None |
| realized_pnl | SUM(realized_pnl)，无 trade 时为 0 | sum(t.realized_pnl)；0 笔时为 Decimal("0") |
| max_drawdown | 基于逐笔成交后累计权益曲线；无/仅一笔时按约定（需在文档中写死为 0 或 NULL） | 按 executed_at 排序后做权益曲线，取 max(peak-running)，并写死：无 trade 或仅一笔 trade 时返回 Decimal("0")；`MetricsResult.max_drawdown` 类型为 `Decimal` |
| avg_holding_time_sec | AVG(close_time-open_time) 秒，无 trade 或缺少时间字段为 NULL | Trade 表无 open/close 时间字段，恒为 None |

---

## 六、与本模块 Acceptance Criteria 逐条对照说明

| 验收口径（C2 交付包） | 结论 | 证据位置 |
|----------------------|------|----------|
| 给定策略+版本+时间范围可返回 B.2 五指标 | **Option B 真实口径**：当前 Phase 1.2 `trade` 表无 `strategy_version_id` 列，C2 在 trade 层仅按 `strategy_id + 时间范围` 读取数据；版本维度在后续写入 `metrics_snapshot` / `evaluation_report` 时由调用方落地。对同一 `strategy_id + 时间范围`，不同 `strategy_version_id` 入参返回的指标完全一致。 | `MetricsCalculator.compute` docstring；`test_compute_returns_b2_five_metrics` 中对 `list_by_strategy_and_executed_time_range` 调用参数的 Spy 断言 |
| 口径抽检：trade_count=COUNT、realized_pnl=SUM、win_rate=盈利/总、max_drawdown 来自权益曲线、avg_holding_time_sec=AVG(close-open) 或 NULL | YES | `test_compute_b2_fixed_trade_set`；avg_holding 缺字段为 None |
| 仅风控拒绝无 trade 的周期，核心指标为 0 或 NULL | YES | `test_compute_no_trades_only_rejections` |
| 只读边界：compute 执行前后 Phase 1.2 表无任何 INSERT/UPDATE/DELETE | YES | MetricsCalculator 仅调用 `list_by_strategy_and_executed_time_range`（只读）；`test_compute_read_only_no_write` 中对 `AsyncSession.add/commit/flush` 的 Spy 计数均为 0，且 trade 行数与内容无变化 |
| MetricsCalculator 未输出 conclusion、comparison_summary、baseline 或「建议」 | YES | `MetricsResult` 仅五字段；`test_metrics_result_no_conclusion_baseline` 中同时锁定 `max_drawdown` 类型为 `Decimal` |

---

## 七、验收结论

本模块满足 C2 目标与开发范围：实现 MetricsCalculator.compute(strategy_id, strategy_version_id, param_version_id?, period_start, period_end) -> MetricsResult；数据来源仅只读 Phase 1.2 trade 表（通过 TradeRepository.list_by_strategy_and_executed_time_range）；输出 B.2 五指标，不包含 conclusion、comparison_summary、baseline 或「建议」；不写 Phase 1.2 表；B.2 口径在实现与证据包中写死并对照。验收通过。
