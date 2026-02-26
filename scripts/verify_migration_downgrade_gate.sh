#!/usr/bin/env bash
# PR11 封版：007 downgrade 门禁可审计化
# 验证“未设置 ALLOW_DATA_LOSS=true 时 downgrade 必须失败；设置后必须成功”。
# 可作为人工或 CI 前置检查脚本。需在项目根目录（trading_system）执行。

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "[1/4] 检查当前 revision 是否 >= 007 ..."
CURRENT="$("${PROJECT_ROOT}/.venv/bin/alembic" current 2>&1)" || true
if ! echo "$CURRENT" | grep -q "007"; then
  echo "  当前不在 007：$CURRENT"
  echo "  请先执行: .venv/bin/alembic upgrade 007"
  exit 1
fi
echo "  通过: 当前在 007"

echo "[2/4] 未设置 ALLOW_DATA_LOSS 时执行 downgrade -1，预期失败 ..."
unset ALLOW_DATA_LOSS
if "${PROJECT_ROOT}/.venv/bin/alembic" downgrade -1 2>&1; then
  echo "  失败: 未设置 ALLOW_DATA_LOSS 时 downgrade 应报错退出"
  exit 2
fi
echo "  通过: downgrade 已拒绝（无 ALLOW_DATA_LOSS）"

echo "[3/4] 设置 ALLOW_DATA_LOSS=true 后执行 downgrade -1，预期成功 ..."
export ALLOW_DATA_LOSS=true
if ! "${PROJECT_ROOT}/.venv/bin/alembic" downgrade -1; then
  echo "  失败: ALLOW_DATA_LOSS=true 时 downgrade 应成功"
  exit 3
fi
echo "  通过: downgrade 成功"

echo "[4/4] 恢复 007（便于后续测试）..."
"${PROJECT_ROOT}/.venv/bin/alembic" upgrade 007
echo "  通过: 已恢复 007"

echo ""
echo "verify_migration_downgrade_gate: 全部通过"
