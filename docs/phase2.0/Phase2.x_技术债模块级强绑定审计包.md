# Phase 2.x 技术债模块级强绑定审计包 (最终版)

**审计日期**: 2026-02-25
**审计范围**: Phase 2.0, 2.1, 2.2
**审计目标**: 结构完全对齐、补齐闭环、强化 TD ↔ AC 显式映射、升级门禁输出、补齐单测覆盖。

---

# 第一部分：技术债注册中心 (tech_debt_registry.yaml)

本文件是系统封版的**唯一真源**。新增 `ac_mapping` 字段以实现 TD 与交付包 AC 的显式强绑定。

```yaml
# Tech Debt and Gate Registry
# All entries must be status: DONE before sealing the target_phase.
# If current Phase == target_phase and status != DONE, sealing MUST fail.
# If status == DONE, evidence_refs MUST NOT be empty.
# GATE- items must be DONE regardless of the phase.

- id: TD-RUN-MODEL-01
  title: "分布式告警冷却去重"
  category: PERFORMANCE
  target_phase: "2.1"
  target_module: "Phase2.1:D7-TECHDEBT-ALARM"
  ac_mapping:
    module_ac_id: AC-RUN-MODEL-01
    module_section: "Phase2.1:D7"
  solution_plan:
    - step: "引入 Redis 作为分布式锁与计数器事实源"
      files_or_components: ["src/services/alarm_service.py"]
      change_type: "modify"
      risk_notes: "需处理 Redis 连接失败降级回进程内去重的策略"
  acceptance:
    - ac_id: AC-RUN-MODEL-01
      verify_by: integration_test
      command: "pytest tests/integration/test_alarm_deduplication.py -v"
      expected: "test_multi_instance_deduplication PASSED"
  evidence_required: ["修改文件清单", "测试文件", "测试命令", "原始输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: TD-RUN-MODEL-02
  title: "告警冷却状态持久化"
  category: STABILITY
  target_phase: "2.1"
  target_module: "Phase2.1:D7-TECHDEBT-ALARM"
  ac_mapping:
    module_ac_id: AC-RUN-MODEL-02
    module_section: "Phase2.1:D7"
  solution_plan:
    - step: "将冷却窗口结束时间戳持久化至 DB"
      files_or_components: ["src/repositories/alarm_repository.py"]
      change_type: "add"
      risk_notes: "需注意 DB 写入延迟对高频告警去重的影响"
  acceptance:
    - ac_id: AC-RUN-MODEL-02
      verify_by: unit_test
      command: "pytest tests/unit/test_alarm_persistence.py -v"
      expected: "test_state_not_lost_after_restart PASSED"
  evidence_required: ["修改文件清单", "测试命令", "原始输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: TD-RUN-MODEL-03
  title: "自动化规则评估触发"
  category: PERFORMANCE
  target_phase: "2.1"
  target_module: "Phase2.1:D7-TECHDEBT-ALARM"
  ac_mapping:
    module_ac_id: AC-RUN-MODEL-03
    module_section: "Phase2.1:D7"
  solution_plan:
    - step: "集成 APScheduler 模块在 execution worker 中运行"
      files_or_components: ["src/worker/scheduler.py"]
      change_type: "add"
      risk_notes: "多实例下需防止调度冲突"
  acceptance:
    - ac_id: AC-RUN-MODEL-03
      verify_by: e2e
      command: "python3 scripts/verify_scheduler.py"
      expected: "Scheduler heartbeat detected"
  evidence_required: ["调度运行日志", "原始输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: TD-PERF-ISOLATION-01
  title: "Perf 写入故障隔离"
  category: PERFORMANCE
  target_phase: "2.1"
  target_module: "Phase2.1:D8-TECHDEBT-PERF"
  ac_mapping:
    module_ac_id: AC-PERF-ISOLATION-01
    module_section: "Phase2.1:D8"
  solution_plan:
    - step: "使用异步任务队列隔离 Perf 写入"
      files_or_components: ["src/services/perf_service.py"]
      change_type: "modify"
      risk_notes: "需确保异步失败后仍有审计日志"
  acceptance:
    - ac_id: AC-PERF-ISOLATION-01
      verify_by: integration_test
      command: "pytest tests/integration/test_perf_isolation.py -v"
      expected: "test_webhook_success_on_perf_failure PASSED"
  evidence_required: ["故障注入测试报告", "原始输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: TD-AUDIT-XSS-01
  title: "审计页面 XSS 修复"
  category: SECURITY
  target_phase: "2.0"
  target_module: "Phase2.0:D6-TECHDEBT-SECURITY"
  ac_mapping:
    module_ac_id: AC-AUDIT-WEB-XSS-01
    module_section: "Phase2.0:D6"
  solution_plan:
    - step: "在后端渲染模板中启用全局转义"
      files_or_components: ["src/web/templates/audit.html"]
      change_type: "modify"
      risk_notes: "无"
  acceptance:
    - ac_id: AC-AUDIT-WEB-XSS-01
      verify_by: unit_test
      command: "pytest tests/unit/test_security_rendering.py -v"
      expected: "test_xss_payload_escaped PASSED"
  evidence_required: ["代码审计报告", "原始输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: TD-TRACE-404-01
  title: "失败决策可追溯化"
  category: SECURITY
  target_phase: "2.0"
  target_module: "Phase2.0:D7-TECHDEBT-TRACE"
  ac_mapping:
    module_ac_id: AC-D2-TRACE-404-01
    module_section: "Phase2.0:D7"
  solution_plan:
    - step: "修改 Trace API 聚合 FAILED 状态的 decision_snapshot"
      files_or_components: ["src/services/trace_service.py"]
      change_type: "modify"
      risk_notes: "需处理快照缺失场景"
  acceptance:
    - ac_id: AC-D2-TRACE-404-01
      verify_by: integration_test
      command: "pytest tests/integration/test_failed_trace.py -v"
      expected: "test_get_trace_for_failed_decision PASSED"
  evidence_required: ["API 响应样本", "原始输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: TD-HEALTH-OBS-01
  title: "健康检查可观测性升级"
  category: OBSERVABILITY
  target_phase: "2.0"
  target_module: "Phase2.0:D8-TECHDEBT-HEALTH"
  ac_mapping:
    module_ac_id: AC-D2-HEALTH-OBS-01
    module_section: "Phase2.0:D8"
  solution_plan:
    - step: "实现 Prometheus 规范的 Health 暴露接口"
      files_or_components: ["src/web/api/health.py"]
      change_type: "add"
      risk_notes: "无"
  acceptance:
    - ac_id: AC-D2-HEALTH-OBS-01
      verify_by: unit_test
      command: "pytest tests/unit/test_health_check.py -v"
      expected: "test_health_metrics_format PASSED"
  evidence_required: ["接口测试报告", "原始输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: TD-STRESS-DB-01
  title: "生产等价压测环境搭建"
  category: STABILITY
  target_phase: "2.2"
  target_module: "Phase2.2:D3-TECHDEBT-STABILITY"
  ac_mapping:
    module_ac_id: AC-C9-STRESS-DB-01
    module_section: "Phase2.2:D3"
  solution_plan:
    - step: "在独立隔离环境搭建与生产配置一致的 PG 集群"
      files_or_components: ["infra/docker-compose.stress.yaml"]
      change_type: "add"
      risk_notes: "压测环境必须与生产网络物理隔离"
  acceptance:
    - ac_id: AC-C9-STRESS-DB-01
      verify_by: integration_test
      command: "python3 scripts/run_stress_test.py --env stress"
      expected: "Stress test completed on production-equivalent DB"
  evidence_required: ["压测报告", "环境说明"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: TD-FAILURE-DRILL-01
  title: "自动化故障恢复演练"
  category: STABILITY
  target_phase: "2.2"
  target_module: "Phase2.2:D3-TECHDEBT-STABILITY"
  ac_mapping:
    module_ac_id: AC-C9-FAILURE-DRILL-01
    module_section: "Phase2.2:D3"
  solution_plan:
    - step: "编写 Chaos 脚本模拟执行端中断并验证自动恢复"
      files_or_components: ["scripts/failure_drill.py"]
      change_type: "add"
      risk_notes: "需确保演练不影响正常流水"
  acceptance:
    - ac_id: AC-C9-FAILURE-DRILL-01
      verify_by: e2e
      command: "python3 scripts/failure_drill.py --verify"
      expected: "Recovery verification PASSED"
  evidence_required: ["演练日志", "原始输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: TD-BACKUP-VERIFY-01
  title: "Schema-aware 备份校验"
  category: STABILITY
  target_phase: "2.2"
  target_module: "Phase2.2:D3-TECHDEBT-STABILITY"
  ac_mapping:
    module_ac_id: AC-C9-BACKUP-VERIFY-01
    module_section: "Phase2.2:D3"
  solution_plan:
    - step: "开发备份自动恢复与 Schema 完整性比对工具"
      files_or_components: ["scripts/verify_backup.py"]
      change_type: "add"
      risk_notes: "无"
  acceptance:
    - ac_id: AC-C9-BACKUP-VERIFY-01
      verify_by: unit_test
      command: "python3 scripts/verify_backup.py --test"
      expected: "Backup integrity check PASSED"
  evidence_required: ["备份校验报告", "原始输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"

- id: GATE-TD-01
  title: "封版门禁：TD-AUDIT-XSS-01 完成度"
  category: SECURITY
  target_phase: "2.0"
  target_module: "Phase2.0:D6-TECHDEBT-SECURITY"
  ac_mapping:
    module_ac_id: GATE-AC-01
    module_section: "Phase2.0:D6"
  solution_plan:
    - step: "检查 registry 中 TD-AUDIT-XSS-01 状态"
      files_or_components: []
      change_type: "modify"
      risk_notes: "无"
  acceptance:
    - ac_id: GATE-AC-01
      verify_by: e2e
      command: "python3 scripts/check_tech_debt_gates.py --current-phase 2.0"
      expected: "PASS"
  evidence_required: ["脚本输出"]
  evidence_refs: []
  status: TODO
  owner: TBD
  last_updated: "2026-02-25"
```

