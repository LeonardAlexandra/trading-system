# Phase 2.x 技术债强绑定审计包

**审计日期**: 2026-02-25
**审计范围**: Phase 2.0, 2.1, 2.2
**审计目标**: 验证技术债已锁定至具体阶段，并建立自动化门禁校验机制。

---

# 第一部分：tech_debt_registry.yaml 完整展开

```yaml
# Tech Debt and Gate Registry
# All entries must be status: DONE before sealing the deadline_phase.
# If current Phase == deadline_phase and status != DONE, sealing MUST fail.
# GATE- items must be DONE regardless of the phase.

- id: AC-运行模型-01
  description: 多实例下同一 rule_id 在冷却窗口内只触发一次（全局去重）
  category: PERFORMANCE
  status: TODO
  target_phase: "2.1"
  target_module: "C5 附"
  deadline_phase: "2.1"
  solution_plan: "使用 Redis 或 DB 实现分布式冷却计数器"
  acceptance: "多实例并发触发同一规则，仅产生一条告警"
  evidence_required: "并发压力测试报告 + 审计日志"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-运行模型-02
  description: 进程重启后冷却状态不丢失
  category: STABILITY
  status: TODO
  target_phase: "2.1"
  target_module: "C5 附"
  deadline_phase: "2.1"
  solution_plan: "冷却状态持久化至数据库"
  acceptance: "重启服务后，处于冷却期的规则不会立即触发"
  evidence_required: "重启演练测试用例"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-运行模型-03
  description: evaluate_rules 能按固定周期自动触发
  category: PERFORMANCE
  status: TODO
  target_phase: "2.1"
  target_module: "C5 附"
  deadline_phase: "2.1"
  solution_plan: "引入内部 Scheduler 或外部 K8s CronJob"
  acceptance: "日志显示 evaluate_rules 每分钟稳定调用"
  evidence_required: "调度运行日志"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-PERF-ISOLATION-01
  description: perf 记录写入失败时，不得导致 webhook/执行链路失败
  category: PERFORMANCE
  status: TODO
  target_phase: "2.1"
  target_module: "C5 附"
  deadline_phase: "2.1"
  solution_plan: "使用异步任务队列或 Try-Except 隔离"
  acceptance: "故障注入导致 Perf 写入失败，订单依然成交"
  evidence_required: "故障注入测试报告"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-PERF-ISOLATION-02
  description: 多实例运行时 perf 采集仍可用且不会重复/丢失关键记录
  category: PERFORMANCE
  status: TODO
  target_phase: "2.1"
  target_module: "C5 附"
  deadline_phase: "2.1"
  solution_plan: "分布式 ID 与幂等写入"
  acceptance: "多实例下统计的总笔数与 Trade 表对齐"
  evidence_required: "数据对齐校验报告"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-AUDIT-LISTTRACES-PERF-01
  description: list_traces 不得出现 N+1 查询模式
  category: PERFORMANCE
  status: TODO
  target_phase: "2.1"
  target_module: "C5 附"
  deadline_phase: "2.1"
  solution_plan: "使用 SQLAlchemy joinedload 或批量 IN 查询"
  acceptance: "单次请求产生的 SQL 语句数量固定，不随数据量增加"
  evidence_required: "SQL 审计日志"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-AUDIT-LISTTRACES-PERF-02
  description: 提供 E2E 证据包证明查询次数为常数级（<=K）
  category: PERFORMANCE
  status: TODO
  target_phase: "2.1"
  target_module: "C5 附"
  deadline_phase: "2.1"
  solution_plan: "编写专项性能回归测试"
  acceptance: "100 条数据查询 SQL 次数 <= 5"
  evidence_required: "E2E 性能测试报告"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-AUDIT-WEB-XSS-01
  description: /audit 页面渲染必须对可变字符串字段做安全输出（转义/escape）
  category: SECURITY
  status: TODO
  target_phase: "2.0"
  target_module: "C5 附"
  deadline_phase: "2.0"
  solution_plan: "使用 Jinja2 自动转义或前端框架安全渲染"
  acceptance: "源码中无未转义的原始 HTML 拼接"
  evidence_required: "代码审计报告"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-AUDIT-WEB-XSS-02
  description: 提供最小验证证据，注入 XSS payload 不得执行
  category: SECURITY
  status: TODO
  target_phase: "2.0"
  target_module: "C5 附"
  deadline_phase: "2.0"
  solution_plan: "构造 XSS 攻击向量进行渗透测试"
  acceptance: "浏览器控制台无脚本执行，页面仅显示转义字符"
  evidence_required: "XSS 渗透测试截图"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-C9-STRESS-DB-01
  description: 压力测试须在与生产等价的数据库上可复现
  category: STABILITY
  status: TODO
  target_phase: "2.2"
  target_module: "C5 附"
  deadline_phase: "2.2"
  solution_plan: "搭建与生产配置一致的 PG 测试集群"
  acceptance: "压测报告标注环境为 Production-Equivalent"
  evidence_required: "压测环境配置说明"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-C9-FAILURE-DRILL-01
  description: 「执行端不可用」故障恢复演练须可复现、可自动化
  category: STABILITY
  status: TODO
  target_phase: "2.2"
  target_module: "C5 附"
  deadline_phase: "2.2"
  solution_plan: "编写混沌工程脚本模拟网络中断"
  acceptance: "系统在执行端恢复后 30s 内自动重连并同步状态"
  evidence_required: "故障演练视频/日志记录"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-C9-BACKUP-VERIFY-01
  description: 备份与恢复演练的恢复后校验须 schema-aware
  category: STABILITY
  status: TODO
  target_phase: "2.2"
  target_module: "C5 附"
  deadline_phase: "2.2"
  solution_plan: "开发数据完整性校验工具"
  acceptance: "恢复后 Trade 表哈希值与备份前一致"
  evidence_required: "备份校验工具运行报告"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-D2-TRACE-404-01
  description: 执行失败的 decision 必须可通过 trace 接口查询到且明确失败原因
  category: SECURITY
  status: TODO
  target_phase: "2.0"
  target_module: "C5 附"
  deadline_phase: "2.0"
  solution_plan: "修正 Trace 逻辑，对 FAILED 状态提供原因聚合"
  acceptance: "API 返回 clear_failure_reason 而非 404"
  evidence_required: "API 响应样本"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: AC-D2-HEALTH-OBSERVABILITY-01
  description: 定义明确的 health 异常字段与判定标准
  category: OBSERVABILITY
  status: TODO
  target_phase: "2.0"
  target_module: "C5 附"
  deadline_phase: "2.0"
  solution_plan: "实现结构化健康检查 API"
  acceptance: "Health 接口返回具体的组件错误码与阈值状态"
  evidence_required: "健康检查接口文档"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: GATE-TD-01
  description: TD-C7-02 状态必须为 DONE
  category: OBSERVABILITY
  status: TODO
  target_phase: "2.0"
  target_module: "C5 附"
  deadline_phase: "2.0"
  solution_plan: "关联技术债 TD-C7-02 完成验收"
  acceptance: "TD-C7-02 在主技术债表中标记为 DONE"
  evidence_required: "主表截图"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: GATE-TD-02
  description: TD-C8-01 状态必须为 DONE
  category: PERFORMANCE
  status: TODO
  target_phase: "2.1"
  target_module: "C5 附"
  deadline_phase: "2.1"
  solution_plan: "关联技术债 TD-C8-01 完成验收"
  acceptance: "TD-C8-01 在主技术债表中标记为 DONE"
  evidence_required: "主表截图"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: GATE-TD-03
  description: /audit 页面对外使用且 TD-C8-02 != DONE，则 Phase2.0 不可封版
  category: SECURITY
  status: TODO
  target_phase: "2.0"
  target_module: "C5 附"
  deadline_phase: "2.0"
  solution_plan: "完成 XSS 修复并封锁审计页外部访问"
  acceptance: "外部扫描无法触发 XSS"
  evidence_required: "扫描报告"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: GATE-TD-04
  description: D2-TRACE-404 != DONE，则 Phase2.0 不可封版
  category: SECURITY
  status: TODO
  target_phase: "2.0"
  target_module: "C5 附"
  deadline_phase: "2.0"
  solution_plan: "完成 Trace 404 修复逻辑"
  acceptance: "失败订单可追溯"
  evidence_required: "追溯日志"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"

- id: GATE-TD-05
  description: D2-HEALTH-WEAK-OBSERVABILITY != DONE，则 Phase2.0 不可封版
  category: OBSERVABILITY
  status: TODO
  target_phase: "2.0"
  target_module: "C5 附"
  deadline_phase: "2.0"
  solution_plan: "完成健康检查可观测性升级"
  acceptance: "具备强门禁能力的健康接口"
  evidence_required: "接口测试报告"
  evidence_refs: []
  owner: TBD
  last_updated: "2026-02-25"
```

