# Phase2.0 D2 证据包（E2E-2.0 版本对比可验证点）

## 模块名称与目标
- 模块：D2（E2E-2.0 版本对比可验证点）
- 目标：strategy_version_A vs baseline strategy_version_B 的对比闭环验证。

## 修改文件清单
- 新增：`tests/e2e/test_e2e_phase2_version_compare.py`
- 新增：`docs/runlogs/phase20_d2_pytest_output.txt`
- 新增：`docs/runlogs/phase20_d2_pytest_output_with_markers.txt`
- 新增：`docs/Phase2.0_D2_证据包.md`

## 对比测试代码
文件：`tests/e2e/test_e2e_phase2_version_compare.py`
```python
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.phase2_main_flow_service import Phase2MainFlowService
from src.database.connection import Base
from src.models.decision_snapshot import DecisionSnapshot
from src.models.execution_event import ExecutionEvent
from src.models.log_entry import LogEntry
from src.models.trade import Trade
from src.phase2.evaluation_config import EvaluatorConfig
from src.repositories.trade_repo import TradeRepository
import src.models  # noqa: F401


def _dt(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


@pytest.fixture
async def d2_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_trade_data(session: AsyncSession, strategy_id: str, rows: list[tuple[str, str]]) -> None:
    repo = TradeRepository(session)
    for trade_id, pnl in rows:
        await repo.create(
            Trade(
                trade_id=trade_id,
                strategy_id=strategy_id,
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("50000"),
                realized_pnl=Decimal(pnl),
                executed_at=_dt(2025, 2, 1, 9, 0),
            )
        )
    await session.commit()


async def _phase12_counts(session: AsyncSession) -> dict[str, int]:
    return {
        "trade": int((await session.execute(select(func.count()).select_from(Trade))).scalar() or 0),
        "decision_snapshot": int((await session.execute(select(func.count()).select_from(DecisionSnapshot))).scalar() or 0),
        "execution_events": int((await session.execute(select(func.count()).select_from(ExecutionEvent))).scalar() or 0),
        "log": int((await session.execute(select(func.count()).select_from(LogEntry))).scalar() or 0),
    }


@pytest.mark.asyncio
async def test_e2e_phase2_version_compare(d2_session_factory):
    strategy_base = "D2-STRATEGY-BASE"
    strategy_target = "D2-STRATEGY-TARGET"
    version_base = "D2-V-B"
    version_target = "D2-V-A"
    param_base = "D2-P-B"
    param_target = "D2-P-A"
    period_start = _dt(2025, 2, 1, 0, 0)
    period_end = _dt(2025, 2, 2, 0, 0)

    async with d2_session_factory() as session:
        # baseline 版本与 target 版本使用不同固定 trade 集，确保 comparison_summary 存在差异
        await _seed_trade_data(session, strategy_base, [("D2-T-B1", "10"), ("D2-T-B2", "-5")])
        await _seed_trade_data(session, strategy_target, [("D2-T-A1", "120"), ("D2-T-A2", "80"), ("D2-T-A3", "-10")])
        counts_before = await _phase12_counts(session)
    print("D2_PHASE12_COUNTS_BEFORE=" + json.dumps(counts_before, ensure_ascii=False, sort_keys=True))

    service = Phase2MainFlowService(d2_session_factory)

    baseline_cfg = EvaluatorConfig(
        objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
        constraint_definition={"max_drawdown_pct": 1000, "min_trade_count": 1, "max_risk_exposure": None, "custom": None},
        baseline_version_id=None,
    )
    compare_cfg = EvaluatorConfig(
        objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
        constraint_definition={"max_drawdown_pct": 1000, "min_trade_count": 1, "max_risk_exposure": None, "custom": None},
        baseline_version_id=version_base,
    )

    write_sql_phase12: list[str] = []
    phase12_tables = ("trade", "decision_snapshot", "execution_events", "log")

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        sql = " ".join((statement or "").strip().split())
        lowered = sql.lower()
        is_write = lowered.startswith("insert") or lowered.startswith("update") or lowered.startswith("delete") or lowered.startswith("replace")
        if is_write and any(f" {tbl} " in f" {lowered} " or f" {tbl}(" in f" {lowered} " for tbl in phase12_tables):
            write_sql_phase12.append(sql)

    event.listen(d2_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        # 先产出 baseline 版本快照/报告
        await service.run_main_flow(
            strategy_id=strategy_base,
            strategy_version_id=version_base,
            param_version_id=param_base,
            period_start=period_start,
            period_end=period_end,
            config=baseline_cfg,
        )
        # 再做版本对比：target vs baseline_version_id
        result = await service.run_main_flow(
            strategy_id=strategy_target,
            strategy_version_id=version_target,
            param_version_id=param_target,
            period_start=period_start,
            period_end=period_end,
            config=compare_cfg,
        )

        # 非法 baseline：param_version_id 作为 baseline_version_id 必须拒绝
        illegal_baseline_error = None
        try:
            await service.run_main_flow(
                strategy_id=strategy_target,
                strategy_version_id=version_target,
                param_version_id=param_target,
                period_start=period_start,
                period_end=period_end,
                config=EvaluatorConfig(
                    objective_definition={"primary": "pnl", "primary_weight": 1.0, "secondary": [], "secondary_weights": []},
                    constraint_definition={"max_drawdown_pct": 1000, "min_trade_count": 1, "max_risk_exposure": None, "custom": None},
                    baseline_version_id=param_target,
                ),
            )
        except Exception as exc:  # ValueError 由 Evaluator 抛出
            illegal_baseline_error = str(exc)
        assert illegal_baseline_error is not None
        print("D2_ILLEGAL_BASELINE_ERROR=" + illegal_baseline_error)
    finally:
        event.remove(d2_session_factory.kw["bind"].sync_engine, "before_cursor_execute", _before_cursor_execute)

    print(f"D2_PHASE12_WRITE_SQL_COUNT={len(write_sql_phase12)}")
    assert len(write_sql_phase12) == 0

    # 查询与持久化验证
    by_version = await service.query_by_strategy_version(version_target)
    by_param = await service.query_by_param_version(param_target)
    print(
        "D2_QUERY_COUNTS="
        + json.dumps(
            {"strategy_version": len(by_version), "param_version": len(by_param)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    assert len(by_version) >= 1
    assert len(by_param) >= 1

    report = by_param[-1]
    sample = {
        "strategy_id": report.strategy_id,
        "strategy_version_id": report.strategy_version_id,
        "param_version_id": report.param_version_id,
        "baseline_version_id": report.baseline_version_id,
        "conclusion": report.conclusion,
        "comparison_summary": report.comparison_summary,
    }
    print("D2_COMPARISON_SAMPLE_JSON=" + json.dumps(sample, ensure_ascii=False, sort_keys=True))

    assert report.baseline_version_id == version_base
    assert report.baseline_version_id != param_target
    assert report.comparison_summary is not None
    assert isinstance(report.comparison_summary, dict)
    delta = report.comparison_summary.get("delta") or {}
    assert "trade_count" in delta
    assert "realized_pnl" in delta
    assert "win_rate" in delta
    summary_str = json.dumps(report.comparison_summary, ensure_ascii=False)
    assert "建议参数" not in summary_str
    assert "优化" not in summary_str
    assert "写回" not in summary_str
    assert "建议参数" not in report.conclusion
    assert "优化" not in report.conclusion
    assert "写回" not in report.conclusion

    async with d2_session_factory() as session:
        counts_after = await _phase12_counts(session)
    print("D2_PHASE12_COUNTS_AFTER=" + json.dumps(counts_after, ensure_ascii=False, sort_keys=True))
    assert counts_after == counts_before
```

