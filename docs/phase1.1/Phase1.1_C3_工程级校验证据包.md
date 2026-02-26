# C3 工程级校验证据包（Phase1.1 系统级封版修订版）

**模块**: C3 - PositionManager.reconcile → EXTERNAL_SYNC（含定价优先级）  
**依据**: Phase1.1 开发交付包 C3 条款 + 封版要求（幂等 DB 兜底 + price_tier 落盘）  
**日期**: 2026-02-05  

---

## 1. 目标校验矩阵（逐条覆盖 C3 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式（测试/脚本/命令） | 结果 |
|-----------|------------------|------------------------|----------------------------|------|
| C3-01 | 对需同步的差异生成 EXTERNAL_SYNC trade 并写入 trade 表（A2） | position_manager.py:149-168 | test_d2_external_sync_trade_uses_* 断言 trade.source_type==EXTERNAL_SYNC 且 trade 存在 | PASS |
| C3-02 | 更新 position_snapshot | position_manager.py:170-177 | test_d2_reconcile_updates_position_and_writes_log 断言 Position 已更新且 quantity 一致 | PASS |
| C3-03 | 写入 position_reconcile_log（A3）含 external_trade_id、event_type | position_manager.py:178-184 | test_d2_reconcile_updates_position_and_writes_log 断言 SYNC_TRADE、external_trade_id、price_tier | PASS |
| C3-04 | 定价优先级写死：交易所价 > 本地参考价 > 兜底价 | position_manager.py:46-59（resolve_price_and_tier） | test_resolve_price_tier_* 与 test_d2_external_sync_trade_uses_* 三档场景 | PASS |
| C3-05 | 档位可追溯（必须落盘） | position_manager.py:178-184；position_reconcile_log.price_tier | test_d2_price_tier_persisted_in_reconcile_log、test_d2_reconcile_* 断言 log_row.price_tier | PASS |
| C3-06 | reconcile 写路径必须持 ReconcileLock，与 C1/C2 互斥 | position_manager.py:108-117（lock.use_lock） | 写 trade/position/log 均在 use_lock 块内；test_c3_concurrent_* 断言 1 trade | PASS |
| C3-07 | trade + position_snapshot + position_reconcile_log 同一事务/一致性边界 | position_manager.py:125-131 + session.begin_nested 单条 savepoint | test_d2_* 均在 session.begin() 内调用；IntegrityError 时 savepoint 回滚，外事务有效 | PASS |
| C3-08 | 使用 A2 source_type=EXTERNAL_SYNC、幂等键；A3 event_type 封闭枚举 | position_manager.py:16,152,179；trade / position_reconcile_log | SOURCE_TYPE_EXTERNAL_SYNC、SYNC_TRADE；external_trade_id 必填；price_tier 落盘 | PASS |

**封版增项**

| 封版项 | 实现位置 | 校验方式 | 结果 |
|--------|----------|----------|------|
| 幂等 DB 兜底：UNIQUE 冲突捕获 IntegrityError 视为幂等成功 | position_manager.py:147-201（try/except IntegrityError + begin_nested） | test_c3_idempotent_integrity_error_treated_as_success | PASS |
| 并发 reconcile 同一 (strategy_id, external_trade_id)：仅 1 trade，position/log 不重复 | position_manager.py 全流程 | test_c3_concurrent_reconcile_same_external_trade_id | PASS |
| price_tier 落盘：position_reconcile_log.price_tier 列 | 016 migration；position_reconcile_log.py；log_event_in_txn(..., price_tier=) | test_d2_price_tier_persisted_in_reconcile_log；test_d2_reconcile_* assert log_row.price_tier | PASS |

---

## 2. 关键实现快照（Code Snapshot）

### 2.1 幂等 DB 兜底 + savepoint（锁内，同一外事务）

- 先查再写仅作优化；最终幂等由 A2 UNIQUE(strategy_id, external_trade_id) 冲突兜底。
- 写 trade 时捕获 IntegrityError，视为幂等成功（skipped_idempotent += 1），reconcile 不整体失败。
- 单条 item 使用 `session.begin_nested()`（savepoint），IntegrityError 时仅回滚本条，外事务仍有效，保证 release 锁可执行。

```133:201:src/execution/position_manager.py
            for item, price, tier in resolved:
                existing = await self._trade_repo.get_by_strategy_external_trade_id(...)
                if existing is not None:
                    skipped_idempotent += 1
                    ...
                    continue
                try:
                    async with session.begin_nested():
                        # C3-01 写 trade
                        await self._trade_repo.create(trade)
                        # C3-02 更新 position
                        await self._position_repo.upsert(...)
                        # C3-03 写 log（含 price_tier）
                        await self._reconcile_log_repo.log_event_in_txn(..., price_tier=tier)
                        synced += 1
                except IntegrityError:
                    skipped_idempotent += 1
                    logger.info("reconcile idempotent skip (unique conflict) ...")
                    continue
```

