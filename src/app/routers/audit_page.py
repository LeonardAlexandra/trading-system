"""
Phase1.2 C8：审计查询 Web 页面。与 CLI 功能对齐，调用 /api/audit/*（同一后端）。
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["audit-page"])


def _audit_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>审计查询</title>
  <style>
    body { font-family: sans-serif; margin: 1rem; }
    section { margin: 1rem 0; border: 1px solid #ccc; padding: 0.5rem; }
    section h2 { margin-top: 0; }
    .error { color: #c00; }
    table { border-collapse: collapse; }
    th, td { border: 1px solid #999; padding: 4px 8px; text-align: left; }
    pre { overflow: auto; max-height: 300px; font-size: 12px; }
    input, select, button { margin: 2px; }
  </style>
</head>
<body>
  <h1>审计查询（C8）</h1>

  <section id="recent-logs">
    <h2>1. 最近 N 条 ERROR/AUDIT 日志</h2>
    <label>条数 <input type="number" id="recent-n" value="20" min="1" max="100"></label>
    <label>level <select id="recent-level"><option value="">ERROR,AUDIT</option><option value="ERROR">ERROR</option><option value="AUDIT">AUDIT</option></select></label>
    <button id="btn-recent">查询</button>
    <div id="recent-content">（点击查询）</div>
  </section>

  <section id="query-logs">
    <h2>2. 按时间/组件/level 分页查日志</h2>
    <label>from <input type="datetime-local" id="logs-from"></label>
    <label>to <input type="datetime-local" id="logs-to"></label>
    <label>component <input type="text" id="logs-component" placeholder="可选"></label>
    <label>level <input type="text" id="logs-level" placeholder="可选"></label>
    <label>limit <input type="number" id="logs-limit" value="100" min="1" max="1000"></label>
    <label>offset <input type="number" id="logs-offset" value="0" min="0"></label>
    <button id="btn-logs">查询</button>
    <div id="logs-content">（点击查询）</div>
  </section>

  <section id="traces">
    <h2>3. list_traces 回放（含 trace_status / missing_nodes）</h2>
    <label>from <input type="datetime-local" id="traces-from" required></label>
    <label>to <input type="datetime-local" id="traces-to" required></label>
    <label>strategy_id <input type="text" id="traces-strategy" placeholder="可选"></label>
    <label>limit <input type="number" id="traces-limit" value="100" min="1" max="100"></label>
    <label>offset <input type="number" id="traces-offset" value="0" min="0"></label>
    <button id="btn-traces">查询</button>
    <div id="traces-content">（点击查询）</div>
  </section>

  <script>
    function el(id) { return document.getElementById(id); }
    
    // 强制使用浏览器内置安全机制：textContent 赋值
    // 满足 Strong Constraints: 必须使用框架内置/成熟转义机制
    function setContent(id, content) { 
      var c = el(id); 
      if (!c) return;
      c.innerHTML = ''; // 清空
      if (typeof content === 'string') {
        // 如果是纯文本，安全起见也用 textContent
        var p = document.createElement('p');
        p.textContent = content;
        c.appendChild(p);
      } else {
        c.appendChild(content);
      }
    }

    function showError(id, msg) { 
      var c = el(id);
      if (!c) return;
      c.innerHTML = '';
      var span = document.createElement('span');
      span.className = 'error';
      span.textContent = msg || '加载失败';
      c.appendChild(span);
    }

    function isoFromLocal(el) { if (!el.value) return null; return new Date(el.value).toISOString(); }

    // 通用安全表格渲染器：基于 DOM API 和 textContent
    function renderSafeTable(cols, items, valueTransform) {
      if (!Array.isArray(items) || items.length === 0) {
        var p = document.createElement('p');
        p.textContent = '（无数据）';
        return p;
      }
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
        var r = tbody.insertRow();
        cols.forEach(function(k) {
          var td = r.insertCell();
          var val = row[k];
          if (valueTransform) val = valueTransform(k, val);
          // 核心安全点：使用 textContent 自动转义所有可变字符串
          td.textContent = (val != null ? String(val) : '');
        });
      });
      return table;
    }

    function renderLogRows(items) {
      var cols = ['id','created_at','component','level','message','event_type'];
      return renderSafeTable(cols, items);
    }

    function renderTraceRows(items) {
      var cols = ['decision_id','trace_status','missing_nodes','strategy_id','symbol','created_at'];
      var container = document.createDocumentFragment();
      var table = renderSafeTable(cols, items, function(k, v) {
        if (k === 'missing_nodes' && Array.isArray(v)) return v.join(', ');
        return v;
      });
      container.appendChild(table);
      var p = document.createElement('p');
      p.textContent = 'count=' + items.length;
      container.appendChild(p);
      return container;
    }

    el('btn-recent').onclick = function(){
      var n = parseInt(el('recent-n').value, 10) || 20;
      var level = el('recent-level').value;
      var url = '/api/audit/logs/recent?n=' + n + (level ? '&level=' + encodeURIComponent(level) : '');
      fetch(url).then(function(r){ return r.ok ? r.json() : r.text().then(function(t){ throw new Error(t); }); })
        .then(function(data){ setContent('recent-content', renderLogRows(data.items || [])); })
        .catch(function(e){ showError('recent-content', e.message); });
    };

    el('btn-logs').onclick = function(){
      var from_ = isoFromLocal(el('logs-from'));
      var to_ = isoFromLocal(el('logs-to'));
      var url = '/api/audit/logs?limit=' + (el('logs-limit').value || 100) + '&offset=' + (el('logs-offset').value || 0);
      if (from_) url += '&from=' + encodeURIComponent(from_);
      if (to_) url += '&to=' + encodeURIComponent(to_);
      if (el('logs-component').value) url += '&component=' + encodeURIComponent(el('logs-component').value);
      if (el('logs-level').value) url += '&level=' + encodeURIComponent(el('logs-level').value);
      fetch(url).then(function(r){ return r.ok ? r.json() : r.text().then(function(t){ throw new Error(t); }); })
        .then(function(data){ setContent('logs-content', renderLogRows(data.items || [])); })
        .catch(function(e){ showError('logs-content', e.message); });
    };

    el('btn-traces').onclick = function(){
      var from_ = isoFromLocal(el('traces-from'));
      var to_ = isoFromLocal(el('traces-to'));
      if (!from_ || !to_) { showError('traces-content', '请填写 from 与 to'); return; }
      var url = '/api/audit/traces?from=' + encodeURIComponent(from_) + '&to=' + encodeURIComponent(to_);
      url += '&limit=' + (el('traces-limit').value || 100) + '&offset=' + (el('traces-offset').value || 0);
      if (el('traces-strategy').value) url += '&strategy_id=' + encodeURIComponent(el('traces-strategy').value);
      fetch(url).then(function(r){ return r.ok ? r.json() : r.text().then(function(t){ throw new Error(t); }); })
        .then(function(data){ setContent('traces-content', renderTraceRows(data.items || [])); })
        .catch(function(e){ showError('traces-content', e.message); });
    };

    (function setDefaultTracesRange(){
      var now = new Date();
      var weekAgo = new Date(now.getTime() - 7*24*60*60*1000);
      function toLocal(d){ return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')+'T'+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0'); }
      el('traces-from').value = toLocal(weekAgo);
      el('traces-to').value = toLocal(now);
    })();
  </script>
</body>
</html>
"""


@router.get("/audit", response_class=HTMLResponse)
async def get_audit_page():
    """
    GET /audit：审计查询页面。使用浏览器内置 DOM API (textContent) 实现强制安全渲染。
    """
    return HTMLResponse(content=_audit_html())
