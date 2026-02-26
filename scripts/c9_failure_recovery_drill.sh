#!/usr/bin/env bash
# C9 故障恢复演练：可复现步骤。
# 场景1：数据库短暂不可用
# 场景2：执行端不可用（通过停止 worker 模拟）
# 用法：在项目根 trading_system 下执行；需先有 DATABASE_URL、TV_WEBHOOK_SECRET 等环境。
set -e
cd "$(dirname "$0")/.." || exit 1
OUT_DIR="${C9_RUNLOGS:-docs/runlogs}"
mkdir -p "$OUT_DIR"
TS=$(date +%Y%m%d_%H%M%S)
LOG1="$OUT_DIR/c9_failure_drill_scenario1_$TS.log"
LOG2="$OUT_DIR/c9_failure_drill_scenario2_$TS.log"

echo "=== C9 故障恢复演练 ==="
echo "输出目录: $OUT_DIR"

# 场景1：数据库短暂不可用（SQLite：移动 DB 文件后恢复）
echo ""
echo "--- 场景1：数据库短暂不可用 ---"
DB_URL="${DATABASE_URL:-sqlite+aiosqlite:///./trading_system.db}"
if [[ "$DB_URL" == *"sqlite"* ]]; then
  DB_PATH="${DB_URL#*:///}"
  DB_PATH="${DB_PATH#*:}"
  if [[ -z "$DB_PATH" ]]; then
    DB_PATH="trading_system.db"
  fi
  if [[ -f "$DB_PATH" ]]; then
    BACKUP_PATH="${DB_PATH}.c9_drill_backup"
    echo "1. 备份 DB: cp $DB_PATH $BACKUP_PATH" | tee -a "$LOG1"
    cp "$DB_PATH" "$BACKUP_PATH"
    echo "2. 模拟不可用: mv $DB_PATH ${DB_PATH}.moved" | tee -a "$LOG1"
    mv "$DB_PATH" "${DB_PATH}.moved"
    echo "3. 此时若请求服务（需服务已启动），应得到连接/执行错误；健康接口可 503 或 500。" | tee -a "$LOG1"
    echo "4. 恢复: mv ${DB_PATH}.moved $DB_PATH" | tee -a "$LOG1"
    mv "${DB_PATH}.moved" "$DB_PATH"
    echo "5. 验证: 再次请求 /healthz 或 /api/health/summary 应恢复 200。" | tee -a "$LOG1"
    echo "场景1 完成（DB 已恢复）" | tee -a "$LOG1"
  else
    echo "DB 文件不存在，跳过场景1（可先 alembic upgrade head 创建）" | tee -a "$LOG1"
  fi
else
  echo "非 SQLite，请手动执行：停止 DB 服务 -> 观测错误 -> 恢复 DB 服务 -> 验证" | tee -a "$LOG1"
fi

# 场景2：执行端不可用（停止 worker 或模拟网络失败）
echo ""
echo "--- 场景2：执行端不可用（以停止 worker 模拟）---"
echo "步骤：" | tee -a "$LOG2"
echo "1. 若 execution worker 作为独立进程运行：kill worker 进程。" | tee -a "$LOG2"
echo "2. 观测：新 webhook 仍可接受（200），决策落库；执行层不处理 RESERVED。" | tee -a "$LOG2"
echo "3. 恢复：重新启动 execution worker。" | tee -a "$LOG2"
echo "4. 验证：/api/health/summary 或 log 中可追溯；新信号可继续走通。" | tee -a "$LOG2"
echo "（本脚本不自动 kill 进程；请手工执行或使用 pytest 注入失败）" | tee -a "$LOG2"
echo "场景2 说明已写入 $LOG2" | tee -a "$LOG2"

echo ""
echo "演练记录已写入 $LOG1, $LOG2"