### 2.2 定价优先级与 price_tier 落盘

- 定价优先级：resolve_price_and_tier（position_manager.py:46-59）写死 EXCHANGE > LOCAL_REF > FALLBACK。
- SYNC_TRADE 写入时调用 log_event_in_txn(..., price_tier=tier)，持久化到 position_reconcile_log.price_tier。

```178:184:src/execution/position_manager.py
                await self._reconcile_log_repo.log_event_in_txn(
                    strategy_id=strategy_id,
                    event_type=SYNC_TRADE,
                    external_trade_id=item.external_trade_id,
                    price_tier=tier,
                )
```

### 2.3 Migration 016：position_reconcile_log.price_tier

```1:35:alembic/versions/016_c3_position_reconcile_log_price_tier.py
"""C3: position_reconcile_log 增加 price_tier 列（定价档位落盘可追溯）"""
...
def upgrade():
    op.add_column(
        "position_reconcile_log",
        sa.Column(
            "price_tier",
            sa.String(50),
            nullable=True,
            comment="C3 定价档位：EXCHANGE/LOCAL_REF/FALLBACK，仅 SYNC_TRADE 时非空",
        ),
    )
def downgrade():
    op.drop_column("position_reconcile_log", "price_tier")
```

### 2.4 ORM：PositionReconcileLog.price_tier

```49:58:src/models/position_reconcile_log.py
    event_type = Column(...)
    price_tier = Column(
        String(50),
        nullable=True,
        comment="C3 定价档位：EXCHANGE/LOCAL_REF/FALLBACK，仅 SYNC_TRADE 时非空",
    )
    created_at = Column(...)
```

### 2.5 Repo：log_event_in_txn(..., price_tier=)

```34:55:src/repositories/position_reconcile_log_repo.py
    async def log_event_in_txn(
        self,
        strategy_id: str,
        event_type: str,
        external_trade_id: Optional[str] = None,
        price_tier: Optional[str] = None,
    ) -> PositionReconcileLog:
        ...
        log = PositionReconcileLog(
            strategy_id=strategy_id,
            event_type=event_type,
            external_trade_id=external_trade_id,
            price_tier=price_tier,
        )
        self.session.add(log)
        return log
```

---

## 3. 测试与实跑输出（原始证据）

### 3.1 全量测试 -q

```bash
.venv/bin/python -m pytest -q
```

```
........................................................................ [ 40%]
........................................................................ [ 80%]
...................................                                      [100%]
179 passed in 12.48s
```

### 3.2 D2/C3 封版相关测试 -v（原始输出）

```bash
.venv/bin/python -m pytest tests/integration/test_d2_external_sync_pricing.py -v
```

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.6.0
...
tests/integration/test_d2_external_sync_pricing.py::test_resolve_price_tier_exchange_first PASSED [  8%]
tests/integration/test_d2_external_sync_pricing.py::test_resolve_price_tier_local_ref_when_no_exchange PASSED [ 16%]
tests/integration/test_d2_external_sync_pricing.py::test_resolve_price_tier_fallback_only PASSED [ 25%]
tests/integration/test_d2_external_sync_pricing.py::test_resolve_price_tier_missing_all_raises PASSED [ 33%]
tests/integration/test_d2_external_sync_pricing.py::test_d2_external_sync_trade_uses_exchange_price PASSED [ 41%]
tests/integration/test_d2_external_sync_pricing.py::test_d2_external_sync_trade_uses_local_ref_when_no_exchange PASSED [ 50%]
tests/integration/test_d2_external_sync_pricing.py::test_d2_external_sync_trade_uses_fallback_only PASSED [ 58%]
tests/integration/test_d2_external_sync_pricing.py::test_d2_reconcile_updates_position_and_writes_log PASSED [ 66%]
tests/integration/test_d2_external_sync_pricing.py::test_d2_price_tier_persisted_in_reconcile_log PASSED [ 75%]
tests/integration/test_d2_external_sync_pricing.py::test_c3_concurrent_reconcile_same_external_trade_id PASSED [ 83%]
tests/integration/test_d2_external_sync_pricing.py::test_c3_idempotent_integrity_error_treated_as_success PASSED [ 91%]
tests/integration/test_d2_external_sync_pricing.py::test_d2_idempotent_skip_duplicate_external_trade_id PASSED [100%]

