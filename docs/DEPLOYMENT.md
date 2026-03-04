# 部署说明

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
   # 编辑 .env，至少设置：
   # DATABASE_URL=sqlite+aiosqlite:///./trading_system.db
   # TV_WEBHOOK_SECRET=你的Webhook密钥
   ```

3. **初始化数据库（必须在首次启动前执行）**
   ```bash
   DATABASE_URL=sqlite+aiosqlite:///./trading_system.db alembic upgrade head
   ```

4. **启动应用（单实例，workers=1）**
   ```bash
   DATABASE_URL=sqlite+aiosqlite:///./trading_system.db \
     TV_WEBHOOK_SECRET=你的Webhook密钥 \
     uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --workers 1 --reload
   ```

5. **验证**

   | 地址 | 预期结果 |
   |------|----------|
   | `curl http://localhost:8000/healthz` | `{"status":"ok"}` |
   | `http://localhost:8000/dashboard` | 实时决策/成交展示页面 |
   | `http://localhost:8000/bi` | BI 只读分析展示页面（Phase 2.2） |
   | `http://localhost:8000/audit` | 审计查询页面 |
   | `http://localhost:8000/docs` | Swagger UI |

---

## 二、Docker Compose 部署

1. **准备 .env**
   ```bash
   cp .env.example .env
   # 编辑 .env：
   # - DATABASE_URL=postgresql+asyncpg://trading:trading_secret@db:5432/trading_system
   # - TV_WEBHOOK_SECRET=你的Webhook密钥
   # 可选：POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB（默认见 docker-compose.yml）
   ```

2. **构建并启动**
   ```bash
   docker compose up --build -d
   ```

3. **执行数据库迁移（首次或升级后）**
   ```bash
   docker compose run --rm app alembic upgrade head
   ```

4. **验证**
   - `docker compose ps`：db、app 均为 running
   - `docker compose logs app`：无报错、应用已监听 8000
   - `curl http://localhost:8000/healthz` → `{"status":"ok"}`
   - 浏览器访问 `http://localhost:8000/dashboard` — 实时决策/成交展示
   - 浏览器访问 `http://localhost:8000/bi` — BI 只读分析展示（Phase 2.2）
   - 浏览器访问 `http://localhost:8000/audit` — 审计查询

**国内拉取 Docker 镜像失败时**：
```bash
docker compose build --build-arg BASE_IMAGE=docker.1ms.run/library/python:3.11-slim
docker compose up -d
```

---

## 三、常见问题排查

| 现象 | 可能原因 | 处理建议 |
|------|----------|----------|
| 应用启动报错 `database.url / DATABASE_URL` | 未配置或 .env 未加载 | 设置 `DATABASE_URL`，确保从项目根目录启动 |
| `alembic upgrade head` 失败 | DB 未就绪或连接串错误 | 使用 PostgreSQL 时先确认 pg 已启动；Docker 下先 `docker compose up -d db` |
| Docker 中 app 启动即退出 | 依赖 db 未 healthy 或迁移未执行 | `docker compose logs app`；先 run db，再执行迁移，最后 `docker compose up -d` |
| 端口 8000 或 5432 已被占用 | 本地已有服务占用 | 修改 docker-compose.yml 中 ports 或关闭占用端口的进程 |
| **所有 API 返回 500** | 数据库表不存在 | 先执行 `alembic upgrade head` 创建所有表 |
| **GET /dashboard 返回 404** | 使用旧版镜像 | 无缓存重建：`docker compose build --no-cache app` |
| **GET /bi 或 /audit 返回 404** | 使用旧版镜像（Phase 2.2 前构建） | 无缓存重建：`docker compose build --no-cache app` |
| Webhook 401 | 签名错误或 secret 不一致 | 确认 `TV_WEBHOOK_SECRET` 与签名时使用的密钥一致；验签使用原始 body bytes |

---

## 四、约束

- **单实例**：`uvicorn --workers 1`，禁止多 worker 或多实例部署。
- **单机 Compose**：仅 1 app + 1 db，禁止扩容。
- **BI 只读**：`/bi` 和 `/api/bi/*` 不写入任何业务表，不改变系统状态。
- 更多限制见 [README.md — 系统架构与约束](../README.md#系统架构与约束)。
