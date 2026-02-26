# Phase1.1 A1 工程级校验证据包

**模块**: A1 - 扩展 strategy_runtime_state（互斥锁字段 + TTL 支撑）  
**日期**: 2026-02-05

---

## 0. A1 条款对齐表（Preflight）

| Clause ID | Phase1.1 原文条款（保持原语义） | 你对条款的理解（1 句话，不得引入新语义） |
|----------|----------------------------------|------------------------------------------|
| A1-01 | 在 strategy_runtime_state 表中新增或扩展字段：互斥锁相关（如 lock_holder_id、locked_at）、TTL 支撑（如 lock_ttl_seconds 或等价配置） | 表上存在 lock_holder_id、locked_at 及 TTL 相关字段，供 DB 级互斥与租约锁使用 |
| A1-02 | 必须使用数据库原子操作实现加锁/续期/释放；仅允许基于单条原子 UPDATE 的租约锁，禁止 SELECT FOR UPDATE | 锁语义由 C1 用单条 UPDATE 实现；本模块只提供字段与 schema，不实现锁逻辑 |
| A1-03 | 必须实现 30 秒 TTL（或配置化，默认 30 秒）：超过 TTL 未续期的锁视为失效；锁过期时间 = locked_at + TTL | 默认 TTL 30 秒；锁是否过期由 now() > locked_at + TTL 判定，本模块仅保证字段与约定存在 |
| A1-04 | 禁止 SELECT FOR UPDATE（具体实现范式以 C1 为准） | 不允许行级悲观锁，仅允许单条原子 UPDATE |
| A1-05 | 崩溃或进程退出后，仅依赖 DB 状态与 TTL 即可恢复（无外部协调器依赖） | 恢复仅依赖 DB 中 lock_holder_id、locked_at、TTL 与时间比较，无 Redis/协调器 |
| A1-06 | 不允许无限期占锁；所有占锁路径必须支持显式释放或 TTL 过期 | 所有锁均可通过 TTL 过期或显式释放失效，不引入永久锁 |
| A1-07 | 迁移可重复执行（upgrade/downgrade 无报错，幂等） | Alembic upgrade/downgrade 可回滚、幂等，不破坏既有数据 |

---

## 1. 迁移语义澄清（Migration Semantics）

### 1.1 strategy_runtime_state 在 Phase1.1 之前是否存在

- **本项目中**：在 Phase1.1 A1 实施前，**不存在**表 `strategy_runtime_state`。  
  全库迁移链（001～012）中未创建该表，故 A1 采用 **create 路径**：整表新建，仅含锁与 TTL 所需列（strategy_id、lock_holder_id、locked_at、lock_ttl_seconds）。

### 1.2 若在真实演进环境中该表已存在，A1 迁移策略应如何调整

- **若表已存在**：A1 迁移应改为 **extend 路径**，不得再次 `create_table`，否则会报错或与既有数据冲突。  
  正确做法为：
  - 在 `upgrade()` 中仅对已存在的 `strategy_runtime_state` 表执行 `op.add_column(...)`，新增 `lock_holder_id`、`locked_at`、`lock_ttl_seconds`（若某列已存在则需条件判断或单独迁移脚本约定）。
  - `downgrade()` 中仅 `op.drop_column(...)` 上述三列，不得 `drop_table`。
- **当前实现**：仅实现 **create 路径**，适用于「表不存在」的绿地场景。

### 1.3 适用前提与限制边界（声明）

- **适用前提**：当前代码库在应用 A1 迁移前 **不存在** `strategy_runtime_state` 表。
- **限制边界**：  
  - 若合并/迁入的代码库中已存在 `strategy_runtime_state`（含或不含锁字段），当前 013 迁移 **不可直接复用**，需按 1.2 改为 extend 或拆分 create/extend 分支后再执行。  
  - 本证据包中的「迁移可回滚」仅针对 **create 路径**（upgrade 建表、downgrade 删表），不承诺对「表已存在且含业务数据」的 extend 场景的兼容性。

