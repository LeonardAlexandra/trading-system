# TradingView 量化交易系统

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

一个专业的 TradingView 信号接收与量化交易执行系统，支持策略管理、风险控制、实时监控和完整的审计追踪。

## ✨ 核心特性

- **📡 信号接收**: 接收 TradingView Webhook 信号，支持 HMAC-SHA256 签名验证
- **🎯 策略执行**: 自动执行交易策略，支持多策略隔离运行
- **🛡️ 风险控制**: 内置风控系统，支持仓位限制、冷却时间、熔断机制
- **📊 实时监控**: Dashboard 实时展示决策、成交、持仓和健康状态
- **🔍 完整审计**: 全链路追踪，支持决策回溯和性能分析
- **🏦 交易所支持**: 支持 OKX 交易所（Paper Trading / 实盘）
- **📈 BI 分析**: 内置业务智能分析，支持策略绩效评估

## 🚀 快速开始

### 环境要求

- Python 3.11+
- PostgreSQL 14+ (生产环境) / SQLite (开发环境)
- Docker & Docker Compose (可选)

### 1. 克隆项目

```bash
git clone https://github.com/LeonardAlexandra/trading-system.git
cd trading-system
```

### 2. 配置环境

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，配置以下关键项：
# - TV_WEBHOOK_SECRET: TradingView Webhook 密钥
# - EXCHANGE_API_KEY: 交易所 API Key
# - EXCHANGE_API_SECRET: 交易所 API Secret
# - DATABASE_URL: 数据库连接字符串
```

### 3. 安装依赖

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -e ".[dev]"
```

### 4. 初始化数据库

```bash
# SQLite (开发环境)
alembic upgrade head

# PostgreSQL (生产环境)
# 确保 PostgreSQL 已启动，然后执行：
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/trading_system alembic upgrade head
```

### 5. 启动服务

```bash
# 开发模式
uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --reload

# 生产模式
uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### 6. 访问系统

| 功能 | 地址 |
|------|------|
| Dashboard | http://localhost:8000/dashboard |
| API 文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/healthz |
| BI 分析 | http://localhost:8000/bi |
| 审计查询 | http://localhost:8000/audit |

## 🐳 Docker 部署

### 使用 Docker Compose

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，设置 DATABASE_URL 为 PostgreSQL

# 2. 启动服务
docker compose up -d

# 3. 执行数据库迁移
docker compose run --rm app alembic upgrade head

# 4. 查看日志
docker compose logs -f app
```

### 国内镜像加速

```bash
docker compose build --build-arg BASE_IMAGE=docker.1ms.run/library/python:3.11-slim
docker compose up -d
```

## 📡 TradingView 配置

### 1. 配置 Webhook 中转

TradingView 不支持自定义请求头，需要中转服务添加签名。

**方案 A: 使用 ngrok + 本地中转**

```bash
# 1. 启动中转服务
export TV_WEBHOOK_SECRET="你的密钥"
python scripts/relay_tradingview_webhook.py

# 2. 使用 ngrok 暴露到公网
ngrok http 8080

# 3. 获取 https://xxx.ngrok.io/webhook 地址填入 TradingView
```

**方案 B: 使用云函数/无代码平台**

- Make (Integromat)
- Zapier
- n8n

### 2. TradingView 告警配置

1. 打开 TradingView 图表，加载你的策略
2. 点击 **「告警」** → **「创建告警」**
3. **条件**: 选择策略或指标条件
4. **通知**: 勾选 **「Webhook URL」**，填入中转地址
5. **消息**: 填写以下 JSON：

```json
{
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "strategy_id": "MOCK_STRATEGY_V1",
  "timestamp": "{{timenow}}",
  "timeframe": "{{interval}}"
}
```

### 3. 测试信号

```bash
# 本地测试
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -H "X-TradingView-Signature: <签名>" \
  -d '{
    "symbol": "BTCUSDT",
    "action": "buy",
    "strategy_id": "MOCK_STRATEGY_V1",
    "timestamp": "2026-03-04T08:00:00Z"
  }'
```

## 📁 项目结构

