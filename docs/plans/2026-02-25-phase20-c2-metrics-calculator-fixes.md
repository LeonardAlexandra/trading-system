# Phase2.0 C2 MetricsCalculator Evidence Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix Phase2.0 C2 MetricsCalculator evidence and behavior gaps so that metrics computation is clearly aligned with the “strategy + version + time range” intent, max_drawdown semantics are consistent, and read-only guarantees are test-backed and auditable.

**Architecture:** Keep MetricsCalculator as a thin, read-only computation layer over Phase 1.2 `trade` data, using `TradeRepository` for data access. Version semantics are documented as trade-layer–agnostic in C2 (Option B), with version-aware persistence deferred to downstream modules. Tests in `tests/unit/phase2/test_metrics_calculator.py` are the primary executable specification for C2 behavior.

**Tech Stack:** Python 3.11, SQLAlchemy async ORM, Pytest, SQLite in-memory test DB.

---

### Task 1: Clarify C2 version semantics (Option B) in tests

**Files:**
- Modify: `src/phase2/metrics_calculator.py`
- Modify: `tests/unit/phase2/test_metrics_calculator.py`

**Step 1: Extend test for strategy+version+time range behavior**
- Update `test_compute_returns_b2_five_metrics` to also assert that `MetricsCalculator.compute` reads trades strictly by `strategy_id + period_start + period_end`, not by `strategy_version_id`.
- Implement a lightweight spy around `TradeRepository.list_by_strategy_and_executed_time_range` inside the test to capture the arguments used during `compute`.
- Assert that the spy recorded exactly one call, with the expected `(strategy_id, period_start, period_end)` and no version information.

**Step 2: Document Option B in docstrings**
- Ensure `MetricsCalculator.compute` docstring explicitly states that, under current Phase 1.2 schema, version-level filtering is not possible at the trade layer and that `strategy_version_id` / `param_version_id` are pass-through context for downstream modules (e.g. C3/C4 writing to `metrics_snapshot`).

**Step 3: Run focused tests**
- Run: `python3 -m pytest tests/unit/phase2/test_metrics_calculator.py::test_compute_returns_b2_five_metrics -v`
- Expect: test passes, confirming behavior and the recorded call arguments.

---

### Task 2: Lock max_drawdown type and semantics to Decimal("0")

**Files:**
- Modify: `src/phase2/metrics_result.py`
- Modify: `src/phase2/metrics_calculator.py`
- Modify: `tests/unit/phase2/test_metrics_calculator.py`

**Step 1: Add a type-level test for max_drawdown**
- In `test_metrics_result_no_conclusion_baseline` (or a new dedicated test), add an assertion that `MetricsResult.max_drawdown` is typed as `Decimal` (non-Optional).
- Example: inspect `MetricsResult.__dataclass_fields__["max_drawdown"].type` to ensure it is `Decimal`.

**Step 2: Make tests expect non-optional max_drawdown values**
- Ensure existing tests (`test_compute_no_trades_only_rejections`, `test_compute_single_trade_max_drawdown_zero`, and others) assert that `max_drawdown` is a `Decimal` and equals `Decimal("0")` when there are zero or one trades.

**Step 3: Update MetricsResult definition**
- Change `max_drawdown` type in `MetricsResult` from `Optional[Decimal]` to `Decimal`.
- Confirm that no callers expect `None` for `max_drawdown`.

**Step 4: Verify _compute_b2_metrics always returns Decimal**
- Double-check `_compute_b2_metrics` to ensure:
  - For `n == 0`, `max_drawdown` is `Decimal("0")`.
  - For `n >= 1`, `max_drawdown` is computed as a `Decimal` from the equity curve and never `None`.
- Update docstring to make the “no trade or only one trade → Decimal('0')” contract explicit.

**Step 5: Run focused and full C2 tests**
- Run: `python3 -m pytest tests/unit/phase2/test_metrics_calculator.py::test_metrics_result_no_conclusion_baseline -v`
- Run: `python3 -m pytest tests/unit/phase2/test_metrics_calculator.py -v`

---

### Task 3: Strengthen read-only guarantees for compute

**Files:**
- Modify: `tests/unit/phase2/test_metrics_calculator.py`

**Step 1: Instrument AsyncSession write paths in the test**
- In `test_compute_read_only_no_write`, wrap the `AsyncSession` methods that would indicate writes:
  - `session.add`
  - `session.commit`
  - `session.flush`
- Use small spy wrappers that increment counters and then delegate to the original implementation.

**Step 2: Call compute under instrumentation**
- With the spies installed, call `MetricsCalculator.compute` for a non-empty trade set.
- After the call, assert that:
  - `add` was never called during compute.
  - `commit` was never called during compute.
  - `flush` was never called during compute.

**Step 3: Keep the existing “data unchanged” assertion**
- Retain the final check that the number and identity of trades in the database are unchanged before and after `compute`, using `list_by_strategy_and_executed_time_range`.

**Step 4: Run the strengthened read-only test**
- Run: `python3 -m pytest tests/unit/phase2/test_metrics_calculator.py::test_compute_read_only_no_write -v`

---

### Task 4: Update C2 evidence pack for version semantics, max_drawdown, and read-only proof

**Files:**
- Modify: `docs/phase2.0/Phase2.0_C2_模块证据包.md`
- Add/Modify: `docs/runlogs/phase20_c2_metrics_YYYYMMDD.txt` (new runlog for this run)

**Step 1: Record latest pytest run**
- Run: `python3 -m pytest tests/unit/phase2/test_metrics_calculator.py -v 2>&1 | tee docs/runlogs/phase20_c2_metrics_20260225.txt`
- This creates a fresh, auditable runlog for the C2 module tests.

**Step 2: Document Option B version semantics**
- In the evidence pack, add a dedicated subsection under core implementation or B.2口径说明：
  - Explicitly state that the current Phase 1.2 `trade` schema has no `strategy_version_id` (or equivalent) column.
  - Declare that C2 follows **Option B**: version filtering cannot be done at the trade layer; `strategy_version_id` / `param_version_id` are accepted as inputs but only used for downstream persistence into `metrics_snapshot` (C3/C4), not for trade selection.
  - Update the Acceptance Criteria table row “给定策略+版本+时间范围可返回 B.2 五指标” to describe the **real** behavior: C2 computes metrics for a given `strategy_id + 时间范围` given the current schema, and the “版本” dimension is realized only when metrics are written to `metrics_snapshot` by later modules.

**Step 3: Document max_drawdown type and semantics**
- Add a bullet or table row clarifying:
  - `MetricsResult.max_drawdown` is a `Decimal` (non-Optional).
  - It is always computed from the equity curve, with `Decimal("0")` returned when there are zero or one trades.
  - Point to the updated tests that lock this behavior.

**Step 4: Surface the strengthened read-only test snippet**
- In the evidence pack, include the key code snippet from `test_compute_read_only_no_write` showing:
  - The spy wrappers around `session.add` / `session.commit` / `session.flush`.
  - The assertion that these counters remain zero after `compute`.

**Step 5: Embed full pytest output in the evidence pack**
- Copy the full text output from the latest `pytest` run into the “测试命令与原始输出” section of the C2 evidence pack so that the document is self-contained and auditable without referencing external files.

**Step 6: Verify acceptance mapping**
- Update the Acceptance Criteria vs tests table to:
  - Reflect Option B wording for the “strategy+version+time range” row.
  - Reference the new/updated tests for max_drawdown semantics and read-only guarantees.

