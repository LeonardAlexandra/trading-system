# Phase1.0 最终封版校验材料

**用途**：系统级封版审查用，仅补齐 PR16 部署可复现证据，不引入新功能、不修改业务逻辑。  
**执行日期**：2026-02-04  
**执行环境**：本机 Docker Daemon 已启动，在项目根目录执行 `docker compose` 系列命令。  
**一键复现**：在项目根目录、Docker 已启动时执行：

```bash
chmod +x scripts/phase10_seal_verify.sh && ./scripts/phase10_seal_verify.sh
```

---

## 【A】Docker Compose 实跑原始输出（硬证据）

### A-1）docker compose up --build

**要求**：至少最后 60 行；须可见 db service healthy、app service started/uvicorn running、无 fatal error / crash loop。

<details>
<summary>docker compose build 输出（最后约 60 行）</summary>

```
#9 152.5 Successfully installed Mako-1.3.10 MarkupSafe-3.0.3 aiodns-4.0.0 ... trading-system-0.1.0 ... yarl-1.22.0
#9 152.5 WARNING: Running pip as the 'root' user can result in broken permissions...
#9 DONE 155.7s

#10 [ 5/10] COPY src/ ./src/
#10 DONE 0.2s

#11 [ 6/10] COPY alembic/ ./alembic/
#11 DONE 0.0s

#12 [ 7/10] COPY alembic.ini ./
#12 DONE 0.0s

#13 [ 8/10] COPY config/ ./config/
#13 DONE 0.0s

#14 [ 9/10] COPY scripts/ ./scripts/
#14 DONE 0.0s

#15 [10/10] RUN mkdir -p /app/logs
#15 DONE 0.4s

#16 exporting to image
#16 exporting layers 10.4s done
#16 unpacking to docker.io/library/trading_system-app:latest 1.6s done
#16 DONE 12.0s

 trading_system-app  Built
```
</details>

<details>
<summary>docker compose up -d 输出</summary>

```
 Network trading_system_default  Creating
 Network trading_system_default  Created
 Volume trading_system_db_data  Creating
 Volume trading_system_db_data  Created
 Container trading_system-db-1  Creating
 Container trading_system-db-1  Created
 Container trading_system-app-1  Creating
 Container trading_system-app-1  Created
 Container trading_system-db-1  Starting
 Container trading_system-db-1  Started
 Container trading_system-db-1  Waiting
 Container trading_system-db-1  Healthy
 Container trading_system-app-1  Starting
 Container trading_system-app-1  Started
```
</details>

**结论**：db service healthy ✓，app service started ✓，无 fatal error ✓

### A-2）docker compose ps

**要求**：原始输出；app / db 均为 Up / healthy。

```
NAME                   IMAGE                COMMAND                  SERVICE   CREATED          STATUS                    PORTS
trading_system-app-1   trading_system-app   "uvicorn src.app.mai…"   app       19 seconds ago   Up 12 seconds             0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
trading_system-db-1    postgres:15-alpine   "docker-entrypoint.s…"   db        19 seconds ago   Up 18 seconds (healthy)   0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp
```

**结论**：app Up ✓，db Up (healthy) ✓

### A-3）docker compose logs app --tail=200

**要求**：应用启动完成；未出现配置校验失败 / migration fatal error。

```
app-1  | INFO:     Started server process [1]
app-1  | INFO:     Waiting for application startup.
app-1  | 2026-02-04 05:33:30,066 - src.app.main - INFO - Application started
app-1  | INFO:     Application startup complete.
app-1  | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**结论**：应用启动完成 ✓，无配置/migration 错误 ✓

---

## 【B】数据库初始化 / 迁移证据

**要求**：DB ready；alembic upgrade head 成功（或等价输出）；无失败回滚。

- `docker compose exec db pg_isready -U trading -d trading_system` 输出：

```
/var/run/postgresql:5432 - accepting connections
```

- `docker compose run --rm app bash scripts/init_db.sh` 输出：

```
 Container trading_system-db-1  Running
[init_db] Waiting for database to be ready...
[init_db] alembic upgrade head succeeded.
```

**结论**：DB ready ✓，alembic upgrade head 成功 ✓，无失败回滚 ✓

---

## 【C】HTTP 可用性证据

**要求**：HTTP 200；可截断 body 但保留 status + body 片段。

```
{"openapi":"3.1.0","info":{"title":"Trading System API","version":"0.1.0"},"paths":{"/healthz":{"get":{"summary":"Health Check"...}}}}}
---
HTTP_STATUS:200
```

**结论**：curl http://localhost:8000/openapi.json 返回 HTTP 200 ✓

---

## 【D】可重复性证据

**要求**：证明环境可完整清理、支持重复部署。

```
 Container trading_system-app-1  Stopping
 Container trading_system-app-1  Stopped
 Container trading_system-app-1  Removing
 Container trading_system-app-1  Removed
 Container trading_system-db-1  Stopping
 Container trading_system-db-1  Stopped
 Container trading_system-db-1  Removing
 Container trading_system-db-1  Removed
 Network trading_system_default  Removing
 Volume trading_system_db_data  Removing
 Volume trading_system_db_data  Removed
 Network trading_system_default  Removed
```

**结论**：docker compose down -v 完整清理 ✓，支持重复部署 ✓

---

## 【E】封版声明（必须）

- 本次操作**未修改任何业务逻辑**。  
- 本次仅**补齐 Phase1.0 PR16 的部署可复现证据**（含在镜像中加入 `scripts/`、修复 alembic 在 PostgreSQL 异步迁移路径下的 context 配置，为 PR16 交付要求所需，不改变应用业务行为）。  
- 当前仓库状态与《Phase1.0_系统完成度检查报告（终版）》一致，满足该报告结论：**Phase1.0 已满足全部交付包要求，可正式封版**。

---

## 通过判定自检

| 检查项 | 状态 |
|--------|------|
| 【A】【B】【C】【D】四项原始输出已齐全 | ✅ |
| Docker Compose 能真实启动 app + db | ✅ |
| DB 迁移成功（init_db.sh 中 alembic upgrade head 成功） | ✅ |
| HTTP endpoint 可访问（openapi.json 返回 200） | ✅ |
| 无「仅描述、不执行」的情况（所有输出为实跑结果） | ✅ |
| 无新增功能 / 无业务逻辑变更 | ✅ |

**结论**：✅ Phase1.0 满足最终封版条件

---

## 附录：本次代码变更（PR16 交付与迁移可用性）

| 文件 | 变更 | 性质 |
|------|------|------|
| `Dockerfile` | 增加 `COPY scripts/ ./scripts/` | 使容器内可执行 `scripts/init_db.sh`，满足 PR16 交付要求 |
| `alembic/env.py` | ① 保留 `postgresql+asyncpg` 用于 async 迁移；② 在 `do_run_migrations` 中增加 `context.configure` 与 `context.begin_transaction` | 修复 PostgreSQL 下 alembic 异步迁移路径的 AssertionError，非业务逻辑变更 |
