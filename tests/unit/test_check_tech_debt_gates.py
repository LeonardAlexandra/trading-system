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
            "python3", "scripts/check_tech_debt_gates.py", 
            "--registry", tmp_path, 
            "--current-phase", current_phase
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def test_check_gates_fails_on_gate_todo():
    # GATE-* → status != DONE → FAIL
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
    assert "GATE status must be DONE" in stdout

def test_check_gates_fails_on_gate_done_but_no_evidence():
    # GATE DONE 时 evidence_refs 不得为空
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
    assert "GATE must have evidence if DONE" in stdout

def test_check_gates_fails_on_current_phase_todo():
    # target_phase == current_phase: status != DONE → FAIL
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
    assert "Phase 2.0 item status must be DONE" in stdout

def test_check_gates_fails_on_current_phase_done_but_no_evidence():
    # target_phase == current_phase: evidence_refs 为空 → FAIL
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
    assert "Phase 2.0 item must have evidence if DONE" in stdout

def test_check_gates_passes_on_done_with_evidence():
    # DONE + evidence_refs 非空 → PASS
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

def test_check_gates_passes_on_future_phase_todo():
    # target_phase != current_phase → PASS
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

def test_check_gates_fails_on_gate_even_if_future_phase():
    # GATE 必须 DONE，无论 phase
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
    assert "GATE status must be DONE" in stdout

def test_check_gates_fails_on_no_registry_arg():
    # 未传 --registry 必须失败（退出码非0）
    try:
        cmd = ["python3", "scripts/check_tech_debt_gates.py", "--current-phase", "2.0"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0
        assert "the following arguments are required: --registry" in result.stderr
    except Exception as e:
        pytest.fail(f"Subprocess call failed: {e}")

def test_check_gates_passes_if_no_gates_in_registry():
    # GATE 条目不存在时脚本仍可正常工作
    content = """
- id: TD-ONLY
  status: DONE
  target_phase: 2.0
  target_module: Phase2.0:D6
  evidence_refs: ["proof.md"]
"""
    code, stdout = run_check_script(content, "2.0")
    assert code == 0
    assert "PASS" in stdout

def test_check_gates_mixed_scenarios():
    # 混合场景（部分 PASS 部分 FAIL）
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
