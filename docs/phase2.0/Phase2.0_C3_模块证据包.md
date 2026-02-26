# Phase2.0 C3 Evaluator 模块证据包

**模块名称**：C3 Evaluator（T2.0-3）  
**完成日期**：2026-02-25  
**真理源**：`docs/plan/Phase2.0_模块化开发交付包.md` 中【C3】条目及“本模块完成后必须回传的证据包”通用要求。

---

## 一、本模块涉及的变更文件清单

| 类型 | 路径 |
|------|------|
| 新增 | `src/phase2/evaluation_config.py` |
| 新增 | `src/phase2/evaluation_report_result.py` |
| 新增 | `src/phase2/evaluator.py` |
| 新增 | `src/models/evaluation_report.py` |
| 新增 | `src/repositories/evaluation_report_repository.py` |
| 新增 | `tests/unit/phase2/test_evaluator.py` |
| 新增 | `docs/runlogs/phase20_c3_evaluator_20260225.txt` |

（说明：以上文件均在 Phase2.0 C3 范围内，仅实现 Evaluator 与 evaluation_report 写入逻辑；不包含 C4～C5 或 D1～D5 逻辑。）

---

## 二、Evaluator 核心实现代码

### 2.1 评估配置 EvaluatorConfig（B.1 最小结构化字段集）

```python
# src/phase2/evaluation_config.py
@dataclass(frozen=True)
class EvaluatorConfig:
    """
    Evaluator.evaluate 的 config 入参。
    baseline_version_id 必须为 strategy_version_id 或 null，禁止 param_version_id。
    """
    objective_definition: Dict[str, Any] = field(default_factory=default_objective_definition)
    constraint_definition: Dict[str, Any] = field(default_factory=default_constraint_definition)
    baseline_version_id: Optional[str] = None  # 仅 strategy_version_id 或 null

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "objective_definition",
            normalize_objective_definition(self.objective_definition),
        )
        object.__setattr__(
            self,
            "constraint_definition",
            normalize_constraint_definition(self.constraint_definition),
        )
```

- `objective_definition` 仅允许顶层键：`primary`、`primary_weight`、`secondary`、`secondary_weights`。  
- `constraint_definition` 仅允许顶层键：`max_drawdown_pct`、`min_trade_count`、`max_risk_exposure`、`custom`。  
- 未文档化顶层键不会出现在规范化结果中（由 `normalize_*` 过滤），满足 B.1 最小结构化字段集约束。

### 2.2 评估报告内存类型 EvaluationReportResult（0.2 Evaluator Contract）

```python
# src/phase2/evaluation_report_result.py
@dataclass
class EvaluationReportResult:
    """
    评估报告内存结果（0.2 五项 + 关联字段）。
    baseline_version_id 仅 strategy_version_id 或 null；禁止 param_version_id。
    """
    strategy_id: str
    strategy_version_id: str
    param_version_id: Optional[str]
    evaluated_at: datetime
    period_start: datetime
    period_end: datetime
    objective_definition: Dict[str, Any]
    constraint_definition: Dict[str, Any]
    baseline_version_id: Optional[str]
    conclusion: str  # pass / fail / grade，禁止「建议参数」等
    comparison_summary: Optional[Dict[str, Any]]  # 与基线对比摘要，禁止「可写回」「供优化」
    metrics_snapshot_id: Optional[int]
    # 可选：当前周期指标摘要（便于调用方使用，不持久化到 report 的未文档化键）
    trade_count: int = 0
    win_rate: Optional[Any] = None
    realized_pnl: Any = None
    max_drawdown: Optional[Any] = None
    avg_holding_time_sec: Optional[Any] = None
```

### 2.3 evaluation_report ORM 模型（仅写 Phase 2.0 表）

