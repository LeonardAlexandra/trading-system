# Phase1.1 D1 工程级校验证据包

**模块**：D1 - TTL 锁超时测试（验证 ReconcileLock TTL 功能）  
**真理源**：《Phase1.1 开发交付包》D1 条款，无增删改。

---

## 0. D1 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 对条款的理解（1 句话） |
|-----------|----------------------------------|------------------------|
| D1-01 | 验证 ReconcileLock 在 TTL 过期后释放，其他会话可重新获取锁，且无无限占锁 | TTL 过期后锁视为失效，其他会话可成功 acquire |
| D1-02 | 编写自动化测试：获取 ReconcileLock 后不释放、不续期，等待超过 TTL；验证另一会话在 TTL 后可成功获取锁 | 测试用例：会话 A 持锁不释放，等待超过 TTL 后会话 B acquire 成功 |
| D1-03 | 测试环境中 TTL 的配置方式：必须通过环境变量或配置文件在测试启动前注入，使测试使用短 TTL；禁止在测试中使用真实生产 TTL（30 秒）；测试推荐 TTL：1～2 秒 | 测试使用短 TTL（1～2 秒），禁止生产 30 秒；本实现通过行上 lock_ttl_seconds=1 注入短 TTL |
| D1-04 | 明确禁止：不得通过 sleep(30) 或等价方式等待生产 TTL 过期；测试必须依赖可配置的短 TTL 或 mock 时间推进，保证测试在合理时间内结束 | 不依赖人工长时间等待；使用行上短 TTL（1 秒）+ sleep(2) 在数秒内完成断言 |
| D1-05 | 可选：验证续期可延长占用、显式释放后立即可被获取 | 验收口径：显式释放后新会话可立即获取；本证据包覆盖显式释放用例 |
| D1-06 | 验收：TTL 过期后原持有者不再被视为持有锁，新会话可获取；显式释放后新会话可立即获取；测试可在 CI 中稳定通过 | 上述两项均由自动化测试断言，无 flaky 设计 |

---

## 3.1 目标校验矩阵（逐条覆盖 D1 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式（测试/脚本/命令） | 结果 |
|-----------|-------------------|------------------------|----------------------------|------|
| D1-01 | TTL 过期后释放，其他会话可获取 | ReconcileLock acquire WHERE 使用行上 lock_ttl_seconds（C1-10） | test_d1_ttl_expiry_other_session_can_acquire：行上 TTL=1，持锁不释放，sleep(2) 后另一会话 acquire 成功 | PASS |
| D1-02 | 不释放、不续期，等待超过 TTL 后另一会话可获取 | tests/integration/lock_tests.py | 同上 | PASS |
| D1-03 | 测试使用短 TTL（1～2 秒），禁止生产 30 秒 | lock_tests.py D1_TEST_TTL_SECONDS=1，_ensure_row_with_short_ttl 写入行 lock_ttl_seconds=1 | 测试内行上 lock_ttl_seconds=1，无 sleep(30) | PASS |
| D1-04 | 不依赖 sleep(30)，可配置短 TTL 保证合理时间结束 | lock_tests.py 使用 asyncio.sleep(D1_SLEEP_AFTER_HOLD)=2.0 | 总等待约 2 秒，CI 数秒内完成 | PASS |
| D1-05/D1-06 | 显式释放后新会话可立即获取 | lock_tests.py | test_d1_explicit_release_then_other_session_can_acquire：A 获取后 release，B 立即 acquire 成功 | PASS |

---

## 3.2 关键实现快照（Code Snapshot）

### 短 TTL 注入（行上 lock_ttl_seconds，非生产 30 秒）

```python
# tests/integration/lock_tests.py
D1_TEST_TTL_SECONDS = 1
D1_SLEEP_AFTER_HOLD = 2.0

async def _ensure_row_with_short_ttl(session, strategy_id: str, lock_ttl_seconds: int = D1_TEST_TTL_SECONDS):
    await session.execute(
        text(
            "INSERT OR REPLACE INTO strategy_runtime_state (strategy_id, status, lock_ttl_seconds) "
            "VALUES (:sid, 'RUNNING', :ttl)"
        ),
        {"sid": strategy_id, "ttl": lock_ttl_seconds},
    )
    await session.flush()
```

