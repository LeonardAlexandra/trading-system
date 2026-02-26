# Phase1.2 B1 模块证据包

**模块编号**: B1  
**模块名称**: 最小 Dashboard 列表与汇总 API（TDASH-1）  
**模块目标**: 实现最小可用的 Dashboard 后端 API，提供决策列表、执行/成交列表、汇总统计与最近记录，仅消费 Phase1.2 已存在的数据与服务，为前端 Dashboard 提供只读数据接口。

---

## 封版修复说明（系统级封版标准）

- **修复 1（from/to 参数解析失败静默忽略）**  
  原 `_parse_iso_opt` 解析失败返回 `None`，导致过滤被悄悄取消。现改为 `_parse_iso_or_400(s, param_name)`：当 `from` 或 `to` 参数存在但不是合法 ISO8601（支持 Z / +00:00）时，抛出 `HTTPException(400, detail="invalid from"` 或 `"invalid to"`)。实现方式为保留 str 参数、解析失败时 `raise HTTPException(400, ...)`。  
  新增测试：`GET /api/dashboard/decisions?from=bad` → 400，detail 含 `invalid from`；`GET /api/dashboard/executions?to=bad` → 400，detail 含 `invalid to`。

- **修复 2（summary 无 trade 时返回伪造一行）**  
  原无 trade 时返回 `[{ group_key: "", trade_count: 0, pnl_sum: 0 }]`，口径不自洽。现改为：无 trade 数据时 `/summary` 返回空数组 `[]`。  
  同步修改测试 `test_dashboard_summary_no_trade_returns_zero`：断言 `resp.json() == []`。

---

## 【A】变更文件清单

| 类型 | 文件路径 | 用途 |
|------|----------|------|
| 新增 | `src/app/routers/dashboard.py` | B1 四个 GET 接口：decisions、executions、summary、recent；只读，数据来自 decision_snapshot、trade |
| 修改 | `src/app/main.py` | 注册 dashboard 路由（include_router(dashboard.router)） |
| 新增 | `tests/integration/test_phase12_b1_dashboard.py` | B1 验收测试：decisions/executions/summary/recent 200 与字段、summary 无 trade 返回 []、from/to 非法返回 400、limit 限制 |
| 新增 | `docs/runlogs/b1_pytest.txt` | pytest 原始输出 |
| 新增 | `docs/Phase1.2_B1_模块证据包.md` | 本证据包 |

未新增数据库迁移、表、字段。未修改 C1/C2/…/C6、health、resume、trace 等模块。

---

## 【B】核心实现代码全文

**文件**: `src/app/routers/dashboard.py`

（以下为完整内容，与仓库一致；含封版修复：from/to 非法返回 400、summary 无 trade 返回 []。）