## pytest 原始输出
### 指定命令输出
命令：`pytest tests/e2e/test_e2e_phase2_version_compare.py`
来源：`docs/runlogs/phase20_d2_pytest_output.txt`
```text
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 1 item

tests/e2e/test_e2e_phase2_version_compare.py .                           [100%]

============================== 1 passed in 0.07s ===============================
```

### 含审计打印输出
命令：`pytest tests/e2e/test_e2e_phase2_version_compare.py -s`
来源：`docs/runlogs/phase20_d2_pytest_output_with_markers.txt`
```text
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 1 item

tests/e2e/test_e2e_phase2_version_compare.py D2_PHASE12_COUNTS_BEFORE={"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 5}
D2_ILLEGAL_BASELINE_ERROR=baseline_version_id 只能为 strategy_version_id 或 null，禁止使用 param_version_id 作为基线
D2_PHASE12_WRITE_SQL_COUNT=0
D2_QUERY_COUNTS={"param_version": 1, "strategy_version": 1}
D2_COMPARISON_SAMPLE_JSON={"baseline_version_id": "D2-V-B", "comparison_summary": {"baseline": {"avg_holding_time_sec": null, "max_drawdown": 5.0, "realized_pnl": 5.0, "trade_count": 2, "win_rate": 0.5}, "current": {"avg_holding_time_sec": null, "max_drawdown": 10.0, "realized_pnl": 190.0, "trade_count": 3, "win_rate": 0.6666666666666666}, "delta": {"max_drawdown": 5.0, "realized_pnl": 185.0, "trade_count": 1, "win_rate": 0.16666667}}, "conclusion": "pass", "param_version_id": "D2-P-A", "strategy_id": "D2-STRATEGY-TARGET", "strategy_version_id": "D2-V-A"}
D2_PHASE12_COUNTS_AFTER={"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 5}
.

============================== 1 passed in 0.07s ===============================
```

