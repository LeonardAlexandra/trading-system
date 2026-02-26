# Phase1.2 B2 模块证据包

**模块编号**: B2  
**模块名称**: 最小 Dashboard 页面（TDASH-2）  
**模块目标**: 实现一个最小可访问的单页 Dashboard，用于展示最近决策/执行/成交、汇总（笔数/盈亏）与健康状态；页面只消费既定后端 API，不在前端计算任何业务指标。

---

## 【A】变更文件清单

| 类型 | 文件路径 | 用途 |
|------|----------|------|
| 新增 | `src/app/routers/dashboard_page.py` | B2 单页：GET /dashboard 返回 HTML，四块展示决策列表、执行/成交列表、汇总、健康状态；仅调用 4 个 API（decisions、executions、summary、health/summary） |
| 修改 | `src/app/main.py` | 注册 dashboard_page 路由（include_router(dashboard_page.router)） |
| 新增 | `docs/runlogs/b2_dashboard_curl.txt` | 实跑 curl 输出 |
| 新增 | `docs/Phase1.2_B2_模块证据包.md` | 本证据包 |

未修改 B1/C5 任何 API；未新增数据库迁移、表、字段。

---

## 【B】页面实现代码全文

**文件**: `src/app/routers/dashboard_page.py`

（以下为完整内容，与仓库一致。）

```python
"""
Phase1.2 B2：最小 Dashboard 单页（TDASH-2）

仅消费 GET /api/dashboard/* 与 GET /api/health/summary，不计算任何业务指标。
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard-page"])


def _dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dashboard</title>
  <style>
    body { font-family: sans-serif; margin: 1rem; }
    section { margin: 1rem 0; border: 1px solid #ccc; padding: 0.5rem; }
    section h2 { margin-top: 0; }
    .error { color: #c00; }
    table { border-collapse: collapse; }
    th, td { border: 1px solid #999; padding: 4px 8px; text-align: left; }
    pre { overflow: auto; max-height: 200px; font-size: 12px; }
  </style>
</head>
<body>
  <h1>Dashboard</h1>

  <section id="decisions">
    <h2>决策列表</h2>
    <div id="decisions-content">加载中…</div>
  </section>

  <section id="executions">
    <h2>执行/成交列表</h2>
    <div id="executions-content">加载中…</div>
  </section>

  <section id="summary">
    <h2>汇总</h2>
    <div id="summary-content">加载中…</div>
  </section>

  <section id="health">
    <h2>健康状态</h2>
    <div id="health-content">加载中…</div>
  </section>

  <script>
    function el(id) { return document.getElementById(id); }
    function showError(containerId, msg) {
      var el = document.getElementById(containerId);
      if (el) { el.innerHTML = '<span class="error">' + (msg || '加载失败') + '</span>'; }
    }
    function renderDecisions(data) {
      var c = el('decisions-content');
      if (!c) return;
      if (!Array.isArray(data)) { c.innerHTML = '<pre>' + JSON.stringify(data) + '</pre>'; return; }
      if (data.length === 0) { c.textContent = '（无数据）'; return; }
      var cols = ['decision_id','strategy_id','symbol','side','created_at'];
      var html = '<table><tr>' + cols.map(function(k){ return '<th>'+k+'</th>'; }).join('') + '</tr>';
      data.forEach(function(row){
        html += '<tr>' + cols.map(function(k){ return '<td>' + (row[k] != null ? String(row[k]) : '') + '</td>'; }).join('') + '</tr>';
      });
      html += '</table>';
      c.innerHTML = html;
    }
    function renderExecutions(data) {
      var c = el('executions-content');
      if (!c) return;
      if (!Array.isArray(data)) { c.innerHTML = '<pre>' + JSON.stringify(data) + '</pre>'; return; }
      if (data.length === 0) { c.textContent = '（无数据）'; return; }
      var cols = ['decision_id','symbol','side','quantity','price','realized_pnl','created_at'];
      var html = '<table><tr>' + cols.map(function(k){ return '<th>'+k+'</th>'; }).join('') + '</tr>';
      data.forEach(function(row){
        html += '<tr>' + cols.map(function(k){ return '<td>' + (row[k] != null ? String(row[k]) : '') + '</td>'; }).join('') + '</tr>';
      });
      html += '</table>';
      c.innerHTML = html;
    }
    function renderSummary(data) {
      var c = el('summary-content');
      if (!c) return;
      if (!Array.isArray(data)) { c.innerHTML = '<pre>' + JSON.stringify(data) + '</pre>'; return; }
      if (data.length === 0) { c.textContent = '（无数据）'; return; }
      var cols = ['group_key','trade_count','pnl_sum'];
      var html = '<table><tr>' + cols.map(function(k){ return '<th>'+k+'</th>'; }).join('') + '</tr>';
      data.forEach(function(row){
        html += '<tr>' + cols.map(function(k){ return '<td>' + (row[k] != null ? String(row[k]) : '') + '</td>'; }).join('') + '</tr>';
      });
      html += '</table>';
      c.innerHTML = html;
    }
    function renderHealth(data) {
      var c = el('health-content');
      if (!c) return;
      if (typeof data !== 'object') { c.innerHTML = '<pre>' + JSON.stringify(data) + '</pre>'; return; }
      c.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
    }
    fetch('/api/dashboard/decisions?limit=100').then(function(r){ return r.ok ? r.json() : r.text().then(function(t){ throw new Error(t); }); })
      .then(renderDecisions).catch(function(e){ showError('decisions-content', '加载失败: ' + (e.message || e)); });
    fetch('/api/dashboard/executions?limit=100').then(function(r){ return r.ok ? r.json() : r.text().then(function(t){ throw new Error(t); }); })
      .then(renderExecutions).catch(function(e){ showError('executions-content', '加载失败: ' + (e.message || e)); });
    fetch('/api/dashboard/summary').then(function(r){ return r.ok ? r.json() : r.text().then(function(t){ throw new Error(t); }); })
      .then(renderSummary).catch(function(e){ showError('summary-content', '加载失败: ' + (e.message || e)); });
    fetch('/api/health/summary').then(function(r){ return r.ok ? r.json() : r.text().then(function(t){ throw new Error(t); }); })
      .then(renderHealth).catch(function(e){ showError('health-content', '加载失败: ' + (e.message || e)); });
  </script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard_page():
    """
    GET /dashboard：最小 Dashboard 单页，展示决策列表、执行/成交列表、汇总、健康状态。
    仅调用 /api/dashboard/decisions、executions、summary 与 /api/health/summary。
    """
    return HTMLResponse(content=_dashboard_html())
```