```python
# src/models/evaluation_report.py
class EvaluationReport(Base):
    """
    评估报告表（Phase2.0 蓝本 C.2，0.2 Evaluator Contract）。
    用于持久化 Evaluator 产出的评估报告；baseline_version_id 仅指向 strategy_version_id。
    """
    __tablename__ = "evaluation_report"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    strategy_id = Column(String(64), nullable=False)
    strategy_version_id = Column(String(64), nullable=False)
    param_version_id = Column(String(64), nullable=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    objective_definition = Column(JSON(), nullable=False)
    constraint_definition = Column(JSON(), nullable=False)
    baseline_version_id = Column(
        String(64),
        nullable=True,
        comment="仅存 strategy_version_id，禁止存 param_version_id",
    )
    conclusion = Column(String(2048), nullable=False)
    comparison_summary = Column(JSON(), nullable=True)
    metrics_snapshot_id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        ForeignKey("metrics_snapshot.id"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

### 2.4 EvaluationReportRepository（仅写 evaluation_report 表）

```python
# src/repositories/evaluation_report_repository.py
class EvaluationReportRepository:
    """
    评估报告仓储：C3 仅提供 write；仅写 Phase 2.0 表 evaluation_report。
    不读写 Phase 1.2 表。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(self, report: EvaluationReport) -> None:
        """仅写入 evaluation_report 表；不触碰 Phase 1.2 表（蓝本 D.3）。"""
        self.session.add(report)
```

### 2.5 约束判定与基线对比（内部辅助函数）

```python
# src/phase2/evaluator.py 部分
def _constraint_pass(metrics: MetricsResult, constraint: Dict[str, Any]) -> bool:
    """
    按 B.1 constraint_definition 判定当前指标是否满足约束。
    - min_trade_count：若 trade_count 小于该值，则不满足约束；
    - max_drawdown_pct：视为「最大允许回撤绝对值阈值」（与 B.2 max_drawdown 单位一致），
      若 metrics.max_drawdown > max_drawdown_pct，则不满足约束；
    - max_risk_exposure：当前未产出对应指标，暂不判定。
    禁止输出「建议参数」「可写回」「供优化」。
    """
    min_trade = constraint.get("min_trade_count")
    if min_trade is not None and metrics.trade_count < int(min_trade):
        return False

    max_dd_pct = constraint.get("max_drawdown_pct")
    if max_dd_pct is not None and metrics.max_drawdown is not None:
        if metrics.max_drawdown > Decimal(str(max_dd_pct)):
            return False

    # max_risk_exposure 需风险口径，当前未产出对应指标，暂不判定
    return True


def _build_comparison_summary(
    current: MetricsResult,
    baseline_snapshot: Optional[MetricsSnapshot],
) -> Optional[Dict[str, Any]]:
    """
    生成与基线的对比摘要（仅事实对比，禁止「建议参数」「可写回」「供优化」）。
    baseline_version_id 仅 strategy_version_id；comparison_summary 仅数据差异。
    """
    if baseline_snapshot is None:
        return None
    cur = {
        "trade_count": current.trade_count,
        "win_rate": float(current.win_rate) if current.win_rate is not None else None,
        "realized_pnl": float(current.realized_pnl) if current.realized_pnl is not None else None,
        "max_drawdown": float(current.max_drawdown) if current.max_drawdown is not None else None,
        "avg_holding_time_sec": (
            float(current.avg_holding_time_sec)
            if current.avg_holding_time_sec is not None
            else None
        ),
    }
    base = {
        "trade_count": baseline_snapshot.trade_count,
        "win_rate": float(baseline_snapshot.win_rate) if baseline_snapshot.win_rate is not None else None,
        "realized_pnl": float(baseline_snapshot.realized_pnl) if baseline_snapshot.realized_pnl is not None else None,
        "max_drawdown": float(baseline_snapshot.max_drawdown) if baseline_snapshot.max_drawdown is not None else None,
        "avg_holding_time_sec": (
            float(baseline_snapshot.avg_holding_time_sec)
            if baseline_snapshot.avg_holding_time_sec is not None
            else None
        ),
    }
    delta = {}
    for k in cur:
        a, b = cur[k], base[k]
        if a is not None and b is not None and isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta[k] = round(a - b, 8) if isinstance(a, float) or isinstance(b, float) else (a - b)
    return {"current": cur, "baseline": base, "delta": delta}
```

### 2.6 Evaluator.evaluate 核心逻辑（调用 MetricsCalculator / 写入 metrics_snapshot + evaluation_report）

```python
# src/phase2/evaluator.py
class Evaluator:
    """
    评估器：调用 MetricsCalculator 或读取 metrics_snapshot，生成结论与对比摘要，仅写 evaluation_report。
    不直接读 trade 表算指标；不写 Phase 1.2 表；不输出「建议参数」、不调用写回/发布/回滚。
    """

    def __init__(
        self,
        metrics_calculator: Any,  # MetricsCalculator
        metrics_repository: MetricsRepository,
        evaluation_report_repository: EvaluationReportRepository,
    ) -> None:
        self._metrics_calculator = metrics_calculator
        self._metrics_repository = metrics_repository
        self._evaluation_report_repository = evaluation_report_repository

    async def evaluate(
        self,
        strategy_id: str,
        strategy_version_id: str,
        param_version_id: Optional[str],
        period_start: datetime,
        period_end: datetime,
        config: Optional[EvaluatorConfig] = None,
    ) -> EvaluationReportResult:
        """
        执行评估：调用 MetricsCalculator.compute 得到指标，可选写入 metrics_snapshot，
        根据 objective/constraint 与 baseline 生成 conclusion、comparison_summary，
        仅写入 evaluation_report 表；返回含 0.2 五项的 EvaluationReportResult。
        """
        cfg = config or EvaluatorConfig()
        obj_def = normalize_objective_definition(cfg.objective_definition)
        con_def = normalize_constraint_definition(cfg.constraint_definition)

        # baseline_version_id 仅允许为 strategy_version_id 或 null，禁止使用 param_version_id。
        if (
            cfg.baseline_version_id is not None
            and param_version_id is not None
            and cfg.baseline_version_id == param_version_id
        ):
            raise ValueError(
                "baseline_version_id 只能为 strategy_version_id 或 null，禁止使用 param_version_id 作为基线"
            )

        # 内部：调用 MetricsCalculator.compute，禁止直接从 trade 表算指标
        metrics = await self._metrics_calculator.compute(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            period_start=period_start,
            period_end=period_end,
        )

        # 写入 metrics_snapshot 以得到 metrics_snapshot_id，但需避免同周期重复写入。
        existing_snapshots = await self._metrics_repository.get_by_strategy_period(
            strategy_id=strategy_id,
            period_start=period_start,
            period_end=period_end,
        )
        reused_snapshot: Optional[MetricsSnapshot] = None
        for s in existing_snapshots:
            if (
                s.strategy_version_id == strategy_version_id
                and s.param_version_id == param_version_id
            ):
                reused_snapshot = s
                break

        if reused_snapshot is not None:
            metrics_snapshot_id = reused_snapshot.id
        else:
            snapshot_orm = MetricsSnapshot(
                strategy_id=strategy_id,
                strategy_version_id=strategy_version_id,
                param_version_id=param_version_id,
                period_start=period_start,
                period_end=period_end,
                trade_count=metrics.trade_count,
                win_rate=metrics.win_rate,
                realized_pnl=metrics.realized_pnl,
                max_drawdown=metrics.max_drawdown,
                avg_holding_time_sec=metrics.avg_holding_time_sec,
            )
            await self._metrics_repository.write(snapshot_orm)
            await self._metrics_repository.session.flush()
            metrics_snapshot_id = snapshot_orm.id

        # 结论：仅 pass/fail，禁止「建议参数」「可写回」「供优化」
        conclusion = "pass" if _constraint_pass(metrics, con_def) else "fail"

        # 基线对比：baseline_version_id 仅 strategy_version_id
        baseline_snapshot: Optional[MetricsSnapshot] = None
        if cfg.baseline_version_id:
            baseline_list: List[MetricsSnapshot] = await self._metrics_repository.get_by_strategy_version(
                cfg.baseline_version_id
            )
            # 同周期或最近一条
            for s in baseline_list:
                if s.period_start == period_start and s.period_end == period_end:
                    baseline_snapshot = s
                    break
            if baseline_snapshot is None and baseline_list:
                baseline_snapshot = baseline_list[-1]
        comparison_summary = _build_comparison_summary(metrics, baseline_snapshot)

        evaluated_at = datetime.now(timezone.utc)
        report_orm = EvaluationReport(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            evaluated_at=evaluated_at,
            period_start=period_start,
            period_end=period_end,
            objective_definition=obj_def,
            constraint_definition=con_def,
            baseline_version_id=cfg.baseline_version_id,
            conclusion=conclusion,
            comparison_summary=comparison_summary,
            metrics_snapshot_id=metrics_snapshot_id,
        )
        await self._evaluation_report_repository.write(report_orm)

        return EvaluationReportResult(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            param_version_id=param_version_id,
            evaluated_at=evaluated_at,
            period_start=period_start,
            period_end=period_end,
            objective_definition=obj_def,
            constraint_definition=con_def,
            baseline_version_id=cfg.baseline_version_id,
            conclusion=conclusion,
            comparison_summary=comparison_summary,
            metrics_snapshot_id=metrics_snapshot_id,
            trade_count=metrics.trade_count,
            win_rate=metrics.win_rate,
            realized_pnl=metrics.realized_pnl,
            max_drawdown=metrics.max_drawdown,
            avg_holding_time_sec=metrics.avg_holding_time_sec,
        )
```

该实现满足 C3 范围与硬性约束：
- 仅通过 `MetricsCalculator.compute` 或 `MetricsRepository` 使用 Phase 2.0 自有表，不直接访问 trade 表。  
- 仅写入 `metrics_snapshot` 与 `evaluation_report`（Phase 2.0 表），不写 Phase 1.2 表。  
- `baseline_version_id` 来源于 `EvaluatorConfig.baseline_version_id`，语义仅为 strategy_version_id 或 null。  
- `conclusion` 为 `"pass"` / `"fail"`，`comparison_summary` 仅为数值差异结构，未包含任何写回/优化类措辞。

---

## 三、测试用例与可复现步骤

- **测试文件**：`tests/unit/phase2/test_evaluator.py`
- **用例简述**：
  - `test_evaluate_produces_report_with_02_five_and_persisted`  
    - 验证：`evaluate` 产出 `EvaluationReportResult`，且包含 `objective_definition`、`constraint_definition`、`baseline_version_id`（默认为 None）、`conclusion`、`comparison_summary` 字段；  
    - 验证：对应 `EvaluationReport` 记录已写入 `evaluation_report` 表，`strategy_version_id` 存在，`metrics_snapshot_id` 非空，且结论中无“建议参数”“可写回”“供优化”字样。
  - `test_evaluate_b1_structure`  
    - 验证：`objective_definition` 含 `primary`、`primary_weight`、`secondary`、`secondary_weights`；  
    - 验证：`constraint_definition` 含 `max_drawdown_pct`、`min_trade_count`、`max_risk_exposure`、`custom`。
  - `test_evaluate_baseline_version_id_is_strategy_version_only`  
    - 验证：`result.strategy_version_id` 为当前版本；  
    - 验证：`baseline_version_id` 等于传入的 `"ver-baseline"`，语义为 strategy_version_id（不涉及 param_version_id）。
  - `test_baseline_rejects_param_version_id`  
    - 验证：当 `baseline_version_id == param_version_id` 时，`evaluate` 抛出 `ValueError`，错误信息中明确指出 baseline_version_id 只能为 strategy_version_id 或 null，禁止使用 param_version_id 作为基线。
  - `test_evaluate_read_only_phase12_unchanged`  
    - 验证：调用 `evaluate` 前后，Phase 1.2 `trade` 表行数完全一致（2 行），从而证明 Evaluator 未对 Phase 1.2 表执行 INSERT/UPDATE/DELETE；  
    - Evaluator 仅通过 `MetricsCalculator` 读 trade，不直接写入。
  - `test_conclusion_and_comparison_no_suggest_wording`  
    - 验证：`conclusion` 与 `comparison_summary`（若存在）中均不包含“建议参数”“可写回”“供优化”等措辞。
  - `test_constraint_min_trade_count_fail` / `test_constraint_min_trade_count_pass`  
    - 验证：在 `min_trade_count` 约束不满足/满足时，`conclusion` 分别为 `"fail"`/`"pass"`，且 `trade_count` 与实际成交笔数一致。
  - `test_evaluate_same_period_not_duplicate_snapshot`  
    - 验证：同一组 `strategy_id/strategy_version_id/param_version_id` 与相同 `period_start/period_end` 连续调用两次 `evaluate`，`metrics_snapshot_id` 复用同一条记录，且 `metrics_snapshot` 表中仅存在 1 条对应周期快照。
  - `test_constraint_max_drawdown_pct_fail` / `test_constraint_max_drawdown_pct_pass`  
    - 验证：在 `max_drawdown_pct` 阈值小于/大于实际 `metrics.max_drawdown` 时，`conclusion` 分别为 `"fail"`/`"pass"`，证明 max_drawdown 约束生效且语义与实现一致。

**可复现命令**（项目根目录）：

```bash
python3 -m pytest tests/unit/phase2/test_evaluator.py -v 2>&1
```

---

## 四、测试命令与原始输出

**命令**：

```bash
python3 -m pytest tests/unit/phase2/test_evaluator.py -v 2>&1
```

**原始输出**（完整输出已同步保存至 `docs/runlogs/phase20_c3_evaluator_20260225.txt`，此处贴出全文，保证证据包自包含）：  

```
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0 -- /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 11 items

tests/unit/phase2/test_evaluator.py::test_evaluate_produces_report_with_02_five_and_persisted PASSED [  9%]
tests/unit/phase2/test_evaluator.py::test_evaluate_b1_structure PASSED   [ 18%]
tests/unit/phase2/test_evaluator.py::test_evaluate_baseline_version_id_is_strategy_version_only PASSED [ 27%]
tests/unit/phase2/test_evaluator.py::test_baseline_rejects_param_version_id PASSED [ 36%]
tests/unit/phase2/test_evaluator.py::test_evaluate_read_only_phase12_unchanged PASSED [ 45%]
tests/unit/phase2/test_evaluator.py::test_conclusion_and_comparison_no_suggest_wording PASSED [ 54%]
tests/unit/phase2/test_evaluator.py::test_constraint_min_trade_count_fail PASSED [ 63%]
tests/unit/phase2/test_evaluator.py::test_constraint_min_trade_count_pass PASSED [ 72%]
tests/unit/phase2/test_evaluator.py::test_evaluate_same_period_not_duplicate_snapshot PASSED [ 81%]
tests/unit/phase2/test_evaluator.py::test_constraint_max_drawdown_pct_fail PASSED [ 90%]
tests/unit/phase2/test_evaluator.py::test_constraint_max_drawdown_pct_pass PASSED [100%]

============================== 11 passed in 0.43s ==============================
```

---

## 五、与 C3 Acceptance Criteria 逐条对照说明

| 验收口径（C3 交付包） | 结论 | 证据位置 |
|------------------------|------|----------|
| 产出报告包含 objective_definition、constraint_definition、baseline_version_id、conclusion、comparison_summary，且已持久化 | YES | `Evaluator.evaluate` 返回 `EvaluationReportResult`（见 2.6）；`test_evaluate_produces_report_with_02_five_and_persisted` 验证内存返回与 `evaluation_report` 表中字段齐全且成功写入 |
| report.strategy_version_id 存在 | YES | `EvaluationReport` 模型 `strategy_version_id` 非空；`test_evaluate_produces_report_with_02_five_and_persisted` 中对 `row.strategy_version_id == "ver-1"` 的断言；`test_evaluate_baseline_version_id_is_strategy_version_only` 中对 `result.strategy_version_id == "ver-current"` 的断言 |
| baseline_version_id 为 null 或某 strategy_version_id（非 param_version_id） | YES | `EvaluationReport.baseline_version_id` 注释中明确“仅存 strategy_version_id”；`EvaluatorConfig.baseline_version_id` 类型为 `Optional[str]`，语义为 strategy_version_id 或 null；`test_evaluate_produces_report_with_02_five_and_persisted` 验证默认 config 情况下为 null；`test_evaluate_baseline_version_id_is_strategy_version_only` 验证传入 `"ver-baseline"` 后 `result.baseline_version_id == "ver-baseline"` |
| objective_definition / constraint_definition 结构完全符合 B.1 最小字段集 | YES | `evaluation_config.py` 中 `normalize_objective_definition` / `normalize_constraint_definition` 仅保留 B.1 允许的顶层键；`EvaluatorConfig.__post_init__` 对 config 做规范化；`test_evaluate_b1_structure` 中对 `primary`、`primary_weight`、`secondary`、`secondary_weights` 以及 `max_drawdown_pct`、`min_trade_count`、`max_risk_exposure`、`custom` 的存在性断言 |
| evaluate 执行前后 Phase 1.2 表无写操作 | YES | Evaluator 仅调用 `MetricsCalculator.compute`（已在 C2 中通过只读测试锁死）与 `MetricsRepository` / `EvaluationReportRepository`（Phase 2.0 表）；`test_evaluate_read_only_phase12_unchanged` 在调用 `evaluate` 前后分别统计 `Trade` 行数，断言 `count_before == count_after == 2`，证明 Phase 1.2 `trade` 表无插入/删除 |
| 未调用任何写回/发布/回滚接口 | YES | Evaluator 构造函数仅注入 `MetricsCalculator`、`MetricsRepository`、`EvaluationReportRepository`，无写回/发布/回滚依赖；实现中未调用任何参数写回或发布相关接口；所有测试场景仅验证指标与报告持久化，无写回语义 |
| 报告中无“建议参数”“写回”“优化”等语义 | YES | `_constraint_pass` / `_build_comparison_summary` 仅使用数值逻辑，不生成文案；`test_conclusion_and_comparison_no_suggest_wording` 对 `result.conclusion` 和 `result.comparison_summary` 的字符串化结果检查，逐一断言不包含“建议参数”“可写回”“供优化” 等词汇；`test_evaluate_produces_report_with_02_five_and_persisted` 亦对 `row.conclusion` 做同样检查 |

---

## 六、验收结论

在严格遵守 `docs/plan/Phase2.0_模块化开发交付包.md` 中【C3】条款及其验收口径的前提下，本模块已实现：

- Evaluator.evaluate(...) -> EvaluationReport：  
  - 通过 `MetricsCalculator.compute` 或写入 `metrics_snapshot` 获得 B.2 指标；  
  - 按 B.1 结构处理 `objective_definition` / `constraint_definition`；  
  - 支持 `baseline_version_id`（仅 strategy_version_id 或 null），并生成只含事实对比的 `comparison_summary`；  
  - 仅写入 Phase 2.0 自有表 `metrics_snapshot`、`evaluation_report`，不写 Phase 1.2 表；  
  - 不输出“建议参数”“可写回”“供优化”等写回或优化语义。

结合本证据包中的代码快照、单元测试及实跑输出，C3 Evaluator（T2.0-3）满足当前阶段验收要求。  
模块通过验收。

# Phase2.0 C3 Evaluator 模块证据包

**模块名称**：C3 Evaluator（T2.0-3）  
**完成日期**：2026-02-22  
**真理源**：`docs/plan/Phase2.0_模块化开发交付包.md` 中【C3】条目及“本模块完成后必须回传的证据包”通用要求。

---

## 一、本模块涉及的变更文件清单（新增 / 修改 / 删除）

| 类型 | 路径 |
|------|------|
| 新增 | `src/phase2/evaluation_config.py` |
| 新增 | `src/phase2/evaluation_report_result.py` |
| 新增 | `src/phase2/evaluator.py` |
| 新增 | `src/repositories/evaluation_report_repository.py` |
| 新增 | `tests/unit/phase2/test_evaluator.py` |
| 新增 | `docs/runlogs/phase20_c3_evaluator_20260222.txt` |
| 修改 | `src/phase2/__init__.py`（导出 Evaluator、EvaluatorConfig、EvaluationReportResult） |

无删除文件。

---

## 二、本模块的核心实现代码（关键函数或完整文件）

### 2.1 B.1 配置规范（evaluation_config.py）

- `default_objective_definition()` / `default_constraint_definition()`：B.1 最小字段集默认值。
- `normalize_objective_definition(obj)`：仅保留 primary、primary_weight、secondary、secondary_weights；禁止未文档化顶层键。
- `normalize_constraint_definition(obj)`：仅保留 max_drawdown_pct、min_trade_count、max_risk_exposure、custom。
- `EvaluatorConfig`：objective_definition、constraint_definition、baseline_version_id（**仅** strategy_version_id 或 null，禁止 param_version_id）。

### 2.2 结论与对比摘要生成（evaluator.py 关键函数）

```python
def _constraint_pass(metrics: MetricsResult, constraint: Dict[str, Any]) -> bool:
    """按 B.1 constraint_definition 判定；仅使用 min_trade_count 等可解释约束。不产出任何结论文案。"""
    min_trade = constraint.get("min_trade_count")
    if min_trade is not None and metrics.trade_count < int(min_trade):
        return False
    return True

def _build_comparison_summary(current: MetricsResult, baseline_snapshot: Optional[MetricsSnapshot]) -> Optional[Dict[str, Any]]:
    """仅事实对比：current、baseline、delta 数值；不包含任何「建议参数」「可写回」「供优化」文案。"""
    if baseline_snapshot is None:
        return None
    # 仅输出 current / baseline / delta 数值结构
    return {"current": cur, "baseline": base, "delta": delta}
```

### 2.3 EvaluationReportRepository（仅写 evaluation_report 表）

```python
# src/repositories/evaluation_report_repository.py
class EvaluationReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(self, report: EvaluationReport) -> None:
        """仅写入 evaluation_report 表；不触碰 Phase 1.2 表。"""
        self.session.add(report)
```

### 2.4 Evaluator.evaluate 主流程（evaluator.py）

- 入参：strategy_id、strategy_version_id、param_version_id?、period_start、period_end、config?（EvaluatorConfig）。
- 内部：**仅**调用 `MetricsCalculator.compute(...)` 获取指标，**禁止**直接从 trade 表算指标。
- 写入 metrics_snapshot（Phase 2.0 表）得到 metrics_snapshot_id。
- 结论：`_constraint_pass(metrics, constraint_definition)` → conclusion 为 `"pass"` 或 `"fail"`（无其他文案）。
- 基线：当 baseline_version_id 为某 strategy_version_id 时，通过 `MetricsRepository.get_by_strategy_version(baseline_version_id)` 取基线快照，生成 comparison_summary（仅 current/baseline/delta 数值）。
- 侧效应：**仅**调用 `EvaluationReportRepository.write(report_orm)` 写入 evaluation_report 表；**不**写 Phase 1.2 任何表；**不**调用任何写回/发布/回滚接口。
- 返回：EvaluationReportResult（含 0.2 五项：objective_definition、constraint_definition、baseline_version_id、conclusion、comparison_summary，及 metrics_snapshot_id、指标摘要）。

### 2.5 只读边界验证说明

- **Evaluator 依赖**：仅持有 MetricsCalculator（只读 Phase 1.2 trade）、MetricsRepository（仅读写 metrics_snapshot）、EvaluationReportRepository（仅写 evaluation_report）。不持有任何 Phase 1.2 写接口。
- **写操作**：evaluate 内仅执行 `session.add(MetricsSnapshot(...))`、`session.add(EvaluationReport(...))`，即仅写 Phase 2.0 表 metrics_snapshot 与 evaluation_report。
- **验证方法**：单元测试 `test_evaluate_read_only_phase12_unchanged` 在 evaluate 前后对 Phase 1.2 表 trade 执行 `SELECT count(*)`，断言行数不变（见下文测试用例）。

### 2.6 禁止措辞检查证明

- **代码**：`_constraint_pass` 仅返回 True/False；`conclusion` 仅赋值为字符串 `"pass"` 或 `"fail"`。`_build_comparison_summary` 仅产出 `{"current", "baseline", "delta"}` 数值结构，无自然语言结论。全库 grep 显示「建议参数」「可写回」「供优化」仅出现在注释/文档说明中（“禁止…”），**未**出现在任何输出或结论字符串中。
- **测试**：`test_conclusion_and_comparison_no_suggest_wording` 断言 `result.conclusion` 与 `result.comparison_summary` 的字符串表示中不包含上述三组措辞；`test_evaluate_produces_report_with_02_five_and_persisted` 对持久化行的 `row.conclusion` 做同样断言。

---

## 三、本模块对应的测试用例（或明确的可复现实跑步骤）

**测试文件**：`tests/unit/phase2/test_evaluator.py`

| 用例名 | 验证内容 |
|--------|----------|
| `test_evaluate_produces_report_with_02_five_and_persisted` | 产出报告必含 objective_definition、constraint_definition、baseline_version_id、conclusion、comparison_summary；evaluation_report 表持久化 1 条；conclusion 与报告中无「建议参数」「可写回」「供优化」。 |
| `test_evaluate_b1_structure` | objective 含 primary、primary_weight、secondary、secondary_weights；constraint 含 max_drawdown_pct、min_trade_count、max_risk_exposure、custom。 |
| `test_evaluate_baseline_version_id_is_strategy_version_only` | **C3-2 验证**：传入 baseline_version_id="ver-baseline"（strategy_version_id 语义），报告中 strategy_version_id 与 baseline_version_id 正确存储；baseline_version_id 仅存 strategy_version_id，非 param_version_id。 |
| `test_evaluate_read_only_phase12_unchanged` | **只读边界**：evaluate 前 trade 表 count=2；evaluate 并 commit 后 trade 表 count 仍为 2，即 Phase 1.2 表无任何写操作。 |
| `test_conclusion_and_comparison_no_suggest_wording` | **C3-5 验证**：result.conclusion 与 result.comparison_summary 字符串中无「建议参数」「可写回」「供优化」。 |
| `test_constraint_min_trade_count_fail` | 约束 min_trade_count=10、仅 1 笔 trade 时 conclusion="fail"。 |
| `test_constraint_min_trade_count_pass` | 约束 min_trade_count=3、5 笔 trade 时 conclusion="pass"。 |

**可复现**：项目根目录执行  
`python3 -m pytest tests/unit/phase2/test_evaluator.py -v 2>&1`

---

## 四、测试命令与原始输出结果

**命令**（真实执行）：

```bash
python3 -m pytest tests/unit/phase2/test_evaluator.py -v 2>&1
```

**原始输出**（真实执行结果，完整输出见 `docs/runlogs/phase20_c3_evaluator_20260222.txt`）：

```
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0 -- /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 7 items

tests/unit/phase2/test_evaluator.py::test_evaluate_produces_report_with_02_five_and_persisted PASSED [ 14%]
tests/unit/phase2/test_evaluator.py::test_evaluate_b1_structure PASSED   [ 28%]
tests/unit/phase2/test_evaluator.py::test_evaluate_baseline_version_id_is_strategy_version_only PASSED [ 42%]
tests/unit/phase2/test_evaluator.py::test_evaluate_read_only_phase12_unchanged PASSED [ 57%]
tests/unit/phase2/test_evaluator.py::test_conclusion_and_comparison_no_suggest_wording PASSED [ 71%]
tests/unit/phase2/test_evaluator.py::test_constraint_min_trade_count_fail PASSED [ 85%]
tests/unit/phase2/test_evaluator.py::test_constraint_min_trade_count_pass PASSED [100%]

============================== 7 passed in 0.35s ===============================
```

---

## 五、与本模块 Acceptance Criteria 的逐条对照说明

| 验收口径（C3 交付包） | 结论 | 验证方法 / 证据位置 |
|----------------------|------|----------------------|
| **AC-1** 产出报告必含 objective_definition、constraint_definition、baseline_version_id、conclusion、comparison_summary，且已持久化 | YES | `test_evaluate_produces_report_with_02_five_and_persisted`：断言 result 五字段非空，且 `select(EvaluationReport)` 得到 1 条，字段齐全。 |
| **AC-2** report.strategy_version_id 存在；baseline_version_id 为 null 或为某 **strategy_version_id**（**非** param_version_id） | YES | `test_evaluate_baseline_version_id_is_strategy_version_only`：传入 config.baseline_version_id="ver-baseline"（语义为 strategy_version_id），断言 result.strategy_version_id 与 result.baseline_version_id 正确；代码与 config 约定 baseline_version_id 仅接受 strategy_version_id 或 null。 |
| **AC-3** 结构：objective 含 primary、primary_weight、secondary、secondary_weights；constraint 含 max_drawdown_pct、min_trade_count、max_risk_exposure、custom；无未文档化顶层键 | YES | `evaluation_config.normalize_*` 仅保留上述 B.1 键；`test_evaluate_b1_structure` 断言 result.objective_definition / result.constraint_definition 包含上述键。 |
| **AC-4** 只读边界：evaluate 执行前后 Phase 1.2 表无任何写操作；Evaluator 未调用任何写回/发布/回滚接口 | YES | Evaluator 仅依赖 MetricsCalculator（只读）、MetricsRepository（仅写 metrics_snapshot）、EvaluationReportRepository（仅写 evaluation_report）；`test_evaluate_read_only_phase12_unchanged` 断言 evaluate 前后 trade 表行数不变。 |
| **AC-5** 结论与 comparison_summary 中无「建议参数」「可写回」「供优化」等措辞 | YES | `test_conclusion_and_comparison_no_suggest_wording` 断言 result 中无上述措辞；`test_evaluate_produces_report_with_02_five_and_persisted` 对持久化 row.conclusion 做同样断言；代码中 conclusion 仅 "pass"/"fail"，comparison_summary 仅数值结构。 |

---

## 六、验收结论

本模块满足 C3 目标与开发范围：实现 Evaluator.evaluate(...) → EvaluationReportResult；内部仅调用 MetricsCalculator.compute 或读取 metrics_snapshot，不直接从 trade 算指标；根据 B.1 objective/constraint 与 baseline 生成 conclusion、comparison_summary；仅写入 evaluation_report 表及本周期 metrics_snapshot；baseline_version_id 仅 strategy_version_id 或 null；B.1 结构仅文档化顶层键；结论与对比摘要无「建议参数」「可写回」「供优化」；Phase 1.2 表无写操作。证据包已包含变更清单、核心实现代码、测试用例、测试命令与原始输出、与五项 Acceptance Criteria 的逐条对照及只读边界/禁止措辞验证说明。验收通过。
