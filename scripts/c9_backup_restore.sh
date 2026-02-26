#!/usr/bin/env bash
# C9 备份与恢复演练：SQLite 备份、恢复、校验。
# 用法：在项目根 trading_system 下执行
#   export DATABASE_URL=sqlite+aiosqlite:///./trading_system.db
#   bash scripts/c9_backup_restore.sh
# 输出：备份文件、恢复步骤、校验查询结果写入 docs/runlogs/
set -e
cd "$(dirname "$0")/.." || exit 1
OUT_DIR="${C9_RUNLOGS:-docs/runlogs}"
mkdir -p "$OUT_DIR"
TS=$(date +%Y%m%d_%H%M%S)
DB_URL="${DATABASE_URL:-sqlite+aiosqlite:///./trading_system.db}"
DB_PATH="${DB_URL#*:///}"
DB_PATH="${DB_PATH#*:}"
if [[ -z "$DB_PATH" || "$DB_PATH" == "$DB_URL" ]]; then
  DB_PATH="trading_system.db"
fi
BACKUP_FILE="$OUT_DIR/c9_backup_$TS.db"
LOG="$OUT_DIR/c9_backup_restore_$TS.log"

echo "=== C9 备份与恢复演练 ===" | tee "$LOG"
echo "DATABASE_URL=$DB_URL" | tee -a "$LOG"
echo "DB_PATH=$DB_PATH" | tee -a "$LOG"
echo "BACKUP_FILE=$BACKUP_FILE" | tee -a "$LOG"

# 备份
echo "" | tee -a "$LOG"
echo "--- 备份 ---" | tee -a "$LOG"
# 若路径为相对路径，确保其目录存在
if [[ "$DB_PATH" == ./* ]]; then
  mkdir -p "$(dirname "$DB_PATH")"
fi
if [[ ! -f "$DB_PATH" ]]; then
  echo "DB 文件不存在，先创建空库并迁移（alembic upgrade head）" | tee -a "$LOG"
  export DATABASE_URL="sqlite+aiosqlite:///$DB_PATH"
  (alembic upgrade head 2>&1 || true) | tee -a "$LOG"
fi
if [[ -f "$DB_PATH" ]]; then
  echo "执行: cp $DB_PATH $BACKUP_FILE" | tee -a "$LOG"
  cp "$DB_PATH" "$BACKUP_FILE"
  echo "备份完成: $BACKUP_FILE" | tee -a "$LOG"
else
  echo "无 DB 文件，跳过备份" | tee -a "$LOG"
  exit 0
fi

# 恢复（模拟：用备份覆盖当前 DB 后再校验）
echo "" | tee -a "$LOG"
echo "--- 恢复演练 ---" | tee -a "$LOG"
RESTORE_PATH="/tmp/c9_restore_verify_$TS.db"
echo "1. 将备份复制到临时路径: cp $BACKUP_FILE $RESTORE_PATH" | tee -a "$LOG"
cp "$BACKUP_FILE" "$RESTORE_PATH"
echo "2. 使用恢复后的 DB 做校验查询（sqlite3）" | tee -a "$LOG"
sync_path="${RESTORE_PATH}"
if command -v sqlite3 &>/dev/null; then
  echo "  decision_snapshot 条数:" | tee -a "$LOG"
  sqlite3 "$sync_path" "SELECT COUNT(*) FROM decision_snapshot;" 2>&1 | tee -a "$LOG"
  echo "  log 条数:" | tee -a "$LOG"
  sqlite3 "$sync_path" "SELECT COUNT(*) FROM log;" 2>&1 | tee -a "$LOG"
  echo "  trade 条数:" | tee -a "$LOG"
  sqlite3 "$sync_path" "SELECT COUNT(*) FROM trade;" 2>&1 | tee -a "$LOG"
  echo "  (若表不存在会报错，属未迁移或空库)" | tee -a "$LOG"
else
  echo "  sqlite3 未安装，跳过命令行校验；可用 Python 或应用接口校验。" | tee -a "$LOG"
fi

echo "" | tee -a "$LOG"
echo "--- 恢复命令（实际恢复时执行）---" | tee -a "$LOG"
echo "  cp $BACKUP_FILE $DB_PATH" | tee -a "$LOG"
echo "  然后重启应用。" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "演练记录已写入 $LOG"