---

# 第二部分：模块完整结构定义 (Expanded Modules)

## 2.1 Phase 2.0 模块定义

#### D6. 技术债专项修复：SECURITY（Phase2.0:D6）

**目标**  
- 修复 /audit 页面 XSS 风险；确保所有可变字符串输出均经过安全转义。

**Strong Constraints（强制约束）**  
- **不得污染**：修复代码仅限于渲染层，禁止修改核心业务逻辑或数据库结构。  
- **安全第一**：必须使用成熟的转义库或框架内置安全机制。  
- **只读一致性**：修复过程不得对数据库执行任何写操作。

**验收口径 (AC)**  
- [ ] AC-AUDIT-WEB-XSS-01: /audit 页面渲染对所有可变字段进行转义。

**证据包要求**  
- 修改文件清单、测试命令、原始输出、代码审计报告。

**不得污染声明**  
- 本模块仅修改模板渲染逻辑，不触及 Phase 1.2 核心交易路径与数据模型。

---

#### D7. 技术债专项修复：TRACE（Phase2.0:D7）

**目标**  
- 修复失败决策无法追溯的问题；确保 FAILED 状态的决策可通过 Trace 接口查询。

**Strong Constraints（强制约束）**  
- **只读边界**：Trace 逻辑必须保持只读，禁止在 Trace 过程中修改决策状态。  
- **原子性**：聚合结果必须包含失败节点的完整快照，不得有数据截断。

