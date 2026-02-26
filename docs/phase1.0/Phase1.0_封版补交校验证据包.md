# Phase1.0 封版补交校验证据包

**补交日期**: 2026-02-03  
**依据**: 《Phase1.0_系统完成度检查报告》PR16/PR17 交付物遗漏项  
**原则**: 不引入任何新业务能力，仅补齐交付包写死的交付物，使 Phase1.0 达到 100% 交付物完成度。

---

## 一、变更清单（新增文件列表 + 路径）

| 序号 | 路径 | 说明 |
|------|------|------|
| 1 | `docker-compose.yml` | PR16：单机部署，db (Postgres) + app，db healthcheck，app depends_on condition: service_healthy，app command 显式 workers=1，env_file .env，DATABASE_URL 指向 db，volumes |
| 2 | `Dockerfile` | PR16：Python 镜像，pip install -e .，拷贝 src/ alembic/ alembic.ini config/，CMD uvicorn workers=1 |
| 3 | `.dockerignore` | PR16：忽略 .git、.venv、__pycache__、.pytest_cache、logs、dist、build 等 |
| 4 | `scripts/init_db.sh` | PR16：等待 DB 就绪（循环重试 alembic upgrade head），输出清晰日志，可独立执行或作为 compose run 执行 |
| 5 | `docs/API.md` | PR17：FastAPI /docs 为权威 OpenAPI，关键端点（含 TradingView webhook），验签头/签名方式（不泄露 secret），最小 curl 示例（占位 secret） |
| 6 | `docs/DEPLOYMENT.md` | PR17：本地部署（venv → .env → alembic upgrade head → uvicorn）、Docker Compose 部署（.env → docker compose up --build → init_db → 验证 /docs）、常见问题排查 |

**修改文件**：

| 路径 | 说明 |
|------|------|
| `README.md` | 增加指向 docs/API.md 与 docs/DEPLOYMENT.md 的链接 |

---

## 二、Docker 部署验证证据

**说明**：以下为交付物存在性及设计验证。若本机未启动 Docker Daemon，可跳过执行，仅保留“待验证”结论；在具备 Docker 环境时请执行并替换为实际输出。

### 2.1 docker compose up --build（最后 30 行示例）

在项目根目录执行：

```bash
cp .env.example .env
# 可选：在 .env 中设置 POSTGRES_USER、POSTGRES_PASSWORD、POSTGRES_DB
docker compose up --build
```

**预期**：先构建 app 镜像，再启动 db、app；app 在 db healthcheck 通过后启动，最后若干行类似：

```
app  | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
app  | INFO:     Started server process [1]
app  | INFO:     Application startup complete.
```

**当前环境**：Docker Daemon 未运行，未执行完整 up --build。交付物已按 PR16 要求编写，具备 db + app、healthcheck、depends_on、workers=1、env_file、DATABASE_URL、volumes。

### 2.2 docker compose ps

执行 `docker compose ps`，预期两服务均为 running（若已执行 up）。

### 2.3 docker compose logs app（启动成功片段）

执行 `docker compose logs app`，预期含 "Application started" 及 Uvicorn 监听 8000 的日志。

---

## 三、DB 初始化/迁移证据

### 3.1 scripts/init_db.sh 执行输出

在项目根目录、已设置 `DATABASE_URL`（或使用默认 SQLite）时执行：

```bash
bash scripts/init_db.sh
```

**实际输出**：

```
[init_db] Waiting for database to be ready...
[init_db] alembic upgrade head succeeded.
```

### 3.2 alembic upgrade head 输出（可选）

直接执行迁移时的典型输出：

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 010 -> 011, ...
INFO  [alembic.runtime.migration] Running upgrade 011 -> 012, ...
```

---

## 四、HTTP Smoke Test 证据

在应用已启动（本地或容器）的前提下：

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/openapi.json
```

**实际结果**（本地 uvicorn 启动后）：

- `GET http://127.0.0.1:8000/docs` → **200**
- `GET http://127.0.0.1:8000/openapi.json` → **200**

---

## 五、回归测试证据（默认离线）

### 5.1 pytest -q

```bash
pytest -q
```

**实际输出**：

```
........................................................................ [ 47%]
........................................................................ [ 94%]
........                                                                 [100%]
152 passed in 2.82s
```

### 5.2 pytest -ra

```bash
pytest -ra
```

**实际输出**：

```
============================= 152 passed in 2.48s ==============================
```

### 5.3 pytest -q tests/integration

```bash
pytest -q tests/integration
```

**实际输出**：

```
........................................................................ [ 91%]
.......                                                                  [100%]
79 passed in 2.23s
```

**说明**：上述运行中无 skipped、xfailed、warnings 导致失败；全部为 passed。

---

## 六、风险声明

- **本次仅补交付物**：新增/修改内容仅包括 PR16（Docker Compose 单机部署）与 PR17（docs/API.md、docs/DEPLOYMENT.md 及 README 链接），**未改变任何交易/执行/风控等业务逻辑**。
- **运行期行为**：应用启动方式、配置读取、数据库连接、Webhook 验签与执行流程与补交前一致；仅增加通过 Docker 与文档的部署与使用方式。
- **无新依赖**：Dockerfile 使用 `pip install -e .`，未在 pyproject.toml 中新增任何依赖。

---

## 七、结论

- PR16 交付物已补齐：`docker-compose.yml`、`Dockerfile`、`.dockerignore`、`scripts/init_db.sh` 已就位并符合封版要求。
- PR17 交付物已补齐：`docs/API.md`、`docs/DEPLOYMENT.md` 已就位，README 已链至上述文档。
- 回归测试：152 passed（含 79 个 integration），无失败/跳过。
- DB 初始化与 HTTP smoke test 已通过，可作为系统级审查的补充证据。

完成本次补交后，Phase1.0 交付物完成度可达 100%（以《Phase1.0开发交付包》PR16/PR17 所列交付物为基准）。建议在具备 Docker 环境时再执行一次 `docker compose up --build` 与 `docker compose logs app`，将实际输出补充到本证据包第二节，即可作为最终封版审查材料。