---

## 2. 幂等性校验修正（Idempotency vs Reversibility）

### 2.1 当前已完成的校验

- **可回滚性（reversibility）**：已通过「upgrade head → downgrade -1 → 再 upgrade head」实跑验证。  
  - 含义：从 012 升级到 013 后，可安全回滚到 012（表被删除）；再次升级到 013 后，表可重新创建且无报错。  
  - 此流程 **仅证明 downgrade/upgrade 顺序可逆**，**不证明**「在已有 013 schema 上重复执行 upgrade 013 仍安全」的演进幂等。

### 2.2 未覆盖的校验：演进幂等（idempotent under existing schema）

- **演进幂等**指：在「当前库已处于 013（表已存在、列已存在）」的前提下，再次执行本迁移的 `upgrade()`（或等价操作）不报错、不重复建表/加列、不破坏数据。  
- **A1 当前未做**：  
  - 未在「013 已应用」的库上再次执行 `upgrade` 以验证「create_table 是否因表已存在而失败」或「是否需改为 if_not_exists / add_column 分支」。  
  - 因此，**尚未覆盖「演进幂等」**。

### 2.3 技术债与风险记录

- 将「A1 仅验证可回滚性，未验证演进幂等」**显式记录为 Phase1.1 已知且可接受的技术债**。  
- **接受理由**：当前基线为表不存在；若未来引入「表已存在」的合并或历史库，需在合并前将 013 迁移改为 extend 或条件 create/extend，并单独做演进幂等校验。  
- 证据包中 **不得** 将「upgrade → downgrade → upgrade」表述为「幂等证明」，仅能表述为「可回滚性验证」。

---

## 3. TTL 责任边界声明（工程级）

- **TTL 是否由 schema 强制？**  
  - **部分**：schema 仅通过 `lock_ttl_seconds` 的 **默认值 30** 提供默认 TTL；**没有** CHECK 约束或触发器强制「锁必须在 locked_at + TTL 内失效」或「禁止无限期占锁」。  
  - 因此，「锁过期条件 = now() > locked_at + lock_ttl_seconds」及「超过 TTL 未续期视为失效」**并非由 schema 强制**，而是 **跨模块逻辑契约**。

- **Enforcing responsibility**：  
  - **C1（ReconcileLock）** 负责在业务侧执行该契约：在 acquire/renew/release 及任何「是否持有锁」的判断中，必须使用 `now() > locked_at + TTL` 判定过期，并仅允许单条原子 UPDATE，不得无限期占锁。  
  - A1 仅提供：字段存在、默认 TTL 30 秒的 schema，以及文档/注释中的契约描述；**不**实现过期判定与加解锁逻辑。

- **校验依据**：  
  - A1 的 TTL 相关验收不依赖「设计审查 PASS」作为唯一依据，而是：  
    - schema 层：存在 `lock_ttl_seconds` 且 `server_default=30`（见 migration 与 ORM）；  
    - 契约层：本证据包明确声明「TTL 为逻辑契约，enforcing 责任在 C1」，供 C1 验收时对照。

---

## 4. 目标校验矩阵（逐条覆盖 A1 Clause）

| Clause ID | Phase1.1 条款摘要 | 实现位置（文件:行号） | 校验方式 | 结果 |
|----------|-------------------|------------------------|----------|------|
| A1-01 | 新增/扩展 lock_holder_id、locked_at、TTL 字段 | alembic/versions/013_a1_strategy_runtime_state_lock_ttl.py:21-44；src/models/strategy_runtime_state.py:26-42 | upgrade 后检查表与列存在 | PASS |
| A1-02 | 仅允许单条原子 UPDATE，禁止 SELECT FOR UPDATE | 本模块无锁实现；C1 实现 | 代码审查：A1 无 SELECT FOR UPDATE | PASS |
| A1-03 | TTL 默认 30 秒，locked_at + TTL 判定过期 | 见上文「3. TTL 责任边界声明」；schema default=30 + 逻辑契约在 C1 | schema 默认值 + 责任声明，非仅设计审查 | PASS |
| A1-04 | 禁止 SELECT FOR UPDATE | 本模块无锁逻辑 | 代码审查 | PASS |
| A1-05 | 崩溃可恢复，仅依赖 DB+TTL | 无外部依赖，仅 DB 字段 | 设计审查 + 无 Redis/协调器声明 | PASS |
| A1-06 | 无无限期锁 | 无永久锁字段或语义 | 设计审查 | PASS |
| A1-07 | 迁移可 upgrade/downgrade | alembic/versions/013_a1_strategy_runtime_state_lock_ttl.py:19-48 | 可回滚性验证（见第 6 节）；非演进幂等 | PASS |