```python
"""
Phase1.2 B1：最小 Dashboard 列表与汇总 API（TDASH-1）

仅消费 Phase1.2 已有数据（decision_snapshot、trade），只读，无副作用。
口径 D.7：trade_count = trade 表条数，pnl_sum = sum(realized_pnl)，无 trade 时 summary 返回 []。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db_session
from src.models.decision_snapshot import DecisionSnapshot
from src.models.trade import Trade
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository

DASHBOARD_LIST_MAX_LIMIT = 100
DASHBOARD_RECENT_DEFAULT_N = 20
DASHBOARD_RECENT_MAX_N = 100

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _parse_iso_or_400(s: Optional[str], param_name: str) -> Optional[datetime]:
    """解析 ISO8601（支持 Z / +00:00）；参数存在但非法时抛出 HTTP 400。"""
    if s is None or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid {param_name}")


def _decision_row_to_item(row: DecisionSnapshot) -> dict:
    dr = row.decision_result or {}
    return {
        "decision_id": row.decision_id,
        "strategy_id": row.strategy_id,
        "symbol": dr.get("symbol") if isinstance(dr, dict) else "",
        "side": dr.get("side") if isinstance(dr, dict) else "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/decisions")
async def get_dashboard_decisions(
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    strategy_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=DASHBOARD_LIST_MAX_LIMIT),
):
    """GET /api/dashboard/decisions?from=&to=&strategy_id=&limit=100"""
    from_dt = _parse_iso_or_400(from_ts, "from")
    to_dt = _parse_iso_or_400(to_ts, "to")
    async with get_db_session() as session:
        repo = DecisionSnapshotRepository(session)
        if strategy_id and strategy_id.strip():
            start = from_dt or datetime(2000, 1, 1, tzinfo=timezone.utc)
            end = to_dt or datetime.now(timezone.utc)
            rows = await repo.list_by_strategy_time(strategy_id.strip(), start, end, limit=limit, offset=0)
        else:
            stmt = select(DecisionSnapshot).order_by(DecisionSnapshot.created_at.desc()).limit(limit)
            if from_dt:
                stmt = stmt.where(DecisionSnapshot.created_at >= from_dt)
            if to_dt:
                stmt = stmt.where(DecisionSnapshot.created_at <= to_dt)
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
        return [_decision_row_to_item(r) for r in rows]


@router.get("/executions")
async def get_dashboard_executions(
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=DASHBOARD_LIST_MAX_LIMIT),
):
    """GET /api/dashboard/executions?from=&to=&limit=100"""
    from_dt = _parse_iso_or_400(from_ts, "from")
    to_dt = _parse_iso_or_400(to_ts, "to")
    async with get_db_session() as session:
        stmt = select(Trade).order_by(Trade.created_at.desc()).limit(limit)
        if from_dt:
            stmt = stmt.where(Trade.created_at >= from_dt)
        if to_dt:
            stmt = stmt.where(Trade.created_at <= to_dt)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        out = []
        for r in rows:
            out.append({
                "decision_id": r.decision_id,
                "symbol": r.symbol,
                "side": r.side,
                "quantity": float(r.quantity) if r.quantity is not None else 0,
                "price": float(r.price) if r.price is not None else 0,
                "realized_pnl": float(r.realized_pnl) if r.realized_pnl is not None else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return out


@router.get("/summary")
async def get_dashboard_summary(
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    group_by: str = Query("day", pattern="^(day|strategy)$"),
):
    """GET /api/dashboard/summary?from=&to=&group_by=day|strategy，无 trade 时返回 []。"""
    from_dt = _parse_iso_or_400(from_ts, "from")
    to_dt = _parse_iso_or_400(to_ts, "to")
    async with get_db_session() as session:
        if group_by == "strategy":
            group_col = Trade.strategy_id
        else:
            group_col = func.date(Trade.created_at)
        stmt = select(
            group_col.label("group_key"),
            func.count(Trade.trade_id).label("trade_count"),
            func.coalesce(func.sum(Trade.realized_pnl), 0).label("pnl_sum"),
        ).group_by(group_col)
        if from_dt:
            stmt = stmt.where(Trade.created_at >= from_dt)
        if to_dt:
            stmt = stmt.where(Trade.created_at <= to_dt)
        result = await session.execute(stmt)
        rows = result.all()
        out = []
        for r in rows:
            gk = r.group_key
            if hasattr(gk, "isoformat"):
                gk = gk.isoformat() if gk else ""
            out.append({
                "group_key": str(gk) if gk is not None else "",
                "trade_count": r.trade_count or 0,
                "pnl_sum": float(r.pnl_sum) if r.pnl_sum is not None else 0,
            })
        if not out:
            return []
        return out


@router.get("/recent")
async def get_dashboard_recent(
    n: int = Query(DASHBOARD_RECENT_DEFAULT_N, ge=1, le=DASHBOARD_RECENT_MAX_N),
):
    """GET /api/dashboard/recent?n=20 返回最近 n 条成交（trade 表）。"""
    async with get_db_session() as session:
        stmt = select(Trade).order_by(Trade.created_at.desc()).limit(n)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        out = []
        for r in rows:
            out.append({
                "decision_id": r.decision_id,
                "symbol": r.symbol,
                "side": r.side,
                "quantity": float(r.quantity) if r.quantity is not None else 0,
                "price": float(r.price) if r.price is not None else 0,
                "realized_pnl": float(r.realized_pnl) if r.realized_pnl is not None else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return out
```

---

## 【C】数据来源与汇总口径说明

- **decisions**：来自表 `decision_snapshot`。decision_id、strategy_id、created_at 取自列；symbol、side 取自列 `decision_result`（JSON）的键 symbol、side。可选查询参数 from、to（ISO 时间）、strategy_id、limit（默认 100，上限 100）。有 strategy_id 时使用 DecisionSnapshotRepository.list_by_strategy_time；否则 select(DecisionSnapshot) 按 created_at 过滤与 limit。
- **executions**：来自表 `trade`。字段 decision_id、symbol、side、quantity、price、realized_pnl、created_at 直接取自 trade 列。可选 from、to、limit（默认 100，上限 100）。
- **summary**：来自表 `trade`。group_by=day 时按 `date(created_at)` 分组；group_by=strategy 时按 strategy_id 分组。trade_count = 该组内 count(trade_id)；pnl_sum = 该组内 sum(realized_pnl)，无行时 coalesce 为 0。无任何 trade 时返回空数组 `[]`。风控拒绝、执行失败未写入 trade 表，故不计入 trade_count。
- **recent**：来自表 `trade`，按 created_at 倒序取最近 n 条（n 默认 20，上限 100）。返回结构与 executions 一致，即最近 n 条成交。

汇总口径（写死 D.7）：trade_count = trade 表记录数（按 group_by 聚合）；pnl_sum = trade.realized_pnl 之和；无 trade 时 summary 返回 []；风控拒绝、执行失败不计入 trade_count。

