# PR3 合规性修复 Diff

## 修复文件
`trading_system/src/repositories/dedup_signal_repo.py`

## 修复内容

### 问题
- **行号：53**
- **违规项：** 直接调用 `await self.session.rollback()`，违反 PR3 约束

### 修复方案
使用 SAVEPOINT 机制（`begin_nested()`）处理 IntegrityError，只回滚嵌套事务，不影响外层事务。

### Diff

```diff
--- a/trading_system/src/repositories/dedup_signal_repo.py
+++ b/trading_system/src/repositories/dedup_signal_repo.py
@@ -39,15 +39,16 @@ class DedupSignalRepository(BaseRepository[DedupSignal]):
         )
         
-        try:
-            self.session.add(dedup_signal)
-            # 尝试 flush 以触发主键冲突检查（不 commit，由上层管理）
-            await self.session.flush()
-            return True
-        except IntegrityError:
-            # 主键冲突（重复信号），回滚 flush 并返回 False
-            await self.session.rollback()
-            return False
+        # 使用 SAVEPOINT 处理 IntegrityError（PR3 约束：禁止直接 rollback）
+        # 嵌套事务回滚不影响外层事务
+        try:
+            async with self.session.begin_nested():
+                self.session.add(dedup_signal)
+                # 尝试 flush 以触发主键冲突检查（不 commit，由上层管理）
+                await self.session.flush()
+            return True
+        except IntegrityError:
+            # 主键冲突（重复信号），SAVEPOINT 已自动回滚，不影响外层事务
+            return False
```

### 修复说明
1. **使用 SAVEPOINT：** 通过 `async with self.session.begin_nested()` 创建嵌套事务
2. **自动回滚：** 当发生 IntegrityError 时，嵌套事务会自动回滚，无需手动调用 rollback()
3. **外层事务保护：** 嵌套事务的回滚不影响外层事务，符合 PR3 约束
4. **保持语义：** 修复后功能保持不变，仍然返回 True/False 表示插入成功/重复
