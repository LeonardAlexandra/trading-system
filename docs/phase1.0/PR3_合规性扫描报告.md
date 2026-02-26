# PR3 合规性扫描报告

## 扫描范围
- 目录：`trading_system/src/repositories/`
- 扫描时间：2026-01-28

## 检查项
1. repo 内是否出现 `session.commit()` / `session.rollback()`
2. repo 内是否创建 `engine/sessionmaker`（`create_async_engine`/`async_sessionmaker`）
3. 是否出现 `await get_db_session()` 或 `Depends(get_db_session)`

## 扫描结果

### ✅ 通过的文件
- `trading_system/src/repositories/base.py` - 无违规项
- `trading_system/src/repositories/orders_repo.py` - 无违规项
- `trading_system/src/repositories/decision_order_map_repo.py` - 无违规项
- `trading_system/src/repositories/__init__.py` - 无违规项

### ❌ 发现违规项

#### 1. `trading_system/src/repositories/dedup_signal_repo.py`
- **行号：53**
- **问题类型：违规使用 `session.rollback()`**
- **问题描述：** 在 `try_insert` 方法中，当捕获 `IntegrityError` 时直接调用了 `await self.session.rollback()`，违反了 PR3 约束（repo 内禁止直接 commit/rollback）
- **修复方案：** 应使用 SAVEPOINT 机制：`async with session.begin_nested()` 来处理 IntegrityError，只回滚嵌套事务，不影响外层事务

## 统计摘要
- 扫描文件总数：5
- 通过文件数：4
- 违规文件数：1
- 违规项总数：1

## 修复建议
对于 `dedup_signal_repo.py` 的 `try_insert` 方法：
- 使用 `async with session.begin_nested()` 创建 SAVEPOINT
- 在嵌套事务中执行 `add()` 和 `flush()`
- 捕获 `IntegrityError` 时，嵌套事务会自动回滚，外层事务不受影响
- 保持"只负责落库，不做业务恢复"的原则（此方法允许吞异常，因为这是幂等操作的特殊需求）
