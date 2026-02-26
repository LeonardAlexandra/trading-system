#!/usr/bin/env python3
import sys
import yaml
import hashlib
from pathlib import Path
import argparse

def get_file_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def check_tech_debt_gates(registry_path: str, current_phase: str):
    path = Path(registry_path)
    if not path.exists():
        print(f"Error: Registry file not found at {registry_path}")
        sys.exit(1)

    # 真源强校验
    real_path = path.resolve()
    file_sha256 = get_file_sha256(path)
    print(f"--- Registry Source Verification ---")
    print(f"RealPath: {real_path}")
    print(f"SHA256:   {file_sha256}")
    print(f"------------------------------------\n")

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

        reasons = []

        # Rule a): GATE-* → status != DONE → FAIL 且 DONE 时 evidence_refs 不得为空
        if item_id.startswith('GATE-'):
            if status != 'DONE':
                reasons.append("GATE status must be DONE")
            elif not evidence_refs:
                reasons.append("GATE must have evidence if DONE")
            
            if reasons:
                failed_items.append({
                    'id': item_id,
                    'target_module': target_module,
                    'status': status,
                    'evidence_refs': evidence_refs,
                    'reasons': reasons
                })
            continue

        # Rule b): target_phase == current_phase: status != DONE → FAIL, evidence_refs 为空 → FAIL
        if target_phase == current_phase:
            if status != 'DONE':
                reasons.append(f"Phase {current_phase} item status must be DONE")
            elif not evidence_refs:
                reasons.append(f"Phase {current_phase} item must have evidence if DONE")
            
            if reasons:
                failed_items.append({
                    'id': item_id,
                    'target_module': target_module,
                    'status': status,
                    'evidence_refs': evidence_refs,
                    'reasons': reasons
                })

    if failed_items:
        print(f"FAIL: The following blocking tech debt items or gates are NOT DONE (Current Phase: {current_phase}):")
        for fail in failed_items:
            print(f"  - ID: {fail['id']}")
            print(f"    Module: {fail['target_module']}")
            print(f"    Status: {fail['status']}")
            print(f"    Evidence: {fail['evidence_refs']}")
            print(f"    Reason: {', '.join(fail['reasons'])}")
        sys.exit(1)
    else:
        print(f"PASS: All blocking gates and Phase {current_phase} tech debts are DONE with evidence.")
        sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check tech debt gates for a specific phase.")
    parser.add_argument("--registry", required=True, help="Path to the registry YAML file.")
    parser.add_argument("--current-phase", required=True, help="The current phase to check against (e.g., 2.0).")
    
    args = parser.parse_args()
    check_tech_debt_gates(args.registry, args.current_phase)