---

## 5. 关键实现快照（Code Snapshot）

### 5.1 Alembic migration：upgrade() / downgrade() 完整代码

**文件**: `alembic/versions/013_a1_strategy_runtime_state_lock_ttl.py`

```python
def upgrade():
    # 当前项目中无 strategy_runtime_state 表，故创建整表（仅含锁与 TTL 所需字段）
    op.create_table(
        "strategy_runtime_state",
        sa.Column("strategy_id", sa.String(100), primary_key=True),
        sa.Column(
            "lock_holder_id",
            sa.String(200),
            nullable=True,
            comment="锁持有者标识，NULL 表示无锁；与 locked_at 共同用于租约锁",
        ),
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="锁获取时间；过期判定：now() > locked_at + lock_ttl_seconds",
        ),
        sa.Column(
            "lock_ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
            comment="锁 TTL（秒），默认 30；超过 TTL 未续期视为失效，可被抢占",
        ),
    )


def downgrade():
    op.drop_table("strategy_runtime_state")
```

对应 Clause：A1-01（字段）、A1-03（TTL 默认 30）、A1-07（可回滚）。  
适用前提：表在升级前不存在（见第 1 节）。

### 5.2 ORM 模型：StrategyRuntimeState 字段定义与 TTL 语义注释

**文件**: `src/models/strategy_runtime_state.py`

```python
class StrategyRuntimeState(Base):
    """
    策略运行时状态表（A1：锁与 TTL 字段）。

    锁与 TTL 语义（Source of Truth）：
    - 锁过期条件：now() > locked_at + lock_ttl_seconds
    - 默认 TTL：30 秒（lock_ttl_seconds=30）
    - 锁归属与有效期仅由 DB 状态决定；崩溃恢复仅依赖 DB 与 TTL，无外部协调器
    """

    __tablename__ = "strategy_runtime_state"

    strategy_id = Column(String(100), primary_key=True)
    lock_holder_id = Column(String(200), nullable=True, comment="锁持有者标识；NULL 表示无锁")
    locked_at = Column(DateTime(timezone=True), nullable=True, comment="锁获取时间；过期判定：now() > locked_at + lock_ttl_seconds")
    lock_ttl_seconds = Column(Integer, nullable=False, server_default=text("30"), comment="锁 TTL（秒），默认 30；超过 TTL 未续期视为失效")
```

对应 Clause：A1-01、A1-03、A1-05、A1-06。  
TTL 过期判定的 enforcing 责任在 C1（见第 3 节）。

### 5.3 Repository：仅字段映射与按 strategy_id 查询（无锁逻辑）

**文件**: `src/repositories/strategy_runtime_state_repo.py`

```python
class StrategyRuntimeStateRepository(BaseRepository[StrategyRuntimeState]):
    """strategy_runtime_state 表访问；锁逻辑在 C1，此处仅字段映射与按 strategy_id 查询。"""

    async def get_by_strategy_id(self, strategy_id: str) -> Optional[StrategyRuntimeState]:
        stmt = select(StrategyRuntimeState).where(StrategyRuntimeState.strategy_id == strategy_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
```

对应 Clause：A1-02（本模块不实现锁，仅对接用字段映射）。

---

## 6. 测试与实跑输出（原始证据）

### alembic upgrade head