---

## 【D】测试用例或可复现实跑步骤

1. **test_dashboard_decisions_200_and_fields**：插入 1 条 decision_snapshot，请求 GET /api/dashboard/decisions?limit=10，断言 200 且每条含 decision_id、strategy_id、symbol、side、created_at。  
2. **test_dashboard_executions_200_and_fields**：插入 1 条 trade，请求 GET /api/dashboard/executions?limit=10，断言 200 且每条含 decision_id、symbol、side、quantity、price、realized_pnl、created_at。  
3. **test_dashboard_summary_no_trade_returns_zero**：空库下请求 GET /api/dashboard/summary?group_by=day，断言 200 且 `resp.json() == []`。  
4. **test_dashboard_decisions_invalid_from_400**：请求 GET /api/dashboard/decisions?from=bad，断言 400 且 detail 含 "invalid from"。  
5. **test_dashboard_executions_invalid_to_400**：请求 GET /api/dashboard/executions?to=bad，断言 400 且 detail 含 "invalid to"。  
6. **test_dashboard_summary_with_trade**：插入 1 条 trade（realized_pnl=100.5），请求 GET /api/dashboard/summary?group_by=strategy，断言存在一项 trade_count≥1 且 pnl_sum≈100.5。  
7. **test_dashboard_recent_200_and_limit**：请求 GET /api/dashboard/recent?n=5，断言 200 且列表长度 ≤5。  
8. **test_dashboard_decisions_limit_enforced**：请求 GET /api/dashboard/decisions?limit=3，断言返回条数 ≤3。

---

## 【E】测试命令与原始输出

**实际执行的命令：**

```bash
cd /Users/zhangkuo/TradingView\ Indicator/trading_system
python -m pytest tests/integration/test_phase12_b1_dashboard.py -v
```

**命令的真实输出**（完整，封版修复后 8 条用例）：

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0 -- /Users/zhangkuo/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/zhangkuo/TradingView Indicator/trading_system
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 8 items

tests/integration/test_phase12_b1_dashboard.py::test_dashboard_decisions_200_and_fields PASSED [ 12%]
tests/integration/test_phase12_b1_dashboard.py::test_dashboard_executions_200_and_fields PASSED [ 25%]
tests/integration/test_phase12_b1_dashboard.py::test_dashboard_summary_no_trade_returns_zero PASSED [ 37%]
tests/integration/test_phase12_b1_dashboard.py::test_dashboard_decisions_invalid_from_400 PASSED [ 50%]
tests/integration/test_phase12_b1_dashboard.py::test_dashboard_executions_invalid_to_400 PASSED [ 62%]
tests/integration/test_phase12_b1_dashboard.py::test_dashboard_summary_with_trade PASSED [ 75%]
tests/integration/test_phase12_b1_dashboard.py::test_dashboard_recent_200_and_limit PASSED [ 87%]
tests/integration/test_phase12_b1_dashboard.py::test_dashboard_decisions_limit_enforced PASSED [100%]

============================== 8 passed in 0.78s ===============================
```

---

## 【F】验收标准逐条对照（YES/NO + 证据）

| 验收口径 | 结果 | 证据 |
|----------|------|------|
| 所有接口返回 HTTP 200（非法 from/to 返回 400），JSON 结构与字段符合本模块定义 | YES | 正常参数下 decisions/executions/summary/recent 均 200；from=bad 或 to=bad 时返回 400、detail 含 "invalid from"/"invalid to"；字段见【C】与实现。 |
| summary 的 trade_count、pnl_sum 与数据库 trade 表聚合结果一致 | YES | test_dashboard_summary_with_trade 插入 trade 后断言 trade_count≥1 且 pnl_sum≈100.5；聚合逻辑为 count(trade_id)、sum(realized_pnl)。 |
| 无 trade 数据时 summary 返回空数组 [] | YES | test_dashboard_summary_no_trade_returns_zero 断言 `resp.json() == []`；实现中无行时返回 `[]`。 |
| 所有列表接口均有分页或 limit 限制 | YES | decisions/executions limit 默认 100、上限 100；recent n 默认 20、上限 100；test_dashboard_decisions_limit_enforced 断言 limit=3 时条数≤3。 |
| 数据仅来自 Phase1.2 既有数据源，无新增表或字段 | YES | 仅使用 decision_snapshot、trade 表及 DecisionSnapshotRepository；未新增迁移、表、列。 |

---

## 验收结论

是否满足模块目标：**是**。B1 四个 GET 接口已实现，数据来源仅为 decision_snapshot 与 trade，汇总口径按 D.7 写死，列表均有 limit 上限，无新增表或字段。封版修复：from/to 非法必返 400；summary 无 trade 返回 []。测试 8 条全部通过。

**文档结束**