## comparison_summary 样本
```json
{"baseline_version_id": "D2-V-B", "comparison_summary": {"baseline": {"avg_holding_time_sec": null, "max_drawdown": 5.0, "realized_pnl": 5.0, "trade_count": 2, "win_rate": 0.5}, "current": {"avg_holding_time_sec": null, "max_drawdown": 10.0, "realized_pnl": 190.0, "trade_count": 3, "win_rate": 0.6666666666666666}, "delta": {"max_drawdown": 5.0, "realized_pnl": 185.0, "trade_count": 1, "win_rate": 0.16666667}}, "conclusion": "pass", "param_version_id": "D2-P-A", "strategy_id": "D2-STRATEGY-TARGET", "strategy_version_id": "D2-V-A"}
```

## 非法 baseline 测试结果
```text
D2_ILLEGAL_BASELINE_ERROR=baseline_version_id 只能为 strategy_version_id 或 null，禁止使用 param_version_id 作为基线
```

## Phase1.2 表行数前后对比
- BEFORE
```json
```
- AFTER
```json
{"decision_snapshot": 0, "execution_events": 0, "log": 0, "trade": 5}
```

## 只读边界强反证
```text
D2_PHASE12_WRITE_SQL_COUNT=0
```

## 与 AC 逐条对照说明
- [x] comparison_summary 正确生成（含 B.2 指标差异 delta）。
- [x] baseline_version_id 合法（持久化为 strategy_version_B，且不为 param_version_id）。
- [x] 非法 baseline 被拒绝（param_version_id 作为 baseline 触发错误）。
- [x] evaluation_report 正确持久化（查询返回记录）。
- [x] 查询可返回正确 baseline（按 strategy_version / param_version 查询均可返回 baseline_version_id=version_B）。
- [x] 无“建议参数/优化/写回”等语义（conclusion 与 comparison_summary 均校验）。
- [x] 无 Phase1.2 写操作（主流程区间 `D2_PHASE12_WRITE_SQL_COUNT=0`）。