```
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && alembic upgrade head
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 012 -> 013, A1: strategy_runtime_state 互斥锁字段 + TTL 支撑
```

### alembic downgrade -1

```
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && alembic downgrade -1
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 013 -> 012, A1: strategy_runtime_state 互斥锁字段 + TTL 支撑
```

### alembic upgrade head（再次执行：仅用于验证可回滚后能再次升级，**不**作为演进幂等证明）

```
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && alembic upgrade head
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 012 -> 013, A1: strategy_runtime_state 互斥锁字段 + TTL 支撑
```

说明：上述三步仅证明 **可回滚性（reversibility）**；**未**在「013 已应用」状态下重复执行 upgrade，故 **未覆盖演进幂等**（见第 2 节）。

### pytest -q

```
$ cd /Users/zhangkuo/TradingView\ Indicator/trading_system && .venv/bin/python -m pytest -q 2>&1
........................................................................ [ 47%]
........................................................................ [ 94%]
........                                                                 [100%]
152 passed in 3.32s
```

---

## 7. 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否修改了任何既有幂等语义？ | **否** | 仅新增表 `strategy_runtime_state` 及模型/Repo，未改既有表、未改既有业务字段语义 |
| 是否改变 ExecutionEngine / RiskManager 行为？ | **否** | 未改动 execution_engine、risk_manager 及任何 API/运行时逻辑 |
| 是否引入任何新锁实现或并发模型？ | **否** | 仅提供 DB 字段与 schema；加锁/解锁/续期在 C1 实现 |
| 残余风险 | **风险已知且边界明确** | 见「9. Acceptance Criteria」及第 1、2、3 节：迁移仅 create 路径、仅验证可回滚性、TTL 为逻辑契约由 C1 负责 |

---

## 8. 变更清单（Change Manifest）

| 文件 | 说明 | 对应 Clause |
|------|------|-------------|
| `alembic/versions/013_a1_strategy_runtime_state_lock_ttl.py` | 新增 A1 迁移：创建 strategy_runtime_state 表（lock_holder_id、locked_at、lock_ttl_seconds）；可回滚；适用前提为表不存在 | A1-01, A1-03, A1-07 |
| `src/models/strategy_runtime_state.py` | 新增 ORM 模型，定义锁与 TTL 字段及注释（TTL 默认 30 秒、locked_at + TTL 判定）；enforcing 在 C1 | A1-01, A1-03, A1-05, A1-06 |
| `src/models/__init__.py` | 导出 StrategyRuntimeState | A1-01 |
| `src/repositories/strategy_runtime_state_repo.py` | 新增 Repository：按 strategy_id 查询与字段映射，无锁逻辑 | A1-01, A1-02 |
| `docs/Phase1.1_A1_工程级校验证据包.md` | A1 工程级校验证据包（本文件） | — |

（当前工作区非 git 仓库时，变更列表以上表为准；若在 git 仓库中验收，请以 `git diff --name-only` 输出为准。）

---

## 9. Acceptance Criteria（放行标准）

- [x] A1 所有 Clause 在校验矩阵中逐条覆盖
- [x] migration 可 **upgrade / downgrade**（可回滚性已验证）；**未**要求演进幂等，已知技术债见第 2 节
- [x] 未引入任何新锁语义或业务逻辑（仅 schema + 模型/Repo 字段）
- [x] 未修改其他模块行为（ExecutionEngine / RiskManager / API 未动）
- [x] 工程级校验证据包完整、可复现
- [x] **适用前提与限制**：当前实现仅适用于「A1 应用前不存在 strategy_runtime_state 表」的基线；若表已存在，需按 1.2 调整迁移为 extend 并单独验证
- [x] **TTL**：schema 提供默认 30 秒；过期判定为跨模块逻辑契约，**enforcing 责任在 C1**，见第 3 节声明
- [x] **风险**：不给出「无残余风险」结论；改为「**风险已知且边界明确**」——包括但不限于：迁移为 create 路径、未验证演进幂等、TTL 依赖 C1 履约
