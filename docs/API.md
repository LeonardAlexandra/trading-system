# API 说明（Phase1.0）

本文档说明系统对外 HTTP 接口。**权威 OpenAPI 规范**由 FastAPI 自动生成，启动应用后访问：

- **Swagger UI**: `http://localhost:8000/docs`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

---

## 关键端点

### 健康检查

- **GET** `/healthz`  
  无鉴权，返回 `{"status":"ok"}`，用于存活探测。

### TradingView Webhook（核心）

- **POST** `/webhook/tradingview`  
  接收 TradingView 发出的 Webhook 请求，验签通过后进入去重与执行流程。

**验签与请求头**：

- 使用请求头 **`X-TradingView-Signature`** 传递签名（不在此文档中泄露 secret）。
- 签名算法：对 **原始请求体（raw body）** 做 **HMAC-SHA256**，密钥为配置中的 Webhook Secret，结果经 **Base64** 编码后与请求头值比对。
- 验签必须基于原始 body bytes，禁止先用 `request.json()` 再序列化后验签。
- 签名缺失或错误时返回 **401**。

**最小 curl 示例**（占位 secret，仅作格式参考；必填字段见 docs/TRADINGVIEW_WEBHOOK.md）：

```bash
# 将 YOUR_WEBHOOK_SECRET 替换为 .env 中的 TV_WEBHOOK_SECRET
BODY='{"symbol":"BTCUSDT","action":"buy","strategy_id":"MOCK_STRATEGY_V1","timestamp":"2026-02-13T08:00:00Z"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "YOUR_WEBHOOK_SECRET" -binary | base64)
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -H "X-TradingView-Signature: $SIG" \
  -d "$BODY"
```

**说明**：生产环境必须使用与 TradingView 后台配置一致的 Webhook Secret，并保证 body 与验签时使用的完全一致（无空格/编码差异）。

---

## 其他

- **TradingView 接入步骤、请求体字段与中转方案**：见 [TradingView 信号接入说明](TRADINGVIEW_WEBHOOK.md)。
- 更多端点与请求/响应模型以 **FastAPI `/docs`** 为准。
- Phase1.0 无账户/订单查询等对外 REST API，仅 Webhook 与健康检查。
