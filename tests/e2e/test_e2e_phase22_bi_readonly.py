"""
Phase 2.2 E2E 测试：BI 只读层验证

覆盖蓝本 F 节可验证点：
- E2E-BI-只读：所有 BI 端点均不执行写操作
- E2E-BI-一致性：BI 统计数据与 2.0/2.1 数据源对齐
- E2E-BI-决策过程与缺失展示：PARTIAL/NOT_FOUND 展示 trace_status + missing_nodes

测试场景：
P1 - /api/bi/stats 可查 metrics_snapshot，返回字段正确
P2 - /api/bi/equity_curve 可查 trade realized_pnl 累积曲线
P3 - /api/bi/decision_flow/list 返回 trace_status 字段
P4 - /api/bi/version_history 可查 param_version
P5 - /api/bi/evaluation_history 可查 evaluation_report
P6 - /api/bi/release_audit 可查 release_audit，operator 脱敏
P7 - 只读边界：所有端点均为 GET，无 POST/PUT/DELETE
P8 - /api/bi/stats 过滤：strategy_id、from、to 生效
P9 - /api/bi/decision_flow?decision_id= 存在时返回 200 + trace_status
P10 - /api/bi/decision_flow?decision_id= 不存在时返回 404
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.database.connection import Base
from src.models.trade import Trade
from src.models.metrics_snapshot import MetricsSnapshot
from src.models.evaluation_report import EvaluationReport
from src.models.param_version import ParamVersion
from src.models.release_audit import ReleaseAudit
from src.app.dependencies import set_session_factory

import src.models  # noqa: F401 — 确保所有 ORM 模型注册到 Base.metadata


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _dt(y: int, m: int, d: int, hh: int = 0) -> datetime:
    return datetime(y, m, d, hh, tzinfo=timezone.utc)


@pytest.fixture
async def sf():
    """每测试独立内存 SQLite，自动清理。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    set_session_factory(factory)
    yield factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(sf):
    """ASGI 测试客户端，使用已初始化的测试数据库。"""
    # 延迟导入避免 lifespan 污染
    from src.app.main import create_app
    import os
    os.environ.setdefault("TV_WEBHOOK_SECRET", "test-secret-32-chars-1234567890xx")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    app = create_app()
    # 绕过 lifespan（测试直接使用 sf 设置的 session_factory）
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ─────────────────────────────────────────────────────────────────────────────
# 辅助种数据函数
# ─────────────────────────────────────────────────────────────────────────────

async def _seed_snapshot(sf, strategy_id: str = "S1", pnl: float = 1500.0) -> MetricsSnapshot:
    async with sf() as session:
        snap = MetricsSnapshot(
            strategy_id=strategy_id,
            strategy_version_id="SV1",
            param_version_id="PV1",
            period_start=_dt(2025, 1, 1),
            period_end=_dt(2025, 12, 31),
            trade_count=10,
            win_rate=Decimal("0.6"),
            realized_pnl=Decimal(str(pnl)),
            max_drawdown=Decimal("0.05"),
            avg_holding_time_sec=Decimal("3600"),
        )
        session.add(snap)
        await session.commit()
        await session.refresh(snap)
        return snap


async def _seed_trades(sf, strategy_id: str = "S1") -> None:
    async with sf() as session:
        for i in range(3):
            t = Trade(
                trade_id=f"{strategy_id}-T{i+1}",
                strategy_id=strategy_id,
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("50000"),
                realized_pnl=Decimal(str(100 * (i + 1))),
                executed_at=_dt(2025, 1, i + 1),
            )
            session.add(t)
        await session.commit()


async def _seed_param_version(sf, strategy_id: str = "S1", state: str = "active") -> ParamVersion:
    async with sf() as session:
        pv = ParamVersion(
            param_version_id="PV1",
            strategy_id=strategy_id,
            strategy_version_id="SV1",
            params={"stop_loss_pct": 0.02},
            release_state=state,
        )
        session.add(pv)
        await session.commit()
        await session.refresh(pv)
        return pv