**验收口径 (AC)**  
- [ ] AC-D2-TRACE-404-01: Trace API 对失败决策返回聚合后的原因而非 404。

**证据包要求**  
- API 响应样本、原始输出、追溯日志。

**不得污染声明**  
- 本模块仅扩展查询聚合能力，不修改任何 Phase 1.2 的写入逻辑。

---

#### D8. 技术债专项修复：HEALTH（Phase2.0:D8）

**目标**  
- 升级健康检查可观测性；提供符合 Prometheus 规范的结构化指标。

**Strong Constraints（强制约束）**  
- **性能影响**：健康检查接口执行耗时必须 < 100ms，禁止在健康检查中执行重型查询。  
- **标准化**：输出格式必须符合 OpenMetrics 文本规范。

**验收口径 (AC)**  
- [ ] AC-D2-HEALTH-OBS-01: 健康接口返回具体的组件状态与阈值指标。

**证据包要求**  
- 接口测试报告、原始输出。

**不得污染声明**  
- 本模块为纯新增 API 接口，不改变系统现有运行逻辑。

---

## 2.2 Phase 2.1 模块定义

#### D7. 技术债专项修复：ALARM（Phase2.1:D7）

**目标**  
- 实现分布式告警冷却去重与状态持久化；解决进程重启丢失冷却状态的问题。