---

# 第二部分：三份交付包中的“技术债绑定清单”章节全文

## Phase 2.0 模块化开发交付包 - 封版 Gate 与技术债绑定清单

#### 封版 Gate（唯一门禁真源）

Phase2.x 封版门禁唯一真源为 `docs/tech_debt_registry.yaml`。
封版前必须运行 `scripts/check_tech_debt_gates.py --current-phase X`。

校验逻辑：
1. 若条目 ID 以 `GATE-` 开头且状态不为 `DONE`，则任何阶段均不可封版。
2. 若条目的 `deadline_phase` 等于当前阶段且状态不为 `DONE`，则当前阶段不可封版。

---

## 技术债完成时点声明

根据 `docs/tech_debt_registry.yaml` 定义，所有技术债已锁定明确的 `deadline_phase`：

- 所有 `deadline_phase=2.0` 的技术债（含 SECURITY 与 OBSERVABILITY 核心条目）**必须**在 Phase2.0 封版前完成状态转为 `DONE`。
- 不允许任何形式的延期至后续 Phase。
- 不允许擅自修改 `deadline_phase` 绑定关系。
- 若因极端特殊原因需变更时点，必须发起单独的技术评审会议，并在证据包中记录评审留痕。
- 若当前 Phase 等于条目的 `deadline_phase` 且状态仍为 `TODO` 或 `IN_PROGRESS`，系统门禁将拒绝封版。