```
trading-system/
├── src/                    # 源代码
│   ├── app/               # FastAPI 应用
│   │   ├── main.py        # 应用入口
│   │   ├── routers/       # API 路由
│   │   └── dependencies.py # 依赖注入
│   ├── adapters/          # 外部适配器
│   │   ├── tradingview_adapter.py  # TradingView 适配
│   │   └── market_data.py            # 市场数据
│   ├── application/       # 应用服务层
│   │   ├── signal_service.py         # 信号处理
│   │   └── phase2_main_flow_service.py # 主流程
│   ├── config/            # 配置管理
│   │   ├── app_config.py             # 应用配置
│   │   └── strategy_resolver.py      # 策略解析
│   ├── execution/         # 执行引擎
│   │   ├── execution_engine.py       # 执行引擎
│   │   ├── execution_worker.py       # 执行工作器
│   │   ├── order_manager.py          # 订单管理
│   │   ├── position_manager.py       # 仓位管理
│   │   ├── risk_manager.py           # 风险管理
│   │   └── okx_client.py             # OKX 客户端
│   ├── models/            # 数据模型
│   ├── repositories/      # 数据仓库
│   ├── services/          # 领域服务
│   └── utils/             # 工具函数
├── config/                # 配置文件
│   ├── config.example.yaml # 配置示例
│   └── alert_rules.example.yaml # 告警规则示例
├── docs/                  # 文档
│   ├── API.md            # API 文档
│   ├── DEPLOYMENT.md     # 部署指南
│   └── TRADINGVIEW_WEBHOOK.md # TradingView 配置
├── alembic/              # 数据库迁移
├── scripts/              # 工具脚本
├── tests/                # 测试
└── docker-compose.yml    # Docker 配置
```

## ⚙️ 配置说明

### 环境变量 (.env)

| 变量 | 说明 | 示例 |
|------|------|------|
| `DATABASE_URL` | 数据库连接 | `sqlite+aiosqlite:///./trading_system.db` |
| `TV_WEBHOOK_SECRET` | TradingView Webhook 密钥 | `your_secret_key` |
| `EXCHANGE_NAME` | 交易所名称 | `okx` |
| `EXCHANGE_API_KEY` | API Key | `your_api_key` |
| `EXCHANGE_API_SECRET` | API Secret | `your_api_secret` |
| `EXCHANGE_SANDBOX` | 沙盒模式 | `true` / `false` |
| `PRODUCT_TYPE` | 产品类型 | `spot` / `perp` |
| `LOG_LEVEL` | 日志级别 | `INFO` / `DEBUG` / `ERROR` |

### 策略配置 (config/config.yaml)

```yaml
strategies:
  MOCK_STRATEGY_V1:
    enabled: true
    execution_override:
      dry_run: false
    risk_override:
      max_position_qty: 0.1
      max_order_qty: 0.01

exchange:
  name: "okx"
  sandbox: true
```

## 🛡️ 安全建议

1. **Webhook 密钥**: 使用强随机字符串，定期更换
2. **API 密钥**: 使用权限受限的 API Key，不要给提现权限
3. **IP 白名单**: 在交易所设置 IP 白名单
4. **沙盒测试**: 实盘前务必在沙盒环境充分测试
5. **监控告警**: 配置异常监控和告警

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/integration/test_signal_receiver.py

# 带覆盖率报告
pytest --cov=src --cov-report=html
```

## 📊 监控指标

系统内置以下监控指标：

- **信号接收延迟**: `signal_receiver.latency_ms`
- **决策生成延迟**: `signal_service.latency_ms`
- **订单执行延迟**: `execution.latency_ms`
- **风控检查次数**: `risk.check_count`
- **仓位一致性**: `position.consistency_check`

## 🔧 故障排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 401 Unauthorized | 签名错误 | 检查 TV_WEBHOOK_SECRET 是否一致 |
| 422 STRATEGY_NOT_FOUND | 策略未配置 | 在 config.yaml 中添加策略配置 |
| 500 Internal Error | 数据库表不存在 | 执行 `alembic upgrade head` |
| 数据库连接失败 | 连接字符串错误 | 检查 DATABASE_URL 格式 |

## 📝 更新日志

### v2.2.0 (2026-03)
- ✅ 新增 BI 分析页面
- ✅ 支持策略绩效评估
- ✅ 完善审计追踪功能

### v2.1.0 (2026-02)
- ✅ 新增发布门禁系统
- ✅ 支持参数优化
- ✅ 强化风险控制

### v2.0.0 (2026-01)
- ✅ 支持多策略隔离
- ✅ 新增持仓一致性监控
- ✅ 完善日志追踪

### v1.2.0 (2025-12)
- ✅ Dashboard 实时监控
- ✅ 决策快照功能
- ✅ 性能日志记录

### v1.1.0 (2025-11)
- ✅ 信号去重机制
- ✅ 风控系统完善
- ✅ 外部数据同步

### v1.0.0 (2025-10)
- ✅ 基础交易执行
- ✅ OKX 交易所对接
- ✅ Webhook 信号接收

## 🤝 贡献指南

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## ⚠️ 免责声明

本软件仅供学习和研究使用，不构成任何投资建议。使用本软件进行交易可能面临资金损失风险，请谨慎使用。

## 📞 联系方式

- GitHub Issues: [提交问题](https://github.com/LeonardAlexandra/trading-system/issues)
- Email: johnemerson928760923@gmail.com

---

**Happy Trading! 📈**