**Strong Constraints（强制约束）**  
- **一致性**：分布式锁必须保证在网络分区时不会产生双重告警。  
- **性能**：去重逻辑对主链路性能损耗必须 < 5ms。

**验收口径 (AC)**  
- [ ] AC-RUN-MODEL-01: 多实例并发触发同一规则，仅产生一条告警。  
- [ ] AC-RUN-MODEL-02: 进程重启后冷却状态不丢失。  
- [ ] AC-RUN-MODEL-03: evaluate_rules 按固定周期自动触发。

**证据包要求**  
- 并发压力测试报告、审计日志、重启演练记录。

**不得污染声明**  
- 本模块仅在告警网关层进行增强，不影响信号接收与执行决策的核心逻辑。

---

#### D8. 技术债专项修复：PERF（Phase2.1:D8）

**目标**  
- 实现 Perf 写入故障隔离与 list_traces 性能优化。

**Strong Constraints（强制约束）**  
- **解耦**：Perf 模块的任何异常不得向上抛出至 Webhook 处理器。  
- **高效查询**：list_traces 必须通过索引优化消除 N+1 查询。

**验收口径 (AC)**  
- [ ] AC-PERF-ISOLATION-01: Perf 写入失败不影响交易链路。
- [ ] AC-AUDIT-LISTTRACES-PERF-01: list_traces 消除 N+1 查询。

**证据包要求**  
- 故障注入测试报告、SQL 审计日志。

**不得污染声明**  
- 本模块仅涉及性能与隔离性增强，不改动业务数据的生命周期。

---

## 2.3 Phase 2.2 模块定义

#### D3. 技术债专项修复：STABILITY（Phase2.2:D3）

**目标**  
- 提升系统稳定性，确保压力测试、故障恢复及备份校验的自动化与可复现性。

**Strong Constraints（强制约束）**  
- **环境隔离**：压力测试必须在独立环境运行，禁止影响在线生产数据。  
- **数据安全**：备份校验过程不得泄露真实交易数据。

**验收口径 (AC)**  
- [ ] AC-C9-STRESS-DB-01: 压力测试在与生产等价的数据库上可复现。
- [ ] AC-C9-FAILURE-DRILL-01: 「执行端不可用」故障恢复演练可自动化。
- [ ] AC-C9-BACKUP-VERIFY-01: 备份与恢复演练的恢复后校验 schema-aware。

**证据包要求**  
- 压测报告、故障演练日志、备份校验报告。

**不得污染声明**  
- 本模块主要为外部脚本与工具链建设，不修改系统核心代码逻辑。

### 《技术债模块级绑定清单 (Phase2.2)》

| TD ID | target_module | acceptance.command | 证据包名称 |
|-------|---------------|-------------------|------------|
| TD-STRESS-DB-01 | Phase2.2:D3-TECHDEBT-STABILITY | `python3 scripts/run_stress_test.py --env stress` | Phase2.2_D3_证据包.md |
| TD-FAILURE-DRILL-01 | Phase2.2:D3-TECHDEBT-STABILITY | `python3 scripts/failure_drill.py --verify` | Phase2.2_D3_证据包.md |
| TD-BACKUP-VERIFY-01 | Phase2.2:D3-TECHDEBT-STABILITY | `python3 scripts/verify_backup.py --test` | Phase2.2_D3_证据包.md |

---

