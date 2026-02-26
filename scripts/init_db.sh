#!/usr/bin/env bash
# Phase1.0 PR16：数据库初始化（等待 DB 就绪后执行 alembic upgrade head）
# 使用方式：
#  - 独立执行：在项目根目录、已设置 DATABASE_URL 时运行 ./scripts/init_db.sh
#  - Docker Compose：docker compose run --rm app scripts/init_db.sh（app 依赖 db 已 healthy，通常无需长等待）

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "[init_db] Waiting for database to be ready..."
max_attempts=30
attempt=1
while [ $attempt -le $max_attempts ]; do
  if alembic upgrade head 2>/dev/null; then
    echo "[init_db] alembic upgrade head succeeded."
    exit 0
  fi
  echo "[init_db] Attempt $attempt/$max_attempts failed, retrying in 2s..."
  sleep 2
  attempt=$((attempt + 1))
done

echo "[init_db] ERROR: Could not run migrations after $max_attempts attempts."
exit 1
