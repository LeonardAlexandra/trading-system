# API 说明（Phase 2.2）

本文档列出系统所有 HTTP 端点。**权威 OpenAPI 规范**由 FastAPI 自动生成，启动后访问：

- **Swagger UI（可交互调试）**：`http://localhost:8000/docs`
- **ReDoc**：`http://localhost:8000/redoc`
- **OpenAPI JSON**：`http://localhost:8000/openapi.json`

---

## 页面（HTML）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 重定向到 `/dashboard` |
| GET | `/dashboard` | 实时决策/成交展示页面（Phase 1.2） |
| GET | `/bi` | BI 只读分析展示页面（Phase 2.2） |
| GET | `/audit` | 审计日志与决策追溯查询页面 |

---

## 健康与监控

### GET `/healthz`

存活探测，无鉴权。

**响应**（200）：
```json
{"status": "ok"}
```

### GET `/api/health/summary`

详细健康状态，包含数据库、交易所、执行引擎连接状态。

**响应**（200）：
```json
{
  "status": "ok",
  "database": "ok",
  "exchange": "ok",
  "scheduler": "ok"
}
```

### GET `/metrics`

Prometheus 格式 metrics（text/plain）。用于监控接入。

---

## TradingView Webhook

### POST `/webhook/tradingview`

接收 TradingView 发出的信号，验签通过后进入去重与执行流程。

**鉴权**：请求头 `X-TradingView-Signature`（HMAC-SHA256 of raw body, Base64 编码）。签名错误返回 401。

**请求体**（JSON）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `symbol` | string | 是 | 交易标的，如 `BTCUSDT` |
| `action` | string | 是 | `buy` / `sell` |
| `strategy_id` | string | 是 | 策略标识 |
| `timestamp` | string | 是 | ISO8601 时间，如 `2026-01-15T08:00:00Z` |
| `timeframe` | string | 否 | K 线周期，如 `1h` |

**响应**（200）：
```json
{
  "status": "accepted",
  "decision_id": "dec-xxxxxxxx",
  "signal_id": "sig-xxxxxxxx"
}
```

**curl 示例**：
```bash
SECRET="你的TV_WEBHOOK_SECRET"
BODY='{"symbol":"BTCUSDT","action":"buy","strategy_id":"MOCK_STRATEGY_V1","timestamp":"2026-01-15T08:00:00Z"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -binary | base64)
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -H "X-TradingView-Signature: $SIG" \
  -d "$BODY"
```

---

## Dashboard API

所有 Dashboard API 均为只读（GET），数据来自 `decision_snapshot` 和 `trade` 表。

### GET `/api/dashboard/decisions`

决策列表。

**查询参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `from` | ISO8601 | 开始时间（可选） |
| `to` | ISO8601 | 结束时间（可选） |
| `strategy_id` | string | 策略过滤（可选） |
| `limit` | int | 最大返回数，默认 100 |

**响应**（200）：
```json
[
  {
    "decision_id": "dec-xxx",
    "strategy_id": "MOCK_STRATEGY_V1",
    "symbol": "BTCUSDT",
    "side": "BUY",
    "created_at": "2026-01-15T08:00:00+00:00"
  }
]
```

### GET `/api/dashboard/executions`

成交记录列表。

**查询参数**：`from`、`to`、`limit`（同上）

**响应**（200）：
```json
[
  {
    "decision_id": "dec-xxx",
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": 0.001,
    "price": 50000.0,
    "realized_pnl": 10.5,
    "created_at": "2026-01-15T08:00:00+00:00"
  }
]
```

### GET `/api/dashboard/summary`

按日期或策略聚合统计。

**查询参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `from` | ISO8601 | 开始时间（可选） |
| `to` | ISO8601 | 结束时间（可选） |
| `group_by` | string | `day`（默认）或 `strategy` |

**响应**（200）：
```json
[
  {"group_key": "2026-01-15", "trade_count": 3, "pnl_sum": 45.0}
]
```

### GET `/api/dashboard/recent`

最近 N 条成交。

**查询参数**：`n`（默认 20，最大 100）

---

## BI 只读 API（Phase 2.2）

所有端点均为 GET，**不执行任何写操作**，不改变系统状态。

响应均包含 `"note": "本 API 为只读，不改变任何业务状态。"` 字段。

### GET `/api/bi/stats`

完整交易统计。数据来自 Phase 2.0 `metrics_snapshot`。

**查询参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `strategy_id` | string | 策略过滤（可选） |
| `from` | ISO8601 | `period_end >= from`（可选） |
| `to` | ISO8601 | `period_start <= to`（可选） |
| `group_by` | string | 备用参数，当前忽略 |

**响应**（200）：
```json
{
  "note": "本 API 为只读，不改变任何业务状态。",
  "data_source": "Phase 2.0 metrics_snapshot (read-only)",
  "count": 1,
  "items": [
    {
      "id": 1,
      "strategy_id": "S1",
      "period_start": "2025-01-01T00:00:00+00:00",
      "period_end": "2025-12-31T00:00:00+00:00",
      "trade_count": 100,
      "win_rate": 0.6,
      "realized_pnl": 1500.0,
      "max_drawdown": 0.05,
      "avg_holding_time_sec": 3600.0
    }
  ]
}
```

