# TradingView 信号驱动自动交易系统

> **TradingView → 风控 → 执行 → 评估 → 优化** 全链路自动交易系统（Phase 2.2 完成）
>
> 本系统接收 TradingView 策略信号，经过风险控制、订单执行、绩效评估，并通过参数学习与发布门禁实现自适应优化；全过程可追溯、可审计、可回滚。

---

## 目录

- [快速开始（3 步）](#快速开始3-步)
- [启动后可访问的页面](#启动后可访问的页面)
- [完整配置说明](#完整配置说明)
- [连接 TradingView](#连接-tradingview)
- [功能页面说明](#功能页面说明)
- [参数学习与版本管理（Phase 2.1）](#参数学习与版本管理phase-21)
- [项目结构](#项目结构)
- [系统架构与约束](#系统架构与约束)
- [开发与测试](#开发与测试)
- [许可证](#许可证)

---

## 快速开始（3 步）

**最小启动方案**（无需配置，使用默认 SQLite 数据库）：

```bash
# 1. 安装依赖
pip install -e ".[dev]"

# 2. 初始化数据库（必须在首次启动前执行）
DATABASE_URL=sqlite+aiosqlite:///./trading_system.db alembic upgrade head

# 3. 启动应用
DATABASE_URL=sqlite+aiosqlite:///./trading_system.db \
  TV_WEBHOOK_SECRET=你的Webhook密钥 \
  uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --workers 1 --reload
```

> **说明**：
> - `DATABASE_URL` 不设置时，应用会尝试读取 `.env` 文件；本地测试可直接在命令行传入。
> - `TV_WEBHOOK_SECRET` 是 TradingView Webhook 签名密钥，随机字符串即可（如 `my_secret_key_2026`）。
> - 启动后访问 http://localhost:8000 会自动跳转到 Dashboard。

### 使用 .env 文件（推荐）

```bash
cp .env.example .env
# 编辑 .env，至少设置以下两项：
# DATABASE_URL=sqlite+aiosqlite:///./trading_system.db
# TV_WEBHOOK_SECRET=你的密钥

alembic upgrade head
uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --workers 1 --reload
```

---

## 启动后可访问的页面

启动成功后，浏览器访问以下地址：

| 地址 | 说明 |
|------|------|
| http://localhost:8000 | 自动跳转到 Dashboard |
| http://localhost:8000/dashboard | 实时决策/成交展示页面 |
| http://localhost:8000/bi | BI 只读分析展示（统计/曲线/决策/历史） |
| http://localhost:8000/audit | 审计日志与决策追溯查询 |
| http://localhost:8000/docs | Swagger UI（所有 API 交互式文档） |
| http://localhost:8000/redoc | ReDoc（API 文档另一种展现方式） |
| http://localhost:8000/healthz | 健康检查（返回 `{"status":"ok"}`） |

---

## 完整配置说明

### 必填项

| 环境变量 | 说明 | 示例 |
|----------|------|------|
| `TV_WEBHOOK_SECRET` | TradingView Webhook 签名密钥（32+ 字符随机字符串） | `Kqeazh4x0Elza25BC3bKBCP23fp0beYu` |

### 数据库（二选一）

| 环境变量 | 说明 | 示例 |
|----------|------|------|
| `DATABASE_URL` | 数据库连接字符串 | SQLite（见下）或 PostgreSQL |

**SQLite（开发/测试，零依赖）**：
```
DATABASE_URL=sqlite+aiosqlite:///./trading_system.db
```

**PostgreSQL（生产推荐）**：
```
DATABASE_URL=postgresql+asyncpg://用户名:密码@localhost:5432/trading_system
```
> PostgreSQL 必须使用 `asyncpg` 驱动（URL 前缀 `postgresql+asyncpg://`）。

### 交易所配置（按需，默认 Paper Trading）

| 环境变量 | 说明 | 示例 |
|----------|------|------|
| `EXCHANGE_NAME` | 交易所名称（固定 1 家） | `okx` / `binance` / `bybit` |
| `EXCHANGE_SANDBOX` | `true` = 模拟交易，`false` = 实盘 | `true` |
| `EXCHANGE_API_KEY` | 交易所 API Key | `9e3b2fa1-...` |
| `EXCHANGE_API_SECRET` | 交易所 API Secret | `D435CDB6...` |
| `PRODUCT_TYPE` | 产品形态（固定 1 种） | `spot` / `perp` |

> **注意**：不配置交易所时，系统使用内置模拟引擎（PaperExchangeAdapter），**不会发出真实订单**。

### 日志配置（可选）

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `LOG_FILE` | 日志文件路径（留空则只输出到控制台） | 空 |
| `LOG_DATABASE` | 是否将审计日志写入数据库 | `true` |

### OKX Demo 配置（仅 OKX Demo 模式需要）

| 环境变量 | 说明 |
|----------|------|
| `OKX_API_KEY` | OKX Demo API Key |
| `OKX_SECRET` | OKX Demo Secret |
| `OKX_PASSPHRASE` | OKX Demo Passphrase |

### `.env.example` 模板

```bash
# 直接复制使用：
cp .env.example .env
```

---

## 连接 TradingView

> 完整说明见 [docs/TRADINGVIEW_WEBHOOK.md](docs/TRADINGVIEW_WEBHOOK.md)

### 简要流程

```
TradingView 告警触发
  → POST 到你的中转服务（加签名头 X-TradingView-Signature）
  → 中转 POST 到本系统 /webhook/tradingview
  → 系统验签 → 去重 → 执行 → Dashboard 可见结果
```

### 本地快速测试（curl 模拟）

不需要 TradingView，直接用 curl 模拟一个信号：

```bash
# 1. 设置 Webhook 密钥（与 .env 中 TV_WEBHOOK_SECRET 一致）
SECRET="你的Webhook密钥"

# 2. 构造信号体
BODY='{"symbol":"BTCUSDT","action":"buy","strategy_id":"MOCK_STRATEGY_V1","timestamp":"2026-01-15T08:00:00Z"}'

# 3. 计算签名
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -binary | base64)

# 4. 发送请求
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -H "X-TradingView-Signature: $SIG" \
  -d "$BODY"

# 预期响应：{"status":"accepted","decision_id":"...","signal_id":"..."}
```

### 在 TradingView 中配置告警

> 因 TradingView 不支持自定义请求头，需要中转服务帮你加签名。
> 最简单的方式：用本项目自带脚本 + ngrok，详见 [docs/TRADINGVIEW_WEBHOOK.md](docs/TRADINGVIEW_WEBHOOK.md)。

**TradingView 告警消息体模板**：
```json
{
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "strategy_id": "MOCK_STRATEGY_V1",
  "timestamp": "{{timenow}}",
  "timeframe": "{{interval}}"
}
```

---

## 功能页面说明

### `/dashboard` — 实时决策/成交展示

- 显示最近的决策列表（信号→决策→执行链路）
- 显示成交记录（数量、价格、盈亏）
- 汇总统计（胜率、总盈亏）
- 健康状态（数据库、交易所、执行引擎）

![Dashboard 展示决策列表、成交记录、汇总与健康状态]

### `/bi` — BI 只读分析展示

Phase 2.2 BI 层，**纯展示，无任何写操作**：

| 区块 | 内容 | 数据来源 |
|------|------|----------|
| A1 完整统计 | 胜率/盈亏/回撤/交易次数 | Phase 2.0 评估快照 |
| A1 权益曲线 | 累积盈亏时序曲线 | Phase 1.2 trade 表 |
| A2 决策链路 | 信号→理由→风控→执行链路，含 PARTIAL/NOT_FOUND 展示 | Phase 1.2 追溯 API |
| B1 版本历史 | 参数版本变更列表（状态/时间） | Phase 2.1 param_version |
| B1 评估历史 | 历次评估报告（结论/时间段） | Phase 2.0 evaluation_report |
| B2 门禁历史 | 发布/回滚/自动停用操作记录 | Phase 2.1 release_audit |

> 所有区块均支持时间范围、strategy_id 筛选；点击「查询」按钮加载数据。

### `/audit` — 审计查询

- 查询最近 ERROR/AUDIT 日志
- 按时间/组件/级别分页查询日志
- 决策追溯（list_traces）：含 `trace_status`（COMPLETE/PARTIAL/NOT_FOUND）和 `missing_nodes`

### `/docs` — API 文档（Swagger UI）

所有 API 端点的交互式文档，可直接在浏览器中调试。

---

## 参数学习与版本管理（Phase 2.1）

Phase 2.1 实现了参数自动学习与发布门禁：

### 发布状态机

```
         submit_candidate
              ↓
         [candidate]
         ↙         ↘
confirm_manual   risk_guard_approve
         ↘         ↙
         [approved]
              ↓
         apply_approved
              ↓
          [active]  ←── 只有 active 状态才允许交易
         ↙         ↘
     mark_stable  auto_disable/reject
         ↓               ↓
       [stable]       [disabled]
         ↑
   rollback_to_stable（从 active 快速回滚到 stable）
```

### 核心操作（通过 Phase21Service）

| 操作 | 说明 |
|------|------|
| `suggest_params` | 基于 Phase 2.0 评估报告生成参数建议 |
| `submit_candidate` | 提交候选版本（进入 candidate 状态） |
| `confirm_manual` | 人工审批通过（candidate → approved） |
| `risk_guard_approve` | 风控护栏审批（candidate → approved） |
| `apply_approved` | 生效（approved → active） |
| `mark_stable` | 标记为稳定基线（active → stable） |
| `rollback_to_stable` | 一键回滚到 stable（active → disabled，stable → active） |
| `check_auto_disable` | 异常检测（连续亏损/健康检查失败时自动停用） |

### 可学习参数（白名单，不可修改）

- `max_position_size` — 最大仓位
- `fixed_order_size` — 固定下单量
- `stop_loss_pct` — 止损百分比
- `take_profit_pct` — 止盈百分比

### 自动停用触发条件（B.2）

- 连续亏损交易 ≥ 5 笔
- 连续亏损金额 ≥ 1000
- 最大回撤 ≥ 10%
- 数据库或交易所健康检查失败

---

## 生产环境部署（Docker Compose）

```bash
# 1. 配置 .env
cp .env.example .env
# 编辑 .env：设置 DATABASE_URL（PostgreSQL）、TV_WEBHOOK_SECRET 等

# 2. 构建并启动
docker compose up --build -d

# 3. 初始化数据库迁移
docker compose run --rm app alembic upgrade head

# 4. 验证
curl http://localhost:8000/healthz
# 浏览器访问 http://localhost:8000
```

**国内拉取 Docker 镜像失败时**：
```bash
echo "DOCKER_MIRROR=docker.1ms.run" >> .env
docker compose build --build-arg BASE_IMAGE=docker.1ms.run/library/python:3.11-slim
docker compose up -d
```

> 详细部署说明见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

---

## 项目结构

```
.
├── src/
│   ├── app/
│   │   ├── main.py              # FastAPI 应用入口（lifespan + 路由注册）
│   │   ├── routers/             # HTTP 路由
│   │   │   ├── bi.py            # Phase 2.2 BI 只读 API（7 个端点）
│   │   │   ├── bi_page.py       # Phase 2.2 BI 展示页面
│   │   │   ├── dashboard.py     # Dashboard API
│   │   │   ├── dashboard_page.py # Dashboard 页面
│   │   │   ├── signal_receiver.py # TradingView Webhook
│   │   │   ├── health.py        # 健康检查与 metrics
│   │   │   ├── trace.py         # 决策追溯 API
│   │   │   ├── audit.py         # 审计日志 API
│   │   │   └── audit_page.py    # 审计查询页面
│   │   └── dependencies.py      # 依赖注入（SessionFactory）
│   ├── application/
│   │   ├── phase21_service.py   # Phase 2.1 应用层（参数学习/发布门禁）
│   │   └── phase2_main_flow_service.py # Phase 2.0 评估主流程
│   ├── phase21/
│   │   ├── optimizer.py         # 参数建议（Optimizer）
│   │   ├── release_gate.py      # 发布门禁（ReleaseGate）
│   │   ├── auto_disable_monitor.py # 自动停用监控
│   │   └── whitelist.py         # 可学习参数白名单（B.1）
│   ├── phase2/
│   │   └── evaluator.py         # Phase 2.0 评估器
│   ├── models/                  # SQLAlchemy ORM 模型
│   ├── repositories/            # 数据访问层
│   ├── services/                # 服务层（TraceQueryService 等）
│   ├── config/
│   │   └── app_config.py        # AppConfig 统一配置（Fail-fast 校验）
│   └── database/
│       └── connection.py        # 数据库引擎初始化
├── tests/
│   ├── e2e/                     # E2E 测试（Phase 2.1/2.2 全闭环）
│   ├── integration/             # 集成测试
│   └── unit/                    # 单元测试
├── alembic/
│   └── versions/                # 26 个数据库迁移文件
├── docs/
│   ├── API.md                   # API 端点说明
│   ├── DEPLOYMENT.md            # 部署说明
│   └── TRADINGVIEW_WEBHOOK.md   # TradingView 信号接入说明
├── config/
│   ├── config.example.yaml      # 配置文件示例
│   └── alert_rules.example.yaml # 告警规则示例
├── scripts/                     # 运维工具脚本
├── .env.example                 # 环境变量模板
├── pyproject.toml               # 项目元数据与依赖
└── alembic.ini                  # Alembic 迁移配置
```

---

## 系统架构与约束

### 架构概览

```
TradingView 信号
    │
    ↓ POST /webhook/tradingview（HMAC-SHA256 验签）
信号接收与去重
    │
    ↓
风险控制（仓位/余额/熔断/冷却）
    │
    ↓
订单执行（单实例、APScheduler 调度）
    │
    ↓
交易记录（trade 表，Phase 1.2）
    │
    ↓
Phase 2.0 评估（metrics_snapshot + evaluation_report）
    │
    ↓
Phase 2.1 参数学习（optimizer + release_gate + param_version）
    │
    ↓
Phase 2.2 BI 展示（只读，/bi 页面 + /api/bi/* API）
```

### 硬性约束（不可违反）

| 约束 | 说明 |
|------|------|
| **单实例** | `uvicorn --workers 1`，禁止多进程/多实例 |
| **单交易所** | 固定 1 家交易所 + 1 种产品形态（spot/perp） |
| **无消息队列** | 禁止 Celery/Redis，定时任务用 APScheduler |
| **可追溯性** | 所有交易决策必须可追溯、可解释、可复现 |
| **BI 只读** | /bi 和 /api/bi/* 不写入任何业务表，不改变系统状态 |
| **参数白名单** | 只有 4 个白名单参数可被优化器修改 |

---

## 开发与测试

### 运行测试

```bash
# 运行全部测试（387 个，0 失败）
python -m pytest --tb=short -q

# 运行特定测试模块
python -m pytest tests/e2e/test_e2e_phase22_bi_readonly.py -v    # Phase 2.2 BI 测试
python -m pytest tests/e2e/test_e2e_phase21_full_cycle.py -v     # Phase 2.1 全闭环测试

# 带覆盖率
python -m pytest --cov=src --cov-report=term-missing
```

### 代码质量

```bash
black src/ tests/      # 格式化
ruff check src/ tests/ # Lint 检查
mypy src/              # 类型检查
```

### 数据库迁移

```bash
# 应用所有迁移到最新
alembic upgrade head

# 查看当前迁移状态
alembic current

# 回滚一步
alembic downgrade -1
```

### API 文档

启动应用后访问：
- **Swagger UI**：http://localhost:8000/docs（可交互调试）
- **ReDoc**：http://localhost:8000/redoc
- **OpenAPI JSON**：http://localhost:8000/openapi.json

---

## 常见问题

**Q: 启动报错「SessionFactory not initialized」**
A: 数据库连接未初始化。检查 `DATABASE_URL` 是否正确，确保 `.env` 中配置了该变量。

**Q: alembic upgrade head 报错「unable to open database file」**
A: SQLite 文件路径问题。确保 `DATABASE_URL=sqlite+aiosqlite:///./trading_system.db`（3 个斜杠）且从项目根目录运行。

**Q: Webhook 返回 401**
A: 签名验证失败。检查 `TV_WEBHOOK_SECRET` 与签名时使用的密钥是否一致，签名必须基于原始 body bytes。

**Q: /dashboard 或 /bi 返回 404**
A: 可能使用了旧版 Docker 镜像。重新构建：`docker compose build --no-cache app`。

**Q: 所有 API 返回 500 Internal Server Error**
A: 数据库表不存在，需要先运行 `alembic upgrade head`。

---

## 许可证

MIT