# 第三部分：门禁脚本源码 (check_tech_debt_gates.py)

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
        target_phase = str(item.get('target_phase', ''))
        target_module = item.get('target_module', '')
        evidence_refs = item.get('evidence_refs', [])

        # Rule 1: GATE- entries must be DONE (regardless of phase)
        if item_id.startswith('GATE-'):
            missing_fields = []
            if status != 'DONE':
                missing_fields.append('status must be DONE for GATE')
            if status == 'DONE' and not evidence_refs:
                missing_fields.append('evidence_refs must NOT be empty for DONE GATE')
            
            if missing_fields:
                failed_items.append({
                    'id': item_id,
                    'target_module': target_module,
                    'status': status,
                    'evidence_refs': evidence_refs,
                    'missing_fields': missing_fields
                })
            continue

        # Rule 2: target_phase == current_phase checks
        if target_phase == current_phase:
            missing_fields = []
            if status != 'DONE':
                missing_fields.append(f"status({status}) != DONE")
            if status == 'DONE' and not evidence_refs:
                missing_fields.append("evidence_refs is empty for DONE item")
            
            if missing_fields:
                failed_items.append({
                    'id': item_id,
                    'target_module': target_module,
                    'status': status,
                    'evidence_refs': evidence_refs,
                    'missing_fields': missing_fields
                })

    if failed_items:
        print(f"FAIL: The following blocking tech debt items or gates are NOT DONE (Current Phase: {current_phase}):")
        for fail in failed_items:
            print(f"  - ID: {fail['id']}")
            print(f"    Module: {fail['target_module']}")
            print(f"    Status: {fail['status']}")
            print(f"    Evidence: {fail['evidence_refs']}")
            print(f"    Reason: {', '.join(fail['missing_fields'])}")
        sys.exit(1)
    else:
        print(f"PASS: All blocking gates and Phase {current_phase} tech debts are DONE with evidence.")
        sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check tech debt gates for a specific phase.")
    parser.add_argument("--registry", default="docs/tech_debt_registry.yaml", help="Path to the registry YAML file.")
    parser.add_argument("--current-phase", required=True, help="The current phase to check against (e.g., 2.0).")
    
    args = parser.parse_args()
    check_tech_debt_gates(args.registry, args.current_phase)
```

---

# 第四部分：单元测试源码 (test_check_tech_debt_gates.py)

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
  target_phase: 2.1
  target_module: Phase2.1:D7
  evidence_refs: []
"""
    code, stdout = run_check_script(content, "2.0")
    assert code != 0
    assert "FAIL" in stdout
    assert "ID: GATE-TEST" in stdout
    assert "Reason: status must be DONE for GATE" in stdout

def test_check_gates_fails_on_current_phase_todo():
    content = """
- id: TD-TEST
  status: TODO
  target_phase: 2.0
  target_module: Phase2.0:D6
  evidence_refs: []
"""
    code, stdout = run_check_script(content, "2.0")
    assert code != 0
    assert "FAIL" in stdout
    assert "ID: TD-TEST" in stdout
    assert "Reason: status(TODO) != DONE" in stdout

def test_check_gates_fails_on_done_but_no_evidence():
    content = """
- id: TD-EVIDENCE
  status: DONE
  target_phase: 2.0
  target_module: Phase2.0:D6
  evidence_refs: []
"""
    code, stdout = run_check_script(content, "2.0")
    assert code != 0
    assert "FAIL" in stdout
    assert "ID: TD-EVIDENCE" in stdout
    assert "Reason: evidence_refs is empty for DONE item" in stdout

def test_check_gates_passes_on_future_phase_todo():
    content = """
- id: TD-FUTURE
  status: TODO
  target_phase: 2.1
  target_module: Phase2.1:D7
  evidence_refs: []
"""
    code, stdout = run_check_script(content, "2.0")
    assert code == 0
    assert "PASS" in stdout

def test_check_gates_passes_on_done_with_evidence():
    content = """
- id: TD-PASS
  status: DONE
  target_phase: 2.0
  target_module: Phase2.0:D6
  evidence_refs: ["docs/evidence.md"]
"""
    code, stdout = run_check_script(content, "2.0")
    assert code == 0
    assert "PASS" in stdout

def test_check_gates_fails_on_gate_even_if_future_phase():
    content = """
- id: GATE-FUTURE
  status: TODO
  target_phase: 2.2
  target_module: Phase2.2:D3
  evidence_refs: []
"""
    code, stdout = run_check_script(content, "2.0")
    assert code != 0
    assert "FAIL" in stdout
    assert "ID: GATE-FUTURE" in stdout

def test_check_gates_fails_on_gate_done_but_no_evidence():
    content = """
- id: GATE-EVIDENCE
  status: DONE
  target_phase: 2.1
  target_module: Phase2.1:D7
  evidence_refs: []
"""
    code, stdout = run_check_script(content, "2.0")
    assert code != 0
    assert "FAIL" in stdout
    assert "ID: GATE-EVIDENCE" in stdout
    assert "Reason: evidence_refs must NOT be empty for DONE GATE" in stdout

def test_check_gates_mixed_scenarios():
    content = """
- id: TD-OK
  status: DONE
  target_phase: 2.0
  target_module: Phase2.0:D6
  evidence_refs: ["proof.md"]
- id: TD-FAIL
  status: TODO
  target_phase: 2.0
  target_module: Phase2.0:D7
  evidence_refs: []
- id: GATE-OK
  status: DONE
  target_phase: 2.1
  target_module: Phase2.1:D7
  evidence_refs: ["gate_proof.md"]
- id: GATE-FAIL
  status: TODO
  target_phase: 2.2
  target_module: Phase2.2:D3
  evidence_refs: []
"""
    code, stdout = run_check_script(content, "2.0")
    assert code != 0
    assert "FAIL" in stdout
    assert "ID: TD-FAIL" in stdout
    assert "ID: GATE-FAIL" in stdout
    assert "ID: TD-OK" not in stdout
    assert "ID: GATE-OK" not in stdout
```