============================== 12 passed in 0.41s ==============================
```

### 3.3 封版测试覆盖说明

| 测试用例 | 覆盖内容 |
|----------|----------|
| test_c3_concurrent_reconcile_same_external_trade_id | 两并发会话对同一 (strategy_id, external_trade_id) reconcile；断言 trade 仅 1 条，SYNC_TRADE log 仅 1 条，position 一致 |
| test_c3_idempotent_integrity_error_treated_as_success | 先插入同幂等键 trade 并 commit，再 mock get_by 返回 None 触发 insert → IntegrityError；断言 skipped_idempotent=1、synced=0、trade 仍为 1 条 |
| test_d2_price_tier_persisted_in_reconcile_log | 三档各跑一次 reconcile，查询 position_reconcile_log 断言 price_tier 分别为 EXCHANGE、LOCAL_REF、FALLBACK |
| test_d2_reconcile_updates_position_and_writes_log | 断言 log_row.price_tier == PRICE_TIER_FALLBACK（落盘） |

---

## 4. 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否严格使用 A2 的 source_type=EXTERNAL_SYNC 与幂等键？ | **是** | 仅写 SOURCE_TYPE_EXTERNAL_SYNC；判重 + UNIQUE 冲突捕获 IntegrityError 双保险 |
| 是否严格使用 A3 event_type 封闭枚举？ | **是** | 仅使用 SYNC_TRADE；未新增 event_type |
| 是否 reconcile 写路径必经 ReconcileLock 且锁内无外部 I/O？ | **是** | 写路径在 lock.use_lock 块内，锁内仅 DB 写 |
| 是否确保 trade + snapshot + reconcile_log 同一事务/一致性边界？ | **是** | 调用方 session.begin()；单条 item 用 begin_nested，IntegrityError 仅回滚 savepoint，外事务有效 |
| price_tier 是否落盘可追溯？ | **是** | position_reconcile_log.price_tier 列 + log_event_in_txn(..., price_tier=tier) + 单测断言 |
| 是否存在残余风险？ | **有说明** | 调用方须保证 strategy_runtime_state 行存在；否则 acquire 失败与锁被占用不可区分 |

---

## 5. 变更清单（Change Manifest）

| 文件 | 说明 | 对应条款 |
|------|------|----------|
| src/execution/position_manager.py | IntegrityError 捕获 + begin_nested savepoint；log_event_in_txn(..., price_tier=tier) | C3 封版幂等兜底、C3-05 落盘 |
| src/models/position_reconcile_log.py | 新增 price_tier 列 | C3-05 落盘 |
| src/repositories/position_reconcile_log_repo.py | log_event_in_txn 增加 price_tier 参数并写入 | C3-05 落盘 |
| alembic/versions/016_c3_position_reconcile_log_price_tier.py | 新增 position_reconcile_log.price_tier 列 | C3-05 落盘 |
| tests/integration/test_d2_external_sync_pricing.py | test_d2_price_tier_persisted_in_reconcile_log；test_c3_concurrent_reconcile_same_external_trade_id；test_c3_idempotent_integrity_error_treated_as_success；test_d2_reconcile_* 断言 price_tier | 封版测试 |
| docs/Phase1.1_C3_工程级校验证据包.md | 本证据包（封版修订版） | 验收输入 |

---

## 6. 事务与锁边界（实现约定）

| 项 | 说明 |
|----|------|
| 锁获取位置 | reconcile 内 `async with lock.use_lock(strategy_id)` 进入时 acquire |
| 锁内允许操作 | 仅 DB 写：trade 插入、position 更新、position_reconcile_log 写入（含 price_tier） |
| 锁内禁止操作 | HTTP/RPC、外部数据拉取、长计算、sleep |
| 事务边界 | 调用方在 session.begin() 内调用 reconcile；单条 item 使用 session.begin_nested()，IntegrityError 时仅回滚 savepoint，外事务继续以便 release 锁 |
| 异常路径 | acquire 失败抛 ReconcileLockNotAcquiredError；IntegrityError 捕获后 skipped_idempotent += 1，不整体失败；use_lock finally 保证 release |

---

## 7. 异常与失败语义

| 场景 | 行为 |
|------|------|
| acquire 锁失败 | 抛 ReconcileLockNotAcquiredError；不写任何数据；max_acquire_retries 可配，不无限等待 |
| EXTERNAL_SYNC 幂等（先查存在） | get_by_strategy_external_trade_id 已存在则跳过该条，skipped_idempotent += 1 |
| UNIQUE(strategy_id, external_trade_id) 冲突 | 捕获 IntegrityError，savepoint 回滚本条，skipped_idempotent += 1，reconcile 不整体失败，外事务有效 |
| position_snapshot / reconcile_log 写入失败 | 与 trade 同属 begin_nested 块，失败则 savepoint 回滚，不产生“有 trade 无 snapshot/log” |
| 未在事务内调用 reconcile | 锁内校验 in_transaction()，不通过则抛 RuntimeError |