---

## Phase 2.1 模块化开发交付包 - 技术债绑定清单（摘录自三、关键约束遵守检查清单）

### ✅ Phase 2.0 不被污染（B.6）
- [ ] Phase 2.1 **未**修改 evaluation_report、**未**写入 metrics_snapshot、**未**更改 Phase 2.0 的 schema 或指标口径；仅追加 param_version、release_audit、learning_audit、发布状态等 Phase 2.1 自有数据。

---

## Phase 2.2 模块化开发交付包 - 技术债绑定清单（摘录自三、关键约束遵守检查清单）

### ✅ Phase 2.2 终止条件与禁止进入后续/对外展示
- [ ] **视为完成**：A.2 全部达成且 F 节端到端用例（E2E-BI、E2E-BI-只读、E2E-BI-一致性、E2E-BI-决策过程与缺失）通过。
- [ ] **禁止进入后续 Phase 或对外正式展示**的情形（任一条即禁止）：BI 展示数据与 2.0/2.1 不一致；BI 能触发系统状态变化；BI 自行计算或推断交易/学习结论；BI 绕过既有 API 直连原始表做私有计算；决策过程展示在 BI 层生成「新解释」或「应该怎么做」；PARTIAL/NOT_FOUND 未清晰展示缺失原因；敏感字段未脱敏或权限模型未按约定生效（见蓝本 A.3、F.3）。

---

# 第三部分：门禁脚本全文

```python
#!/usr/bin/env python3
import sys
import yaml
from pathlib import Path

import argparse

def check_tech_debt_gates(registry_path: str, current_phase: str):
    path = Path(registry_path)
    if not path.exists():
        print(f"Error: Registry file not found at {registry_path}")
        sys.exit(1)

    with open(path, 'r', encoding='utf-8') as f:
        try:
            items = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"Error parsing YAML: {e}")
            sys.exit(1)

    if not items or not isinstance(items, list):
        print("Error: Registry is empty or not a list")
        sys.exit(1)

    failed_items = []
    
    for item in items:
        item_id = item.get('id', 'Unknown')
        status = item.get('status', 'TODO')
        deadline_phase = str(item.get('deadline_phase', ''))

        # Rule 1: GATE- entries must be DONE (regardless of phase)
        if item_id.startswith('GATE-') and status != 'DONE':
            failed_items.append({
                'id': item_id,
                'status': status,
                'deadline_phase': deadline_phase,
                'reason': 'Gate must be DONE'
            })
            continue

        # Rule 2: deadline_phase == current_phase entries must be DONE
        if deadline_phase == current_phase and status != 'DONE':
            failed_items.append({
                'id': item_id,
                'status': status,
                'deadline_phase': deadline_phase,
                'reason': f'Deadline reached for Phase {current_phase}'
            })

    if failed_items:
        print(f"FAIL: The following blocking tech debt items or gates are NOT DONE (Current Phase: {current_phase}):")
        for fail in failed_items:
            print(f"  - ID: {fail['id']}, Status: {fail['status']}, Deadline: {fail['deadline_phase']}, Reason: {fail['reason']}")
        sys.exit(1)
    else:
        print(f"PASS: All blocking gates and Phase {current_phase} tech debts are DONE.")
        sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check tech debt gates for a specific phase.")
    parser.add_argument("--registry", default="docs/tech_debt_registry.yaml", help="Path to the registry YAML file.")
    parser.add_argument("--current-phase", required=True, help="The current phase to check against (e.g., 2.0).")
    
    args = parser.parse_args()
    check_tech_debt_gates(args.registry, args.current_phase)
```

