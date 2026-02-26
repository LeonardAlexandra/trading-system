# Phase1.1 D2 工程级校验证据包

**模块**: D2 - EXTERNAL_SYNC 定价优先级测试  
**依据**: 《Phase1.1 开发交付包》D2 条款  
**日期**: 2026-02-05  

---

## 0. D2 条款对齐表

| Clause ID | Phase1.1 原文条款（保持原语义） | 对条款的理解（1 句话） |
|----------|----------------------------------|------------------------|
| D2-01 | 验证 C3 中 EXTERNAL_SYNC 的定价优先级（交易所价 > 本地参考价 > 兜底价）被正确执行，且落库 trade 的价格与预期档位一致 | 确保交易所价 > 本地参考价 > 兜底价，且 trade.price 与所选档位一致 |
| D2-02 | 测试必须覆盖至少三档优先级中的每一档；边界情况（多档同时存在时取最高优先）需覆盖 | 覆盖交易所价、本地参考价、兜底价三档，以及多档同时存在取最高优先 |
| D2-03 | 不依赖真实交易所；使用 mock 或 fixture 数据 | 测试数据为 ReconcileItem fixture/mock，无真实交易所依赖 |
| D2-04 | 有交易所价时使用交易所价；无交易所价有本地参考价时使用本地参考价；仅兜底价时使用兜底价；测试可重复运行且通过 | 验收口径：三档行为 + 可重复通过 |

---

## 1. 目标校验矩阵（逐条覆盖 D2 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式（测试/脚本/命令） | 结果 |
|----------|-------------------|------------------------|----------------------------|------|
| D2-01 | 定价优先级正确且落库 price 与档位一致 | src/execution/position_manager.py:49-62, 112-116, 160-175 | tests/integration/external_sync_pricing_test.py 三档 + 多档测试 + test_d2_external_sync_pricing.py | 通过 |
| D2-02 | 覆盖三档 + 多档取最高优先 | tests/integration/external_sync_pricing_test.py:98-158, 161-198 | pytest tests/integration/external_sync_pricing_test.py | 通过 |
| D2-03 | 使用 mock/fixture，不依赖真实交易所 | tests/integration/external_sync_pricing_test.py 全文件（ReconcileItem 构造） | 测试仅用内存 SQLite + ReconcileItem 入参 | 通过 |
| D2-04 | 三档验收 + 可重复通过 | 同上 + position_manager.resolve_price_and_tier | pytest -q tests/integration/external_sync_pricing_test.py 多次运行 | 通过 |

---

## 2. 关键实现快照（Code Snapshot）

### 2.1 定价优先级处理逻辑（交易所价 > 本地参考价 > 兜底价）

**文件**: `src/execution/position_manager.py`

```python
# 49-62：resolve_price_and_tier
def resolve_price_and_tier(item: ReconcileItem) -> Tuple[Decimal, str]:
    """
    C3-04：定价优先级写死 —— 交易所价 > 本地参考价 > 兜底价。
    返回 (price, tier) 供落库与日志可追溯（C3-05）。
    """
    if item.exchange_price is not None:
        return (item.exchange_price, PRICE_TIER_EXCHANGE)
    if item.local_ref_price is not None:
        return (item.local_ref_price, PRICE_TIER_LOCAL_REF)
    if item.fallback_price is not None:
        return (item.fallback_price, PRICE_TIER_FALLBACK)
    raise ValueError(
        "ReconcileItem must have at least one of exchange_price, local_ref_price, fallback_price"
    )
```

**reconcile 内使用**（锁外先解析，锁内写 trade + log）：

```python
# 112-116：锁外准备
resolved: List[Tuple[ReconcileItem, Decimal, str]] = []
for item in items:
    price, tier = resolve_price_and_tier(item)
    resolved.append((item, price, tier))
# ...
# 141-175：锁内写 EXTERNAL_SYNC trade（price=price）+ position_reconcile_log（price_tier=tier）
for item, price, tier in resolved:
    # ...
    trade = Trade(..., price=price, ...)
    await self._reconcile_log_repo.log_event_in_txn(..., price_tier=tier)
    logger.info("... price=%s price_tier=%s", ..., price, tier)
```

### 2.2 Mock 数据与结构

- **ReconcileItem**：`external_trade_id`, `symbol`, `side`, `quantity`, `exchange_price`, `local_ref_price`, `fallback_price`（三价可选，用于模拟三档场景）。
- **场景 1（交易所价）**：`exchange_price=Decimal("60000")`, `local_ref_price`/`fallback_price` 也填；断言 `trade.price == 60000`。
- **场景 2（本地参考价）**：`exchange_price=None`, `local_ref_price=Decimal("3500")`, `fallback_price=Decimal("3000")`；断言 `trade.price == 3500`。
- **场景 3（兜底价）**：`exchange_price=None`, `local_ref_price=None`, `fallback_price=Decimal("100")`；断言 `trade.price == 100`。
- **场景 4（多档取最高）**：三档均非 None；断言 `trade.price == exchange_price`（62000）。

