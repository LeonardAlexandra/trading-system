# TradingView 信号接入说明

本文说明如何在 TradingView 中观测/暴露交易信号，并配置传入本系统。

---

## 零、在 TradingView 中观测与暴露信号

### 信号从哪里来

TradingView 中的「信号」通常来自两类触发方式，最终都通过**告警（Alert）** 发出：

1. **策略（Strategy）**  
   在图表上加载或编写策略后，策略的「开多/开空/平仓」等订单动作会作为可告警条件。  
   - 观测：图表上的策略标签、策略测试器里的成交列表、以及创建告警时可选「策略订单成交」等条件。  
   - 暴露：为该策略创建告警，并选择「通过 Webhook URL」发送，即可把每次触发的信号发到外部系统。

2. **指标/条件（Indicator / Condition）**  
   用任意指标或画线、条件（如价格上穿某均线）作为告警条件。  
   - 观测：指标数值、条件成立时的提示。  
   - 暴露：创建告警时选择「指标/条件」作为触发源，再选 Webhook URL 发送。

因此：**要观测信号** = 在图表/策略测试器里看策略或指标是否按预期触发；**要把信号传入本系统** = 为这些触发条件创建告警，并配置 Webhook URL 与消息体（见下文）。

### TradingView 端配置步骤（概览）

| 步骤 | 在 TradingView 中的操作 |
|------|------------------------|
| 1 | 打开目标图表，确保已加载策略或指标（信号源）。 |
| 2 | 点击 **「告警」**（Alerts）按钮（或菜单：插入 → 告警），新建告警。 |
| 3 | **条件**：选择「策略/指标」及具体条件（如「Strategy › 订单成交」或某指标「交叉/大于」等）。 |
| 4 | **通知**：在「通知」里勾选 **「Webhook URL」**，在输入框中填写**接收端 URL**（见下节说明）。 |
| 5 | **消息**：在「消息」框中填写 JSON，必须包含本系统要求的字段（见第四节）。 |
| 6 | 保存告警；触发后 TradingView 会向该 URL 发送一次 POST，body 为你填的 JSON（占位符会被替换）。 |

**重要**：TradingView 只会把请求发到你填的 URL，**不会**添加签名头。若 URL 直接填本系统的 `/webhook/tradingview`，会因缺少 `X-TradingView-Signature` 返回 401。因此需要**中转服务**代为计算签名并转发到本系统，或先用 **curl 模拟** 验证本系统（见第二节）。

### 中转 Webhook URL 如何获取

中转 URL **不是**某个现成网站的链接，而是**你部署或运行的中转服务**的地址，常见三种方式：

| 方式 | 你得到的 URL | 说明 |
|------|--------------|------|
| **本仓库自带中转脚本 + ngrok** | `https://xxx.ngrok.io/webhook` | 本地运行脚本，用 ngrok 暴露端口，把 ngrok 给的 HTTPS 地址填进 TradingView（推荐先这样试）。 |
| **无代码平台（Zapier / Make / n8n）** | 平台提供的「Webhook 触发」URL | 在平台里创建「接收 Webhook」→ 用代码/步骤计算签名并请求本系统，平台会给你一个唯一 URL。 |
| **自建服务器 / 云函数** | 你域名或云函数地址 | 自己写或部署一个接收 POST、加签名、转发到本系统的小服务，该服务的公网 URL 即填进 TradingView 的地址。 |