---

# 第四部分：单测全文

```python
import os
import subprocess
import tempfile
import yaml
import pytest

def run_check_script(yaml_content: str, current_phase: str = "2.0"):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
        tmp.write(yaml_content)
        tmp_path = tmp.name

    try:
        cmd = [
            "python3", "-c",
            f"from scripts.check_tech_debt_gates import check_tech_debt_gates; check_tech_debt_gates('{tmp_path}', '{current_phase}')"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def test_check_gates_fails_on_gate_todo():
    content = """
- id: GATE-TEST
  status: TODO
  deadline_phase: 2.1
"""
    code, stdout = run_check_script(content, "2.0")
    assert code != 0
    assert "FAIL" in stdout
    assert "GATE-TEST" in stdout
    assert "Gate must be DONE" in stdout

def test_check_gates_fails_on_current_phase_todo():
    content = """
- id: AC-TEST
  status: TODO
  deadline_phase: 2.0
"""
    code, stdout = run_check_script(content, "2.0")
    assert code != 0
    assert "FAIL" in stdout
    assert "AC-TEST" in stdout
    assert "Deadline reached for Phase 2.0" in stdout

def test_check_gates_passes_on_future_phase_todo():
    content = """
- id: AC-FUTURE
  status: TODO
  deadline_phase: 2.1
"""
    code, stdout = run_check_script(content, "2.0")
    assert code == 0
    assert "PASS" in stdout

def test_check_gates_passes_on_done():
    content = """
- id: GATE-DONE
  status: DONE
  deadline_phase: 2.0
- id: AC-DONE
  status: DONE
  deadline_phase: 2.0
"""
    code, stdout = run_check_script(content, "2.0")
    assert code == 0
    assert "PASS" in stdout

def test_check_gates_fails_on_gate_even_if_future_phase():
    content = """
- id: GATE-FUTURE
  status: TODO
  deadline_phase: 2.2
"""
    code, stdout = run_check_script(content, "2.0")
    assert code != 0
    assert "FAIL" in stdout
    assert "GATE-FUTURE" in stdout
```

---

# 第五部分：真实运行原始输出

### 1) python scripts/check_tech_debt_gates.py --current-phase 2.0 的完整原始输出

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

### 2) python scripts/check_tech_debt_gates.py --current-phase 2.1 的完整原始输出

```text
FAIL: The following blocking tech debt items or gates are NOT DONE (Current Phase: 2.1):
  - ID: AC-运行模型-01, Status: TODO, Deadline: 2.1, Reason: Deadline reached for Phase 2.1
  - ID: AC-运行模型-02, Status: TODO, Deadline: 2.1, Reason: Deadline reached for Phase 2.1
  - ID: AC-运行模型-03, Status: TODO, Deadline: 2.1, Reason: Deadline reached for Phase 2.1
  - ID: AC-PERF-ISOLATION-01, Status: TODO, Deadline: 2.1, Reason: Deadline reached for Phase 2.1
  - ID: AC-PERF-ISOLATION-02, Status: TODO, Deadline: 2.1, Reason: Deadline reached for Phase 2.1
  - ID: AC-AUDIT-LISTTRACES-PERF-01, Status: TODO, Deadline: 2.1, Reason: Deadline reached for Phase 2.1
  - ID: AC-AUDIT-LISTTRACES-PERF-02, Status: TODO, Deadline: 2.1, Reason: Deadline reached for Phase 2.1
  - ID: GATE-TD-01, Status: TODO, Deadline: 2.0, Reason: Gate must be DONE
  - ID: GATE-TD-02, Status: TODO, Deadline: 2.1, Reason: Gate must be DONE
  - ID: GATE-TD-03, Status: TODO, Deadline: 2.0, Reason: Gate must be DONE
  - ID: GATE-TD-04, Status: TODO, Deadline: 2.0, Reason: Gate must be DONE
  - ID: GATE-TD-05, Status: TODO, Deadline: 2.0, Reason: Gate must be DONE
```

### 3) pytest tests/unit/test_check_tech_debt_gates.py 的完整原始输出

```text
================================= test session starts ==================================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0 -- /Users/zhangkuo/TradingView Indicator/trading_system/.venv/bin/python3.11
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collected 5 items                                                                      

tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_gate_todo PASSED [ 20%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_current_phase_todo PASSED [ 40%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_passes_on_future_phase_todo PASSED [ 60%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_passes_on_done PASSED [ 80%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_gate_even_if_future_phase PASSED [100%]

================================== 5 passed in 0.28s ===================================
```