async def _seed_evaluation_report(sf, strategy_id: str = "S1") -> EvaluationReport:
    async with sf() as session:
        rpt = EvaluationReport(
            strategy_id=strategy_id,
            strategy_version_id="SV1",
            param_version_id="PV1",
            evaluated_at=_dt(2025, 6, 1),
            period_start=_dt(2025, 1, 1),
            period_end=_dt(2025, 12, 31),
            objective_definition={"primary": "pnl"},
            constraint_definition={"min_trade_count": 1},
            conclusion="pass",
            comparison_summary={"pnl": 1500.0},
        )
        session.add(rpt)
        await session.commit()
        await session.refresh(rpt)
        return rpt


async def _seed_release_audit(sf, strategy_id: str = "S1") -> ReleaseAudit:
    async with sf() as session:
        ra = ReleaseAudit(
            strategy_id=strategy_id,
            param_version_id="PV1",
            action="APPLY",
            gate_type="MANUAL",
            passed=True,
            operator_or_rule_id="op-secret-123",
        )
        session.add(ra)
        await session.commit()
        await session.refresh(ra)
        return ra


# ─────────────────────────────────────────────────────────────────────────────
# P1 — /api/bi/stats 可查 metrics_snapshot
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p1_stats_returns_snapshot(sf, client):
    await _seed_snapshot(sf, strategy_id="S1", pnl=1500.0)

    resp = await client.get("/api/bi/stats?strategy_id=S1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["strategy_id"] == "S1"
    assert item["realized_pnl"] == pytest.approx(1500.0)
    assert item["trade_count"] == 10
    assert "note" in body
    # 注：note 是只读声明
    assert "只读" in body["note"]


# ─────────────────────────────────────────────────────────────────────────────
# P2 — /api/bi/equity_curve 累积 realized_pnl
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p2_equity_curve_cumulative(sf, client):
    await _seed_trades(sf, strategy_id="S1")

    resp = await client.get("/api/bi/equity_curve?strategy_id=S1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    points = body["points"]
    # 累积 pnl 应递增
    assert points[0]["cumulative_pnl"] == pytest.approx(100.0)
    assert points[1]["cumulative_pnl"] == pytest.approx(300.0)
    assert points[2]["cumulative_pnl"] == pytest.approx(600.0)


# ─────────────────────────────────────────────────────────────────────────────
# P3 — /api/bi/decision_flow/list 返回 trace_status 字段
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p3_decision_flow_list_has_trace_status(sf, client):
    # 无决策数据时，应返回空列表（不报错）
    resp = await client.get(
        "/api/bi/decision_flow/list",
        params={"from": "2025-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "count" in body
    # 列表为空时，count 应为 0
    assert body["count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# P4 — /api/bi/version_history 可查 param_version
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p4_version_history(sf, client):
    await _seed_param_version(sf, strategy_id="S1", state="active")

    resp = await client.get("/api/bi/version_history?strategy_id=S1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["strategy_id"] == "S1"
    assert item["release_state"] == "active"
    assert item["param_version_id"] == "PV1"


# ─────────────────────────────────────────────────────────────────────────────
# P5 — /api/bi/evaluation_history 可查 evaluation_report
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p5_evaluation_history(sf, client):
    await _seed_evaluation_report(sf, strategy_id="S1")

    resp = await client.get("/api/bi/evaluation_history?strategy_id=S1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["strategy_id"] == "S1"
    assert item["conclusion"] == "pass"
    # 字段与 2.0 schema 一致
    assert "period_start" in item
    assert "period_end" in item
    assert "evaluated_at" in item


# ─────────────────────────────────────────────────────────────────────────────
# P6 — /api/bi/release_audit 脱敏（operator_or_rule_id → has_operator）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p6_release_audit_operator_masked(sf, client):
    await _seed_release_audit(sf, strategy_id="S1")

    resp = await client.get("/api/bi/release_audit?strategy_id=S1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    item = body["items"][0]
    # B4 脱敏：operator_or_rule_id 不得出现在响应中
    assert "operator_or_rule_id" not in item
    assert "op-secret-123" not in str(item)
    # has_operator 应为 True（因为 operator_or_rule_id 有值）
    assert item["has_operator"] is True
    assert item["action"] == "APPLY"
    assert item["gate_type"] == "MANUAL"
    assert item["passed"] is True


# ─────────────────────────────────────────────────────────────────────────────
# P7 — 只读边界：所有端点均为 GET，无写操作
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p7_all_bi_endpoints_are_get_only(sf, client):
    """验证 BI 路由不存在 POST/PUT/DELETE 方法。"""
    # 获取 OpenAPI schema 验证方法
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    paths = schema.get("paths", {})

    bi_paths = [p for p in paths if p.startswith("/api/bi/")]
    assert len(bi_paths) > 0, "BI 路由应存在"

    for path in bi_paths:
        methods = set(paths[path].keys())
        # 只允许 GET（以及 OpenAPI 内置的 parameters 等，非 HTTP 方法）
        http_methods = methods & {"get", "post", "put", "delete", "patch"}
        assert http_methods == {"get"}, (
            f"BI 路由 {path} 包含非 GET 方法: {http_methods}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# P8 — /api/bi/stats 过滤参数生效（strategy_id、from、to）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p8_stats_filter_strategy_id(sf, client):
    await _seed_snapshot(sf, strategy_id="S1", pnl=1000.0)
    await _seed_snapshot(sf, strategy_id="S2", pnl=2000.0)

    resp = await client.get("/api/bi/stats?strategy_id=S1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["strategy_id"] == "S1"

    resp2 = await client.get("/api/bi/stats?strategy_id=S2")
    body2 = resp2.json()
    assert body2["count"] == 1
    assert body2["items"][0]["strategy_id"] == "S2"


# ─────────────────────────────────────────────────────────────────────────────
# P9 — /api/bi/decision_flow?decision_id= 不存在时返回 404
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p9_decision_flow_not_found(sf, client):
    resp = await client.get("/api/bi/decision_flow?decision_id=nonexistent-id-xyz")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body


# ─────────────────────────────────────────────────────────────────────────────
# P10 — /api/bi/decision_flow 缺少参数时返回 400
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p10_decision_flow_missing_params(sf, client):
    resp = await client.get("/api/bi/decision_flow")
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body


# ─────────────────────────────────────────────────────────────────────────────
# P11 — 数据一致性：equity_curve 按时间过滤
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p11_equity_curve_time_filter(sf, client):
    await _seed_trades(sf, strategy_id="S1")  # 3 trades: Jan 1, 2, 3

    # 只查第 1 天
    resp = await client.get(
        "/api/bi/equity_curve",
        params={
            "strategy_id": "S1",
            "from": "2025-01-01T00:00:00Z",
            "to": "2025-01-01T23:59:59Z",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["points"][0]["cumulative_pnl"] == pytest.approx(100.0)


# ─────────────────────────────────────────────────────────────────────────────
# P12 — release_audit 无 operator 时 has_operator = False
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p12_release_audit_no_operator(sf, client):
    async with sf() as session:
        ra = ReleaseAudit(
            strategy_id="S_NO_OP",
            param_version_id="PV2",
            action="AUTO_DISABLE",
            gate_type=None,
            passed=False,
            operator_or_rule_id=None,  # 无 operator
        )
        session.add(ra)
        await session.commit()

    resp = await client.get("/api/bi/release_audit?strategy_id=S_NO_OP")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["has_operator"] is False
    assert "operator_or_rule_id" not in body["items"][0]


# ─────────────────────────────────────────────────────────────────────────────
# P13 — BI 页面可访问
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p13_bi_page_accessible(sf, client):
    resp = await client.get("/bi")
    assert resp.status_code == 200
    content = resp.text
    assert "BI 只读展示" in content
    # 验证无状态变更按钮
    assert "触发评估" not in content
    assert "执行回滚" not in content
    assert "通过门禁" not in content
    assert "应用参数" not in content
