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
