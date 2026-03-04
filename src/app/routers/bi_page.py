"""
Phase 2.2 B3：BI 只读展示页面

集成 A1、A2、B1、B2 的只读 API，无任何状态变更按钮或操作。

【只读边界（宪法级约束）】
- 页面不提供「触发评估」「执行回滚」「通过门禁」「应用参数」等任何会改变系统状态的按钮或调用。
- 数据仅通过调用 /api/bi/* 只读 API 获取，不直连业务表，不重算指标。
- 无任何写操作、无状态变更入口。

【展示内容】
- A1: 完整统计与资金/权益曲线（/api/bi/stats、/api/bi/equity_curve）
- A2: 决策过程列表（/api/bi/decision_flow/list），含 PARTIAL/NOT_FOUND 展示
- B1: 版本历史（/api/bi/version_history）、评估历史（/api/bi/evaluation_history）
- B2: 门禁/回滚/停用历史（/api/bi/release_audit）
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["bi-page"])


def _bi_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BI 只读展示（Phase 2.2）</title>
  <style>
    body { font-family: sans-serif; margin: 1rem; background: #f8f8f8; }
    h1 { color: #333; }
    .readonly-badge { display: inline-block; background: #2a7; color: #fff; border-radius: 4px; padding: 2px 8px; font-size: 0.85em; margin-left: 8px; }
    nav { margin: 0.5rem 0 1rem; }
    nav a { margin-right: 1rem; color: #0077cc; text-decoration: none; }
    nav a:hover { text-decoration: underline; }
    section { margin: 1rem 0; border: 1px solid #ccc; padding: 0.75rem; background: #fff; border-radius: 4px; }
    section h2 { margin-top: 0; font-size: 1.1em; color: #444; }
    .filter-bar { margin-bottom: 0.5rem; }
    .filter-bar label { margin-right: 0.5rem; font-size: 0.9em; }
    .filter-bar input, .filter-bar select { padding: 2px 4px; font-size: 0.9em; }
    button.query-btn { padding: 3px 10px; font-size: 0.9em; cursor: pointer; }
    .error { color: #c00; }
    .info { color: #555; font-size: 0.85em; }
    table { border-collapse: collapse; font-size: 0.88em; }
    th, td { border: 1px solid #bbb; padding: 4px 8px; text-align: left; vertical-align: top; }
    th { background: #f0f0f0; }
    pre { overflow: auto; max-height: 180px; font-size: 11px; background: #f4f4f4; padding: 4px; }
    .status-partial { color: #b60; font-weight: bold; }
    .status-not-found { color: #c00; font-weight: bold; }
    .status-complete { color: #2a7; }
    .passed-true { color: #2a7; }
    .passed-false { color: #c00; }
  </style>
</head>
<body>
  <h1>BI 只读展示 <span class="readonly-badge">只读</span></h1>
  <p class="info">本页面为纯只读展示，不提供任何状态变更操作。数据来自 Phase 1.2/2.0/2.1 只读 API。</p>

  <nav>
    <a href="#stats">统计</a>
    <a href="#equity">权益曲线</a>
    <a href="#decision">决策链路</a>
    <a href="#version">版本历史</a>
    <a href="#evaluation">评估历史</a>
    <a href="#audit">门禁/回滚历史</a>
  </nav>

  <!-- A1: 完整统计 -->
  <section id="stats">
    <h2>A1 完整交易统计</h2>
    <div class="filter-bar">
      <label>strategy_id <input type="text" id="stats-strategy" placeholder="可选"></label>
      <label>from <input type="datetime-local" id="stats-from"></label>
      <label>to <input type="datetime-local" id="stats-to"></label>
      <button class="query-btn" id="btn-stats">查询</button>
    </div>
    <div id="stats-content">（点击查询）</div>
  </section>

  <!-- A1: 权益曲线 -->
  <section id="equity">
    <h2>A1 权益曲线</h2>
    <div class="filter-bar">
      <label>strategy_id <input type="text" id="equity-strategy" placeholder="可选"></label>
      <label>from <input type="datetime-local" id="equity-from"></label>
      <label>to <input type="datetime-local" id="equity-to"></label>
      <button class="query-btn" id="btn-equity">查询</button>
    </div>
    <div id="equity-content">（点击查询）</div>
  </section>

  <!-- A2: 决策链路列表 -->
  <section id="decision">
    <h2>A2 决策链路列表（含 PARTIAL/NOT_FOUND 状态）</h2>
    <div class="filter-bar">
      <label>strategy_id <input type="text" id="decision-strategy" placeholder="可选"></label>
      <label>from <input type="datetime-local" id="decision-from"></label>
      <label>to <input type="datetime-local" id="decision-to"></label>
      <label>limit <input type="number" id="decision-limit" value="50" min="1" max="200"></label>
      <button class="query-btn" id="btn-decision">查询</button>
    </div>
    <div id="decision-content">（点击查询）</div>
  </section>

  <!-- B1: 版本历史 -->
  <section id="version">
    <h2>B1 参数版本历史</h2>
    <div class="filter-bar">
      <label>strategy_id <input type="text" id="version-strategy" placeholder="可选"></label>
      <label>limit <input type="number" id="version-limit" value="50" min="1" max="200"></label>
      <button class="query-btn" id="btn-version">查询</button>
    </div>
    <div id="version-content">（点击查询）</div>
  </section>

  <!-- B1: 评估历史 -->
  <section id="evaluation">
    <h2>B1 评估报告历史</h2>
    <div class="filter-bar">
      <label>strategy_id <input type="text" id="eval-strategy" placeholder="可选"></label>
      <label>from <input type="datetime-local" id="eval-from"></label>
      <label>to <input type="datetime-local" id="eval-to"></label>
      <label>limit <input type="number" id="eval-limit" value="50" min="1" max="200"></label>
      <button class="query-btn" id="btn-eval">查询</button>
    </div>
    <div id="eval-content">（点击查询）</div>
  </section>

  <!-- B2: 门禁/回滚/停用历史 -->
  <section id="audit">
    <h2>B2 门禁/回滚/自动停用历史</h2>
    <div class="filter-bar">
      <label>strategy_id <input type="text" id="audit-strategy" placeholder="可选"></label>
      <label>from <input type="datetime-local" id="audit-from"></label>
      <label>to <input type="datetime-local" id="audit-to"></label>
      <label>limit <input type="number" id="audit-limit" value="50" min="1" max="200"></label>
      <button class="query-btn" id="btn-audit">查询</button>
    </div>
    <div id="audit-content">（点击查询）</div>
  </section>

  <script>
    // ─── 工具函数 ───────────────────────────────────────────────
    function el(id) { return document.getElementById(id); }

    function showError(containerId, msg) {
      var c = el(containerId);
      if (!c) return;
      c.innerHTML = '';
      var span = document.createElement('span');
      span.className = 'error';
      span.textContent = '错误: ' + (msg || '加载失败');
      c.appendChild(span);
    }

    function showEmpty(containerId) {
      var c = el(containerId);
      if (!c) return;
      c.innerHTML = '';
      var p = document.createElement('p');
      p.className = 'info';
      p.textContent = '（无数据）';
      c.appendChild(p);
    }

    // 安全渲染：全程使用 textContent，避免 XSS
    function renderTable(cols, items, cellTransform) {
      if (!Array.isArray(items) || items.length === 0) return null;
      var table = document.createElement('table');
      var thead = table.createTHead();
      var hRow = thead.insertRow();
      cols.forEach(function(k) {
        var th = document.createElement('th');
        th.textContent = k;
        hRow.appendChild(th);
      });
      var tbody = table.createTBody();
      items.forEach(function(row) {
        var tr = tbody.insertRow();
        cols.forEach(function(k) {
          var td = tr.insertCell();
          var val = row[k];
          if (cellTransform) {
            var result = cellTransform(td, k, val, row);
            if (result !== undefined) val = result;
          }
          if (!td.hasChildNodes()) {
            td.textContent = (val != null ? String(val) : '');
          }
        });
      });
      return table;
    }

    function isoFromLocal(input) {
      if (!input.value) return null;
      return new Date(input.value).toISOString();
    }

    function buildUrl(base, params) {
      var parts = [];
      Object.keys(params).forEach(function(k) {
        if (params[k] != null && params[k] !== '') {
          parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
        }
      });
      return parts.length ? base + '?' + parts.join('&') : base;
    }

    function setResult(containerId, element, count) {
      var c = el(containerId);
      if (!c) return;
      c.innerHTML = '';
      if (element) c.appendChild(element);
      if (count !== undefined) {
        var p = document.createElement('p');
        p.className = 'info';
        p.textContent = '共 ' + count + ' 条';
        c.appendChild(p);
      }
    }

    // ─── A1: 统计 ────────────────────────────────────────────────
    el('btn-stats').onclick = function() {
      var url = buildUrl('/api/bi/stats', {
        strategy_id: el('stats-strategy').value,
        from: isoFromLocal(el('stats-from')),
        to: isoFromLocal(el('stats-to'))
      });
      fetch(url)
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.error || JSON.stringify(e)); }); })
        .then(function(data) {
          var cols = ['id','strategy_id','period_start','period_end','trade_count','win_rate','realized_pnl','max_drawdown','avg_holding_time_sec'];
          var table = renderTable(cols, data.items || []);
          if (!table) { showEmpty('stats-content'); return; }
          setResult('stats-content', table, data.count);
        })
        .catch(function(e) { showError('stats-content', e.message); });
    };

    // ─── A1: 权益曲线 ────────────────────────────────────────────
    el('btn-equity').onclick = function() {
      var url = buildUrl('/api/bi/equity_curve', {
        strategy_id: el('equity-strategy').value,
        from: isoFromLocal(el('equity-from')),
        to: isoFromLocal(el('equity-to'))
      });
      fetch(url)
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.error || JSON.stringify(e)); }); })
        .then(function(data) {
          var cols = ['trade_id','strategy_id','executed_at','realized_pnl','cumulative_pnl'];
          var table = renderTable(cols, data.points || []);
          if (!table) { showEmpty('equity-content'); return; }
          setResult('equity-content', table, data.count);
        })
        .catch(function(e) { showError('equity-content', e.message); });
    };

    // ─── A2: 决策链路列表 ────────────────────────────────────────
    el('btn-decision').onclick = function() {
      var url = buildUrl('/api/bi/decision_flow/list', {
        strategy_id: el('decision-strategy').value,
        from: isoFromLocal(el('decision-from')),
        to: isoFromLocal(el('decision-to')),
        limit: el('decision-limit').value
      });
      fetch(url)
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.error || JSON.stringify(e)); }); })
        .then(function(data) {
          var cols = ['decision_id','trace_status','missing_nodes','strategy_id','symbol','side','quantity','created_at'];
          var table = renderTable(cols, data.items || [], function(td, k, val, row) {
            if (k === 'trace_status') {
              td.textContent = val != null ? String(val) : '';
              if (val === 'PARTIAL') td.className = 'status-partial';
              else if (val === 'NOT_FOUND') td.className = 'status-not-found';
              else td.className = 'status-complete';
              return undefined;
            }
            if (k === 'missing_nodes' && Array.isArray(val)) {
              td.textContent = val.length ? val.join(', ') : '—';
              return undefined;
            }
          });
          if (!table) { showEmpty('decision-content'); return; }
          setResult('decision-content', table, data.count);
        })
        .catch(function(e) { showError('decision-content', e.message); });
    };

    // ─── B1: 版本历史 ────────────────────────────────────────────
    el('btn-version').onclick = function() {
      var url = buildUrl('/api/bi/version_history', {
        strategy_id: el('version-strategy').value,
        limit: el('version-limit').value
      });
      fetch(url)
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.error || JSON.stringify(e)); }); })
        .then(function(data) {
          var cols = ['param_version_id','strategy_id','strategy_version_id','release_state','created_at','updated_at'];
          var table = renderTable(cols, data.items || []);
          if (!table) { showEmpty('version-content'); return; }
          setResult('version-content', table, data.count);
        })
        .catch(function(e) { showError('version-content', e.message); });
    };

    // ─── B1: 评估历史 ────────────────────────────────────────────
    el('btn-eval').onclick = function() {
      var url = buildUrl('/api/bi/evaluation_history', {
        strategy_id: el('eval-strategy').value,
        from: isoFromLocal(el('eval-from')),
        to: isoFromLocal(el('eval-to')),
        limit: el('eval-limit').value
      });
      fetch(url)
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.error || JSON.stringify(e)); }); })
        .then(function(data) {
          var cols = ['id','strategy_id','evaluated_at','period_start','period_end','conclusion','param_version_id'];
          var table = renderTable(cols, data.items || []);
          if (!table) { showEmpty('eval-content'); return; }
          setResult('eval-content', table, data.count);
        })
        .catch(function(e) { showError('eval-content', e.message); });
    };

    // ─── B2: 门禁/回滚/停用历史 ──────────────────────────────────
    el('btn-audit').onclick = function() {
      var url = buildUrl('/api/bi/release_audit', {
        strategy_id: el('audit-strategy').value,
        from: isoFromLocal(el('audit-from')),
        to: isoFromLocal(el('audit-to')),
        limit: el('audit-limit').value
      });
      fetch(url)
        .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { throw new Error(e.error || JSON.stringify(e)); }); })
        .then(function(data) {
          var cols = ['id','strategy_id','param_version_id','action','gate_type','passed','has_operator','created_at'];
          var table = renderTable(cols, data.items || [], function(td, k, val) {
            if (k === 'passed') {
              td.textContent = val != null ? String(val) : '';
              td.className = val ? 'passed-true' : 'passed-false';
              return undefined;
            }
          });
          if (!table) { showEmpty('audit-content'); return; }
          setResult('audit-content', table, data.count);
        })
        .catch(function(e) { showError('audit-content', e.message); });
    };

    // 设置默认时间范围（近一年）
    (function setDefaultRange() {
      var now = new Date();
      var yearAgo = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
      function toLocal(d) {
        return d.getFullYear() + '-' +
          String(d.getMonth() + 1).padStart(2, '0') + '-' +
          String(d.getDate()).padStart(2, '0') + 'T' +
          String(d.getHours()).padStart(2, '0') + ':' +
          String(d.getMinutes()).padStart(2, '0');
      }
      var nowStr = toLocal(now);
      var yearAgoStr = toLocal(yearAgo);
      ['stats-from','equity-from','decision-from','eval-from','audit-from'].forEach(function(id) {
        el(id).value = yearAgoStr;
      });
      ['stats-to','equity-to','decision-to','eval-to','audit-to'].forEach(function(id) {
        el(id).value = nowStr;
      });
    })();
  </script>
</body>
</html>
"""


@router.get("/bi", response_class=HTMLResponse)
async def get_bi_page():
    """
    GET /bi：Phase 2.2 BI 只读展示页面。

    集成 A1（统计/权益曲线）、A2（决策链路）、B1（版本/评估历史）、B2（门禁/回滚历史）。
    仅消费 /api/bi/* 只读 API，不提供任何状态变更操作。
    """
    return HTMLResponse(content=_bi_html())