---

# 第五部分：门禁运行输出 (Gate Execution Logs)

### 5.1 Phase 2.0 运行输出
```text
FAIL: The following blocking tech debt items or gates are NOT DONE (Current Phase: 2.0):
  - ID: TD-AUDIT-XSS-01
    Module: Phase2.0:D6-TECHDEBT-SECURITY
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: TD-TRACE-404-01
    Module: Phase2.0:D7-TECHDEBT-TRACE
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: TD-HEALTH-OBS-01
    Module: Phase2.0:D8-TECHDEBT-HEALTH
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: GATE-TD-01
    Module: Phase2.0:D6-TECHDEBT-SECURITY
    Status: TODO
    Evidence: []
    Reason: status must be DONE for GATE
```

### 5.2 Phase 2.1 运行输出
```text
FAIL: The following blocking tech debt items or gates are NOT DONE (Current Phase: 2.1):
  - ID: TD-RUN-MODEL-01
    Module: Phase2.1:D7-TECHDEBT-ALARM
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: TD-RUN-MODEL-02
    Module: Phase2.1:D7-TECHDEBT-ALARM
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: TD-RUN-MODEL-03
    Module: Phase2.1:D7-TECHDEBT-ALARM
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: TD-PERF-ISOLATION-01
    Module: Phase2.1:D8-TECHDEBT-PERF
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: GATE-TD-01
    Module: Phase2.0:D6-TECHDEBT-SECURITY
    Status: TODO
    Evidence: []
    Reason: status must be DONE for GATE
```

### 5.3 Phase 2.2 运行输出
```text
FAIL: The following blocking tech debt items or gates are NOT DONE (Current Phase: 2.2):
  - ID: TD-STRESS-DB-01
    Module: Phase2.2:D3-TECHDEBT-STABILITY
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: TD-FAILURE-DRILL-01
    Module: Phase2.2:D3-TECHDEBT-STABILITY
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: TD-BACKUP-VERIFY-01
    Module: Phase2.2:D3-TECHDEBT-STABILITY
    Status: TODO
    Evidence: []
    Reason: status(TODO) != DONE
  - ID: GATE-TD-01
    Module: Phase2.0:D6-TECHDEBT-SECURITY
    Status: TODO
    Evidence: []
    Reason: status must be DONE for GATE
```

---

# 第六部分：单元测试运行输出 (Pytest Results)

```text
================================= test session starts ==================================
platform darwin -- Python 3.11.7, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
collected 8 items                                                                      

tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_gate_todo PASSED [ 12%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_current_phase_todo PASSED [ 25%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_done_but_no_evidence PASSED [ 37%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_passes_on_future_phase_todo PASSED [ 50%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_passes_on_done_with_evidence PASSED [ 62%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_gate_even_if_future_phase PASSED [ 75%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_fails_on_gate_done_but_no_evidence PASSED [ 87%]
tests/unit/test_check_tech_debt_gates.py::test_check_gates_mixed_scenarios PASSED [100%]

================================== 8 passed in 0.37s ===================================
```