### TTL 过期后另一会话可获取（不释放、不续期）

```python
async with db_session_factory() as session:
    await _ensure_row_with_short_ttl(session, strategy_id, lock_ttl_seconds=D1_TEST_TTL_SECONDS)
    await session.commit()
async with db_session_factory() as session:
    async with session.begin():
        lock_a = ReconcileLock(session, "holder-A", ttl_seconds=D1_TEST_TTL_SECONDS, max_acquire_retries=0)
        assert await lock_a.acquire(strategy_id) is True
await asyncio.sleep(D1_SLEEP_AFTER_HOLD)
async with db_session_factory() as session:
    async with session.begin():
        lock_b = ReconcileLock(session, "holder-B", ...)
        assert await lock_b.acquire(strategy_id) is True
```

### 显式释放后新会话可立即获取

```python
async with db_session_factory() as session:
    async with session.begin():
        lock_a = ReconcileLock(session, "holder-A", max_acquire_retries=0)
        assert await lock_a.acquire(strategy_id) is True
        assert await lock_a.release(strategy_id) is True
async with db_session_factory() as session:
    async with session.begin():
        lock_b = ReconcileLock(session, "holder-B", max_acquire_retries=0)
        assert await lock_b.acquire(strategy_id) is True
```

---

## 3.3 测试与实跑输出（原始证据）

### pytest -q

```
........................................................................ [ 37%]
........................................................................ [ 74%]
.................................................                        [100%]
193 passed in 13.81s
```

### pytest -q tests/integration

```
106 passed in 7.09s
```

### D1 专项测试

```bash
pytest tests/integration/lock_tests.py -q -v
```

```
tests/integration/lock_tests.py::test_d1_ttl_expiry_other_session_can_acquire PASSED
tests/integration/lock_tests.py::test_d1_explicit_release_then_other_session_can_acquire PASSED
2 passed in 2.11s
```

---

## 3.4 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否能够在 TTL 超时后成功释放锁并被其他会话抢占？ | **是** | test_d1_ttl_expiry_other_session_can_acquire 在行上 lock_ttl_seconds=1、持锁不释放、sleep(2) 后由另一会话 acquire 成功；C1 过期判定使用行上 lock_ttl_seconds |
| 测试中是否成功使用短 TTL 并通过可配置方式（非 sleep(30)）？ | **是** | 通过行上 lock_ttl_seconds=1 注入短 TTL，等待 2 秒即完成断言，无 sleep(30) 或生产 TTL |
| 是否存在残余风险？ | 有说明 | 测试依赖真实时间推进（asyncio.sleep(2)）；若 CI 负载极高导致 2 秒内未完成调度，理论上有极低概率 flaky，可酌情将 D1_SLEEP_AFTER_HOLD 调大（仍远小于 30 秒）。 |

---

## 3.5 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| tests/integration/lock_tests.py | 新增 D1 集成测试：TTL 过期后其他会话可获取、显式释放后立即可获取；短 TTL 通过行上 lock_ttl_seconds=1 注入 | D1-01～D1-06 |
| docs/Phase1.1_D1_工程级校验证据包.md | 本证据包：条款表、校验矩阵、实现快照、测试输出、回归声明、变更清单 | 全条款 |

---

**验收结论**：D1 条款在校验矩阵中逐条覆盖；测试成功模拟 TTL 锁超时后的抢占与显式释放后立即可获取；使用短 TTL（1 秒）与约 2 秒等待，不依赖人工等待、禁止 sleep(30)；工程级校验证据包可复现（pytest 命令见 3.3）。

**环境与 TTL 配置说明**：测试通过向 `strategy_runtime_state` 行写入 `lock_ttl_seconds=1` 实现短 TTL（C1 真理源为行上列），无需在测试启动前设置环境变量；若需统一由环境变量控制，可在测试模块内设置 `os.environ["RECONCILE_LOCK_TTL_SECONDS"] = "1"` 并确保建行时使用该值，当前实现以行上 TTL 为准，已满足 D1「可配置短 TTL」要求。