---

## 【C】调用 API 列表与对应展示字段映射

| 页面模块 | 调用 API | 展示字段（与 API 响应一致，无前端计算） |
|----------|----------|----------------------------------------|
| 决策列表 | GET /api/dashboard/decisions?limit=100 | decision_id, strategy_id, symbol, side, created_at（表格逐行展示） |
| 执行/成交列表 | GET /api/dashboard/executions?limit=100 | decision_id, symbol, side, quantity, price, realized_pnl, created_at（表格逐行展示） |
| 汇总 | GET /api/dashboard/summary | group_key, trade_count, pnl_sum（表格逐行展示；完全来自 API，无重算） |
| 健康状态 | GET /api/health/summary | overall_ok, metrics, recent_alerts, recent_errors（整段 JSON 原样展示，字段不改名） |

允许列表中的 GET /api/dashboard/recent 本实现未调用（四块布局已满足；仅用上述 4 个 API）。未调用允许列表之外的任何接口。

---

## 【D】可复现实跑步骤（含访问 URL/路由、启动命令）

1. **启动应用**（需已配置数据库等，与 B1/C5 一致）：
   ```bash
   cd /Users/zhangkuo/TradingView\ Indicator/trading_system
   python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8000
   ```
2. **访问 Dashboard 页面**：浏览器打开 **http://127.0.0.1:8000/dashboard**（或 http://localhost:8000/dashboard）。
3. **预期**：页面返回 HTTP 200，出现四个区块标题「决策列表」「执行/成交列表」「汇总」「健康状态」；各块内容由对应 API 填充，API 失败时该块显示「加载失败: …」，不影响其他块。

**路由/入口**：GET `/dashboard`，由 `src.app.routers.dashboard_page.get_dashboard_page` 处理，无前缀，即访问路径为 **/dashboard**。

---

## 【E】验证输出（等价可验证证据 + API 响应对照）

**实际执行命令与输出**（见 `docs/runlogs/b2_dashboard_curl.txt`）：

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/dashboard
# 输出: 200

curl -s http://127.0.0.1:8000/dashboard | head -c 700
# 输出: <!DOCTYPE html>...<h2>决策列表</h2>...<h2>执行/成交列表</h2>...<h2>汇总</h2>...<h2>健康状态</h2>...
```

**与 API 响应对照**：汇总块展示内容即 GET /api/dashboard/summary 的 JSON（例如无数据时为 `[]`，页面显示「（无数据）」）；健康块展示内容即 GET /api/health/summary 的 JSON（overall_ok、metrics、recent_alerts、recent_errors 原样）。列表块为 decisions/executions 数组的表格化展示，字段与 B1 定义一致，无前端计算。

---

## 【F】验收标准逐条对照（YES/NO + 证据）

| 验收口径 | 结果 | 证据 |
|----------|------|------|
| 页面可访问且展示四块：决策列表、执行/成交列表、汇总、健康状态 | YES | GET /dashboard 返回 200；HTML 含四个 section（#decisions、#executions、#summary、#health）及对应 h2 标题；runlogs 见 b2_dashboard_curl.txt。 |
| 页面展示数据与直接调用对应 API 的响应一致（可对比验证） | YES | 列表与汇总为 API 数组/对象的表格或 JSON 展示，无重算；汇总来自 /api/dashboard/summary，健康来自 /api/health/summary；见【C】与【B】渲染逻辑。 |
| 汇总数据完全来自 /api/dashboard/summary，前端无业务指标计算逻辑 | YES | renderSummary 仅将 API 返回数组按 group_key、trade_count、pnl_sum 制表展示；无 sum/count 等计算，见【B】。 |
| 健康数据完全来自 /api/health/summary，展示字段与响应一致 | YES | renderHealth 将整段 JSON 以 JSON.stringify(data, null, 2) 展示，字段未改名、未改口径，见【B】。 |
| 页面仅调用允许列表中的 5 个 API | YES | 实际调用 4 个：decisions、executions、summary、health/summary；未调用 recent；未调用允许列表外任何接口，见【B】script 中 fetch。 |

---

## 验收结论

是否满足模块目标：**是**。已实现最小可访问单页 Dashboard（GET /dashboard），展示决策列表、执行/成交列表、汇总、健康状态四块；数据仅来自既定 4 个 API，前端无任何业务指标计算；健康块与 /api/health/summary 响应一致；未修改 B1/C5 API，未新增 DB 迁移/表/字段。

**实际执行的命令**（逐条）：
- `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/dashboard` → 200
- `curl -s http://127.0.0.1:8000/dashboard | head -c 700` → 见 docs/runlogs/b2_dashboard_curl.txt
- `curl -s http://127.0.0.1:8000/api/dashboard/summary` → []（与汇总块一致）

**证据包文件路径**：`docs/Phase1.2_B2_模块证据包.md`

**文档结束**