**最快上手**：用本仓库自带脚本 + ngrok，具体步骤见 [第五节：用自带脚本获取中转 URL](#五用自带脚本获取中转-url)。

---

## 一、本系统 Webhook 约定

- **URL**：`POST /webhook/tradingview`  
  完整示例：`https://你的域名或IP:8000/webhook/tradingview`（本地：`http://localhost:8000/webhook/tradingview`）

- **请求头**
  - `Content-Type: application/json`
  - **`X-TradingView-Signature`**（必填）：对**原始 JSON 请求体**做 HMAC-SHA256，密钥为 `.env` 中的 `TV_WEBHOOK_SECRET`，结果再 Base64 编码后放在此头。签名错误或缺失返回 401。

- **请求体（JSON）必填字段**

  | 字段 | 说明 | 示例 |
  |------|------|------|
  | `symbol` 或 `ticker` | 交易对，会转成大写 | `"BTCUSDT"` |
  | `side` 或 `action` | 方向 | `"buy"` / `"sell"` |
  | `timestamp` 或 `bar_time` 或 `time` | 时间，支持 ISO 字符串或 Unix 秒数 | `"2026-02-13T08:00:00Z"` 或 `1739422800` |
  | `strategy_id` 或 `strategy` | 策略 ID，**必须在系统配置中存在** | `"MOCK_STRATEGY_V1"` |

  可选：`timeframe`、`interval`、`indicator_name` 等，用于展示与去重语义。

**示例 JSON 请求体**：

```json
{
  "symbol": "BTCUSDT",
  "action": "buy",
  "strategy_id": "MOCK_STRATEGY_V1",
  "timestamp": "2026-02-13T08:00:00Z",
  "timeframe": "1h"
}
```

---

## 二、TradingView 告警的限制与推荐做法

TradingView 的「Webhook URL」告警只会向你填写的 URL 发送 **POST + JSON 正文**，**不会**添加自定义请求头（例如 `X-TradingView-Signature`）。因此：

- 若**直接**把本系统的 `POST /webhook/tradingview` 填进 TradingView 的 Webhook URL，请求会因缺少签名而返回 **401**。
- 推荐两种用法：

### 方式 A：中间层转发（推荐用于生产）

1. TradingView 告警 → 发到你自己的**中转服务**（例如云函数、自建小服务、Zapier/Make/n8n 等）。
2. 中转服务用与 `.env` 中 **相同的 `TV_WEBHOOK_SECRET`** 对收到的**原始 body** 做 HMAC-SHA256，再 Base64，写入请求头 `X-TradingView-Signature`，然后 **原样转发** body 到本系统 `POST /webhook/tradingview`。
3. 本系统验签通过后，按信号做去重与执行。

签名算法（与 `docs/API.md` 一致）：

- 密钥：`TV_WEBHOOK_SECRET`（UTF-8）
- 消息：原始 HTTP body（bytes，不可先 parse 再序列化）
- 算法：HMAC-SHA256 → 结果 Base64 编码 → 放在 `X-TradingView-Signature`

### 方式 B：本地/测试用 curl 模拟

不经过 TradingView，在本地用 curl 直接带签名请求本系统，用于联调与测试：

```bash
# 将 YOUR_WEBHOOK_SECRET 换成 .env 里的 TV_WEBHOOK_SECRET
BODY='{"symbol":"BTCUSDT","action":"buy","strategy_id":"MOCK_STRATEGY_V1","timestamp":"2026-02-13T08:00:00Z"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "YOUR_WEBHOOK_SECRET" -binary | base64)
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -H "X-TradingView-Signature: $SIG" \
  -d "$BODY"
```

成功会返回 `{"status":"accepted","decision_id":"...","signal_id":"..."}`，Dashboard 的决策/执行列表会陆续有数据。

---

## 三、配置与策略 ID

1. **`.env`**  
   必须配置 `TV_WEBHOOK_SECRET`，与签名时使用的密钥一致。

2. **策略 ID**  
   请求体里的 `strategy_id`（或 `strategy`）必须在系统策略配置中存在，否则会返回 422（例如 `STRATEGY_NOT_FOUND`）。  
   若使用示例配置，策略 ID 为 `MOCK_STRATEGY_V1`（见 `config/config.example.yaml` 中 `strategy.strategy_id`）。部署时按你的策略名在配置中增加对应项。

3. **本地开发时 TradingView 无法访问 localhost**  
   需要把本系统暴露到公网再填到 TradingView 的 Webhook URL，例如：
   - 用 **ngrok**：`ngrok http 8000`，把生成的 `https://xxx.ngrok.io/webhook/tradingview` 填到 TradingView；
   - 或先把应用部署到有公网 IP/域名的服务器，再在 TradingView 里填该服务器的 `https://域名:8000/webhook/tradingview`。

---

## 四、TradingView 告警里如何配置（传入本系统）

当使用**中转服务**（方式 A）时，在 TradingView 告警里这样配置即可把信号传入本系统。

### 4.1 告警创建与 Webhook URL

1. 在图表上点击 **告警（Alerts）** → 新建告警。
2. **条件**：选你的策略（如「Strategy › 订单成交」）或指标条件。
3. **通知**：勾选 **「Webhook URL」**，在输入框填写**中转服务的地址**（例如 `https://你的中转域名/forward`），**不要**直接填本系统的 `.../webhook/tradingview`（会 401，见第二节）。
4. **消息**：在「消息」框中填写下面 4.2 的 JSON；TradingView 会把占位符替换成当前触发的值后，整段作为 POST body 发给该 URL。

### 4.2 消息体（JSON）必填字段与占位符

本系统要求 body 里包含：`symbol`/`ticker`、`side`/`action`、`timestamp`/`bar_time`/`time`、`strategy_id`/`strategy`。推荐在 TradingView 消息里这样写（使用 TradingView 占位符）：

```json
{
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "strategy_id": "MOCK_STRATEGY_V1",
  "timestamp": "{{timenow}}",
  "timeframe": "{{interval}}"
}
```

**常用占位符**（TradingView 会在发送前替换）：

| 占位符 | 含义 | 示例值 |
|--------|------|--------|
| `{{ticker}}` | 当前品种 | `BTCUSDT` |
| `{{strategy.order.action}}` | 策略订单动作（仅策略告警） | `buy` / `sell` |
| `{{interval}}` | 周期 | `60`、`1D` 等 |
| `{{timenow}}` | 当前时间（ISO 或 Unix，依 TV 版本） | 需能解析为时间；若本系统报错可改用 `{{time}}` 或自建格式 |

- 若告警来自**指标/条件**而非策略，没有 `{{strategy.order.action}}`，可写死 `"action": "buy"` 或 `"sell"`，或用指标值构造。
- `strategy_id` 必须与本系统配置中的策略 ID 一致（示例为 `MOCK_STRATEGY_V1`）。
- `timestamp`：本系统支持 ISO 字符串或 Unix 秒数。若 `{{timenow}}` 解析失败，可在中转里把收到的时间转成 ISO 或 Unix 再写入 body 后转发。

### 4.3 数据流小结

```
TradingView 告警触发
  → POST 到你填的「Webhook URL」（中转），body = 上面 JSON（占位符已替换）
  → 中转用 TV_WEBHOOK_SECRET 对 body 算 HMAC-SHA256，Base64 后加 X-TradingView-Signature
  → 中转 POST 到本系统 https://你的本系统/webhook/tradingview，原样 body + 签名头
  → 本系统验签、解析、去重、落库并执行，Dashboard 可见决策/成交
```

---

## 五、用自带脚本获取中转 URL（推荐先试）

项目里自带一个**仅用 Python 标准库**的中转脚本，运行后得到一个本地地址，再用 **ngrok** 暴露到公网，即可在 TradingView 里填这个公网 URL 作为 Webhook URL。

### 5.1 步骤

1. **确保本系统已启动**（例如 `uvicorn src.app.main:app --host 0.0.0.0 --port 8000`），且 `.env` 中已配置 `TV_WEBHOOK_SECRET`。

2. **设置环境变量并启动中转**（在项目根目录）：
   ```bash
   export TV_WEBHOOK_SECRET="你的密钥"   # 与 .env 中一致
   export RELAY_TARGET_URL="http://localhost:8000/webhook/tradingview"  # 可选，默认即此
   python scripts/relay_tradingview_webhook.py
   ```
   脚本会监听 **9000 端口**，本地中转 URL 为：**`http://localhost:9000/webhook`**。

3. **用 ngrok 暴露 9000 端口**（另开终端）：
   ```bash
   ngrok http 9000
   ```
   会得到类似 `https://a1b2c3d4.ngrok-free.app` 的地址。

4. **在 TradingView 告警里填的 Webhook URL**：
   ```
   https://a1b2c3d4.ngrok-free.app/webhook
   ```
   （把 `a1b2c3d4.ngrok-free.app` 换成你终端里显示的 ngrok 域名。）

5. 告警触发时：TradingView → 你的 ngrok 地址 → 本机中转脚本（加签名）→ 本系统 `http://localhost:8000/webhook/tradingview`。

### 5.2 环境变量说明

| 变量 | 必填 | 说明 |
|------|------|------|
| `TV_WEBHOOK_SECRET` | 是 | 与 `.env` 中一致，用于计算签名。 |
| `RELAY_TARGET_URL` | 否 | 本系统 Webhook 地址，默认 `http://localhost:8000/webhook/tradingview`。 |
| `RELAY_PORT` | 否 | 中转监听端口，默认 `9000`。 |

### 5.3 其他获取中转 URL 的方式

- **Zapier / Make (Integromat) / n8n**：创建「Webhook 触发」→ 收到请求后用「Code」或「HTTP 请求」步骤，按本文档的算法对 body 算签名并带上 `X-TradingView-Signature` 请求本系统。平台会给你一个固定的 Webhook URL，把该 URL 填进 TradingView 即可。
- **自建服务器 / 云函数**：在你有公网 IP 或域名的机器上部署一个同样逻辑的小服务（接收 POST → 签名 → 转发），该服务的公网 URL 即 TradingView 里填的地址。

---

## 六、相关文档

- **验签与 curl 示例**：`docs/API.md`  
- **部署与 Webhook 401 排查**：`docs/DEPLOYMENT.md`
