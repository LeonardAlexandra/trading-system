# 部署说明（Phase1.0 PR17）

本文档说明本地部署与 Docker Compose 单机部署方式，以及常见问题排查。

---

## 一、本地部署

1. **创建虚拟环境并安装依赖**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

2. **配置环境变量**
   ```bash
   cp .env.example .env
   # 编辑 .env：至少设置 DATABASE_URL（可选，默认 SQLite）
   # 若使用 PostgreSQL：DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/trading_system
   ```

3. **初始化数据库（迁移）**
   ```bash
   export DATABASE_URL=sqlite+aiosqlite:///./trading_system.db   # 或与 .env 一致
   alembic upgrade head
   ```

4. **启动应用（单实例，workers=1）**
   ```bash
   uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --workers 1
   ```

5. **验证**  
   访问 `http://localhost:8000/docs` 或 `curl http://localhost:8000/healthz`。

---

## 二、Docker Compose 部署

1. **准备 .env**
   ```bash
   cp .env.example .env
   # 可选：设置 POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB（默认见 docker-compose.yml）
   # 确保 TV_WEBHOOK_SECRET 等业务变量已配置
   ```

2. **构建并启动**
   ```bash
   docker compose up --build -d
   ```

3. **执行数据库迁移（首次或升级后）**  
   Compose 中 app 依赖 db 健康后才启动，首次部署建议显式执行迁移：
   ```bash
   docker compose run --rm app alembic upgrade head
   ```
   或使用提供的脚本（内部会重试直至 DB 就绪）：
   ```bash
   docker compose run --rm app scripts/init_db.sh
   ```

4. **验证**
   - `docker compose ps`：db、app 均为 running
   - `docker compose logs app`：无报错、应用已监听 8000
   - `curl http://localhost:8000/docs` 或 `curl http://localhost:8000/openapi.json` 返回 200
   - **交易情况展示（Phase1.2 最小 Dashboard）**：浏览器访问 **http://localhost:8000/dashboard**，可查看决策列表、执行/成交列表、汇总与健康状态（无交易时列表与汇总显示「无数据」属正常）

---

## 三、常见问题排查

| 现象 | 可能原因 | 处理建议 |
|------|----------|----------|
| 应用启动报错 database.url / DATABASE_URL | 未配置或 .env 未加载 | 设置 DATABASE_URL（或 config 中 database.url），确保从项目根目录启动或 env_file 正确 |
| alembic upgrade head 失败 | DB 未就绪或连接串错误 | 使用 PostgreSQL 时先确认 pg 已启动；Docker 下先 `docker compose up -d db`，再执行迁移 |
| Docker 中 app 启动即退出 | 依赖 db 未 healthy 或迁移未执行 | 查看 `docker compose logs app`；先 `docker compose up -d db`，再 `docker compose run --rm app alembic upgrade head`，最后 `docker compose up -d` |
| 端口 8000 或 5432 已被占用 | 本地已有服务占用 | 修改 docker-compose.yml 中 ports（如 8001:8000）或关闭占用端口的进程 |
| **GET /dashboard 返回 404** | 镜像为旧版本，未包含 Phase1.2 Dashboard 路由 | 在项目根目录执行 **无缓存重建**：`docker compose build --no-cache app`，完成后 `docker compose up -d`；再访问 http://localhost:8000/dashboard 或 http://localhost:8000/（根路径会重定向到 /dashboard） |
| Webhook 401 | 签名错误或 secret 不一致 | 确认 .env 中 TV_WEBHOOK_SECRET 与 TradingView 配置一致；验签使用原始 body，见 docs/API.md |

---

## 四、约束（Phase1.0）

- **单实例**：`uvicorn --workers 1`，禁止多 worker 或多实例部署。
- **单机 Compose**：仅 1 app + 1 db，禁止扩容。
- 更多限制见《系统使用指南-小白版》及《Phase1.0_Final_Evidence_Pack》中的已知限制。
