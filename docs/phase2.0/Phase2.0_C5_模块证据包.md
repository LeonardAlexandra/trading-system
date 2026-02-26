# Phase 2.0 C5 模块证据包

**模块名称**: C5：历史数据假设与硬性待办（T2.0-5）  
**完成日期**: 2026-02-25  
**真理源**: `docs/plan/Phase2.0_模块化开发交付包.md`（全文版）

---

## 一、本模块涉及的变更文件清单

| 类型 | 路径 | 说明 |
|------|------|------|
| 修改 | `docs/Phase2.0_C5_模块证据包.md` | 本证据包文件（升级强门禁） |
| 新增 | `scripts/check_tech_debt_gates.py` | 自动化门禁校验脚本 |
| 新增 | `tests/unit/test_check_tech_debt_gates.py` | 门禁校验脚本单元测试 |
| 新增 | `docs/tech_debt_registry.yaml` | 系统化技术债与 Gate 注册表 |

---

## 二、本模块的核心实现内容（强门禁与口径修正）

### 1️⃣ 修正反证口径（Strong Constraints）

- **口径声明**: Phase 2.0 C5 **未新增/未修改**任何历史数据导入、调度、去重或 Perf Isolation 相关实现代码；本模块仅负责需求锁死、技术债门禁注册及自动化校验机制的建立。
- **既有资产说明**:
  - `scripts/c9_stress_test.py`: 属于 Phase 1.2 既有资产，用于压力测试。
  - **无修改证明**: 
    - `git diff scripts/c9_stress_test.py` 输出为空。
    - 文件 HASH (SHA-256): `8b383d00a17f847405d90588d75700b9378ea820e5c5ed92540f9567cc04f913`。

### 2️⃣ 历史数据假设（系统级口径）

- **责任方**: 历史数据由运营方导出，由开发者负责导入。
- **一致性要求**: 必须与实盘 Webhook 产出的 `trade` 表格式严格对齐。
- **Phase 2.0 边界声明**: 本 Phase **禁止**实现任何历史数据导入业务代码。

### 3️⃣ 门禁自动化（机器可执行强锁死）

已实现 `scripts/check_tech_debt_gates.py`，作为封版放行的**唯一自动化依据**。

- **校验规则**:
  - 所有 `id` 以 `GATE-` 开头的条目必须为 `DONE`。
  - 所有 `deadline_phase` 等于当前阶段（通过 `--current-phase` 指定）的条目必须为 `DONE`。
- **封版检查机制**:
  - 封版前必须运行 `python scripts/check_tech_debt_gates.py --current-phase 2.0`。
  - 若存在任何 `TODO` 或 `IN_PROGRESS` 阻塞项，脚本将以 ID、状态、截止阶段及失败原因等详细信息退出并拒绝封版。

---

## 三、原始输出全文（验证记录）

### 3.1 门禁校验脚本运行输出
**命令**: `python3 scripts/check_tech_debt_gates.py --current-phase 2.0`
```text
FAIL: The following blocking tech debt items or gates are NOT DONE (Current Phase: 2.0):
  - ID: AC-AUDIT-WEB-XSS-01, Status: TODO, Deadline: 2.0, Reason: Deadline reached for Phase 2.0
  - ID: AC-AUDIT-WEB-XSS-02, Status: TODO, Deadline: 2.0, Reason: Deadline reached for Phase 2.0
  - ID: AC-D2-TRACE-404-01, Status: TODO, Deadline: 2.0, Reason: Deadline reached for Phase 2.0
  - ID: AC-D2-HEALTH-OBSERVABILITY-01, Status: TODO, Deadline: 2.0, Reason: Deadline reached for Phase 2.0
  - ID: GATE-TD-01, Status: TODO, Deadline: 2.0, Reason: Gate must be DONE
  - ID: GATE-TD-02, Status: TODO, Deadline: 2.1, Reason: Gate must be DONE
  - ID: GATE-TD-03, Status: TODO, Deadline: 2.0, Reason: Gate must be DONE
  - ID: GATE-TD-04, Status: TODO, Deadline: 2.0, Reason: Gate must be DONE
  - ID: GATE-TD-05, Status: TODO, Deadline: 2.0, Reason: Gate must be DONE
```
*(注：当前返回 FAIL 符合预期，因为注册表中 Phase 2.0 的技术债尚未完成，证明了门禁的有效性)*

### 3.2 校验脚本单元测试输出
**命令**: `python3 -m pytest tests/unit/test_check_tech_debt_gates.py -v`
```text
tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_gate_todo PASSED [ 20%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_current_phase_todo PASSED [ 40%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_passes_on_future_phase_todo PASSED [ 60%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_passes_on_done PASSED [ 80%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_gate_even_if_future_phase PASSED [100%]

========================= 5 passed in 0.15s =========================
```

---

## 四、技术债完成时间锁死声明

根据 `docs/tech_debt_registry.yaml` 升级后的结构：

- **本模块不修复技术债**：C5 仅负责建立结构化管理机制。
- **锁死 deadline_phase**：所有已注册技术债已根据其性质（SECURITY/OBSERVABILITY/PERFORMANCE/STABILITY）强制绑定到具体的 Phase（2.0、2.1 或 2.2）。
- **禁止模糊性**：移除了所有“Phase2.x”等模糊表述，确保每一项技术债都有明确的终态交付时点。
- **不存在“无限延期”可能**：若在对应 Phase 封版时 `status` 未转为 `DONE`，门禁脚本将强制拦截封版流程。

---

## 五、验收口径对照 Checklist

- [x] **修正反证口径**: 已声明未新增/修改实现代码，并解释了既有资产。
- [x] **门禁自动化**: 已新增 `scripts/check_tech_debt_gates.py` 及其单测。
- [x] **强锁死机制**: 校验脚本严格执行 GATE- 和 2.x 阻塞逻辑。
- [x] **原始输出补齐**: 已包含脚本运行和 pytest 原始输出。
- [x] **不实现业务代码**: 仓库中无新增导入/调度等业务实现。

---

**证据包结束**
