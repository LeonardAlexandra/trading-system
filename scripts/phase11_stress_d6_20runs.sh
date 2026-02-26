#!/usr/bin/env bash
# 封版补强 C：D6 并发/互斥测试连续运行 20 次，验证无 flaky。
# 用法：在项目根 trading_system 下执行：bash scripts/phase11_stress_d6_20runs.sh
set -e
cd "$(dirname "$0")/.." || exit 1
passed=0
failed=0
for i in $(seq 1 20); do
  out=$(python -m pytest tests/integration/test_d6_reconcile_vs_order_mutex.py -q --tb=no 2>&1)
  if echo "$out" | grep -q "passed"; then
    passed=$((passed+1))
    echo "Run $i: PASS"
  else
    failed=$((failed+1))
    echo "Run $i: FAIL"
    echo "$out"
  fi
done
echo "=== Total: $passed passed, $failed failed ==="
exit $failed
