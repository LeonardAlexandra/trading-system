#!/usr/bin/env bash
# Phase1.0 最终封版校验脚本：在 Docker 可用环境下执行，生成可审计的原始输出
# 用法：在项目根目录执行 ./scripts/phase10_seal_verify.sh
# 输出将写入 docs/Phase1.0_封版校验_实跑输出.txt

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"
OUTPUT_FILE="${ROOT_DIR}/docs/Phase1.0_封版校验_实跑输出.txt"

echo "========== Phase1.0 封版校验实跑输出 ==========" | tee "$OUTPUT_FILE"
echo "执行时间: $(date -Iseconds)" | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

# 清理
echo "----------------------------------------"
echo "【预清理】docker compose down -v"
echo "----------------------------------------"
docker compose down -v 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

# 1) 构建并启动（等价于 docker compose up --build，后台模式以便后续执行其他命令）
echo "----------------------------------------"
echo "【A-1】docker compose up --build（build + up -d 完整输出）"
echo "----------------------------------------"
docker compose build 2>&1 | tee -a "$OUTPUT_FILE"
docker compose up -d 2>&1 | tee -a "$OUTPUT_FILE"
sleep 10
echo "" >> "$OUTPUT_FILE"

echo "----------------------------------------"
echo "【A-2】docker compose ps"
echo "----------------------------------------"
docker compose ps 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "----------------------------------------"
echo "【A-3】docker compose logs app --tail=200"
echo "----------------------------------------"
docker compose logs app --tail=200 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "----------------------------------------"
echo "【B】数据库就绪 + init_db.sh"
echo "----------------------------------------"
echo ">>> docker compose exec db pg_isready -U trading -d trading_system"
docker compose exec -T db pg_isready -U trading -d trading_system 2>&1 | tee -a "$OUTPUT_FILE"
echo ""
echo ">>> docker compose run --rm app bash scripts/init_db.sh"
docker compose run --rm app bash scripts/init_db.sh 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "----------------------------------------"
echo "【C】HTTP smoke test: curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/openapi.json"
echo "----------------------------------------"
curl -s -o /tmp/openapi.json -w "HTTP_STATUS=%{http_code}\n" http://localhost:8000/openapi.json 2>&1 | tee -a "$OUTPUT_FILE"
head -c 500 /tmp/openapi.json 2>/dev/null >> "$OUTPUT_FILE" || true
echo "" | tee -a "$OUTPUT_FILE"

echo "----------------------------------------"
echo "【D】docker compose down -v（可重复性）"
echo "----------------------------------------"
docker compose down -v 2>&1 | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

echo "========== 校验脚本执行结束 ==========" | tee -a "$OUTPUT_FILE"
echo "完整输出已写入: $OUTPUT_FILE"
