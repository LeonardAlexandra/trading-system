# TradingView Signal Driven Trading System

TradingView 信号驱动的自动交易系统（Phase 1.0）

## 系统架构

- **TradingView**: 负责产生确定性交易信号
- **Python 系统**: 负责风控、状态管理、执行、优化

## 快速开始

### 本地快速启动（SQLite，新机器可直接跑）

**最小启动方案**（无需配置，使用默认 SQLite）：

```bash
# 1. 安装依赖
pip install -e ".[dev]"

# 2. 启动应用（使用默认 SQLite 数据库）
uvicorn src.app.main:app --reload

# 3. 验证健康检查
curl http://localhost:8000/healthz
# 预期输出: {"status":"ok"}
```

**说明**：
- 默认使用 SQLite 数据库：`sqlite+aiosqlite:///./trading_system.db`
- 无需配置 `.env` 文件即可启动
- 适合本地开发和快速验证

### 开发环境（完整配置）

1. **安装依赖**
   ```bash
   pip install -e ".[dev]"
   ```

2. **配置环境变量**
   ```bash
   cp .env.example .env
   # 编辑 .env 文件，配置数据库、交易所等
   # 最小配置：DATABASE_URL=sqlite+aiosqlite:///./trading_system.db
   ```

3. **初始化数据库**（如果使用 PostgreSQL，需要先运行迁移）
   ```bash
   alembic upgrade head
   ```

4. **启动应用（单实例，workers=1）**
   ```bash
   uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --workers 1 --reload
   ```

**环境变量说明**：
- `DATABASE_URL`: 数据库连接字符串（可选，默认使用 SQLite）
  - SQLite: `sqlite+aiosqlite:///./trading_system.db`
  - PostgreSQL（必须 asyncpg）: `postgresql+asyncpg://user:password@localhost:5432/trading_system`

### 生产环境（Docker Compose）

1. **配置环境变量**
   ```bash
   cp .env.example .env
   # 编辑 .env 文件
   ```

2. **启动（单机/单实例部署）**
   ```bash
   docker compose up --build -d
   ```

   **国内拉取镜像失败或 403 时**：在 `.env` 中设置镜像源并构建时传入基础镜像，例如：
   ```bash
   echo "DOCKER_MIRROR=docker.1ms.run" >> .env
   docker compose build --build-arg BASE_IMAGE=docker.1ms.run/library/python:3.11-slim
   docker compose up -d
   ```

3. **查看日志**
   ```bash
   docker-compose logs -f app
   ```

## 项目结构

```
trading_system/
├── src/                    # 源代码
│   ├── app/               # FastAPI 应用
│   ├── signal/            # 信号处理
│   ├── strategy/          # 策略执行
│   ├── risk/              # 风控管理
│   ├── execution/         # 订单执行
│   ├── adapters/          # 外部适配器
│   ├── repositories/      # 数据访问层
│   ├── models/            # 数据模型
│   └── utils/             # 工具函数
├── tests/                 # 测试
├── alembic/               # 数据库迁移
└── config/                # 配置文件
```

## 核心约束（Phase 1.0）

- **单实例运行**: `uvicorn workers=1`，禁止多进程/多实例
- **单交易所 + 单产品**: 固定 1 家交易所 + 1 种产品形态（spot/perp 二选一）
- **无消息队列**: 禁止 Celery/Redis/消息队列，定时任务用进程内调度（APScheduler）
- **幂等性保证**: 所有交易逻辑必须可追溯、可解释、可复现

## 文档

- **[API 说明](docs/API.md)**：关键端点、TradingView Webhook 验签与 curl 示例
- **[部署说明](docs/DEPLOYMENT.md)**：本地部署、Docker Compose 部署与常见问题排查

启动应用后，还可访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 开发规范

- 所有代码必须通过类型检查（mypy）
- 代码格式化使用 black
- 代码检查使用 ruff
- 测试使用 pytest

## 许可证

MIT