### 2.3 日志记录定价优先级

**文件**: `src/execution/position_manager.py` 191-195 行

```python
logger.info(
    "reconcile sync_trade strategy_id=%s external_trade_id=%s symbol=%s side=%s "
    "quantity=%s price=%s price_tier=%s",
    strategy_id, item.external_trade_id, item.symbol, item.side,
    item.quantity, price, tier,
)
```

档位同时落盘至 `position_reconcile_log.price_tier`（185-189 行）。

---

## 3. 测试与实跑输出（原始证据）

### 3.1 仅跑 D2 新增测试文件

```bash
cd trading_system && python -m pytest tests/integration/external_sync_pricing_test.py -v --tb=short
```

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
...
collected 5 items

tests/integration/external_sync_pricing_test.py::test_d2_exchange_price_used_when_present PASSED [ 20%]
tests/integration/external_sync_pricing_test.py::test_d2_local_ref_used_when_no_exchange PASSED [ 40%]
tests/integration/external_sync_pricing_test.py::test_d2_fallback_used_when_only_fallback PASSED [ 60%]
tests/integration/external_sync_pricing_test.py::test_d2_multi_tier_takes_highest_priority PASSED [ 80%]
tests/integration/external_sync_pricing_test.py::test_d2_price_tier_persisted_in_log PASSED [100%]

============================== 5 passed in 0.22s ===============================
```

### 3.2 pytest -q（全量）

```bash
python -m pytest -q
```

```
........................................................................ [ 36%]
........................................................................ [ 72%]
......................................................                   [100%]
198 passed in 9.74s
```

### 3.3 pytest -ra（全量详细）

```bash
python -m pytest -ra
```

（节选）  
`tests/integration/external_sync_pricing_test.py .....` 与 `tests/integration/test_d2_external_sync_pricing.py ............` 均通过，最终：`198 passed in 9.62s`。

### 3.4 pytest -q tests/integration

```bash
python -m pytest -q tests/integration
```

```
........................................................................ [ 64%]
.......................................                                  [100%]
111 passed in 5.44s
```

---

## 4. 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否正确使用了交易所价 > 本地计算价 > 兜底价的优先级？ | **是** | position_manager.resolve_price_and_tier 写死顺序；三档 + 多档测试均断言 trade.price 与预期一致 |
| 是否验证了每一种定价场景（交易所价、本地价、兜底价）？ | **是** | external_sync_pricing_test.py 中 test_d2_exchange_* / test_d2_local_ref_* / test_d2_fallback_* + test_d2_multi_tier_* |
| 是否成功执行了所有测试，并记录了正确的定价优先级？ | **是** | pytest -q 全量 198 passed；reconcile 日志与 position_reconcile_log.price_tier 落盘；test_d2_price_tier_persisted_in_log 校验 log 中档位 |
| 是否存在残余风险？ | **无** | 不依赖真实交易所；锁与事务边界未改动；仅新增独立测试文件，未修改定价业务逻辑 |

---

## 5. 变更清单（Change Manifest）

**说明**：当前工作区非 git 仓库，以下为本次 D2 交付涉及的文件列表及说明。

| 文件 | 变更类型 | 说明 | 对应 Clause |
|------|----------|------|-------------|
| tests/integration/external_sync_pricing_test.py | 新增 | D2 白名单要求的独立测试文件：三档落库 price 校验、多档取最高优先、price_tier 落盘校验；mock 数据，不依赖真实交易所 | D2-01, D2-02, D2-03, D2-04 |
| docs/Phase1.1_D2_工程级校验证据包.md | 新增 | D2 工程级校验证据包（本文件） | 验收输入 |

**未修改**：`src/execution/position_manager.py`、`src/execution/trading_engine.py` 未改动（定价逻辑已满足 C3/D2，仅通过测试验证）。

---

## 6. 放行自检

- [x] D2 所有 Clause 在校验矩阵中逐条覆盖  
- [x] 定价优先级机制正确执行，三种优先级场景 + 多档取最高均测试通过  
- [x] 日志与 position_reconcile_log.price_tier 正确记录定价档位  
- [x] 工程级校验证据包完整、可复现（pytest 命令与输出已保留）

**结论**：D2 满足《Phase1.1 开发交付包》验收口径，可放行。