### GET `/api/bi/equity_curve`

权益曲线（累积 realized_pnl 时序）。数据来自 Phase 1.2 `trade` 表。

**查询参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `strategy_id` | string | 策略过滤（可选） |
| `from` | ISO8601 | 开始时间（可选） |
| `to` | ISO8601 | 结束时间（可选） |
| `granularity` | string | `day`（默认，仅说明用） |

**响应**（200）：
```json
{
  "note": "...",
  "count": 3,
  "points": [
    {"trade_id": "T1", "executed_at": "2025-01-01T00:00:00+00:00", "realized_pnl": 100.0, "cumulative_pnl": 100.0},
    {"trade_id": "T2", "executed_at": "2025-01-02T00:00:00+00:00", "realized_pnl": 200.0, "cumulative_pnl": 300.0}
  ]
}
```

### GET `/api/bi/decision_flow`

单笔决策链路（信号 → 风控 → 执行）。数据来自 Phase 1.2 TraceQueryService。

**查询参数**（至少提供一个）：

| 参数 | 类型 | 说明 |
|------|------|------|
| `decision_id` | string | 决策 ID |
| `signal_id` | string | 信号 ID |

**响应**：
- `200`：找到，含 `trace_status`（COMPLETE / PARTIAL）和 `missing_nodes`
- `400`：未提供任何参数 → `{"error": "需要提供 decision_id 或 signal_id"}`
- `404`：未找到 → `{"error": "未找到对应的决策链路 ..."}`

### GET `/api/bi/decision_flow/list`

决策链路列表。数据来自 Phase 1.2 TraceQueryService。

**查询参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `from` | ISO8601 | 开始时间（默认：1 年前） |
| `to` | ISO8601 | 结束时间（默认：当前） |
| `strategy_id` | string | 策略过滤（可选） |
| `limit` | int | 最大 200，默认 50 |
| `offset` | int | 偏移量，默认 0 |

每条含 `trace_status`（COMPLETE / PARTIAL / NOT_FOUND）和 `missing_nodes`。

### GET `/api/bi/version_history`

参数版本历史。数据来自 Phase 2.1 `param_version`。

**查询参数**：`strategy_id`（可选）、`limit`（默认 50）

**响应**（200）：
```json
{
  "count": 2,
  "items": [
    {
      "param_version_id": "PV1",
      "strategy_id": "S1",
      "params": {"stop_loss_pct": 0.02},
      "release_state": "active",
      "created_at": "2025-06-01T00:00:00+00:00"
    }
  ]
}
```

`release_state` 取值：`candidate` / `approved` / `active` / `stable` / `disabled`

### GET `/api/bi/evaluation_history`

评估报告历史。数据来自 Phase 2.0 `evaluation_report`。

**查询参数**：`strategy_id`（可选）、`from`、`to`、`limit`（默认 50）

**响应**（200）：每条含 `strategy_id`、`conclusion`（pass/fail/insufficient_data）、`period_start`、`period_end`、`evaluated_at`。

### GET `/api/bi/release_audit`

门禁/回滚/自动停用历史。数据来自 Phase 2.1 `release_audit`。

**查询参数**：`strategy_id`（可选）、`from`、`to`、`limit`（默认 50）

**响应**（200）：

```json
{
  "count": 1,
  "items": [
    {
      "strategy_id": "S1",
      "param_version_id": "PV1",
      "action": "APPLY",
      "gate_type": "MANUAL",
      "passed": true,
      "has_operator": true,
      "created_at": "2025-06-01T00:00:00+00:00"
    }
  ]
}
```

> **B4 脱敏**：`operator_or_rule_id` 字段不在响应中暴露，仅以 `has_operator`（bool）表示是否有操作者。

---

## 追溯 API

### GET `/api/trace/signal/{signal_id}`

按信号 ID 查询决策追溯链路。

### GET `/api/trace/decision/{decision_id}`

按决策 ID 查询决策追溯链路。

---

## 审计 API

### GET `/api/audit/logs/recent`

最近 ERROR/AUDIT 级别日志（快速查询，默认 100 条）。

### GET `/api/audit/logs`

分页查询审计日志。

**查询参数**：`from`、`to`、`component`、`level`、`limit`、`offset`

### GET `/api/audit/traces`

决策追溯列表（含 `trace_status`：COMPLETE / PARTIAL / NOT_FOUND）。

---

## 自动生成文档

| 地址 | 说明 |
|------|------|
| `/docs` | Swagger UI（可直接在浏览器中调试所有接口） |
| `/redoc` | ReDoc 文档 |
| `/openapi.json` | OpenAPI 规范 JSON |

---

## 更多说明

- **TradingView 接入步骤**：见 [TRADINGVIEW_WEBHOOK.md](TRADINGVIEW_WEBHOOK.md)
- **部署说明**：见 [DEPLOYMENT.md](DEPLOYMENT.md)
- **完整 Phase 2.1 操作（参数学习/发布门禁）**：见 README.md — Phase 2.1 章节
