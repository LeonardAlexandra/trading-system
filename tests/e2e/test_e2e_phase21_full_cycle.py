"""
Phase2.1 E2E 测试：全闭环验证

覆盖 A.2 完成判定中的所有场景：

F1 - 完整闭环：evaluate(2.0) → suggest → submit_candidate → confirm_manual
              → apply_approved → active → mark_stable → re-evaluate 可查
F2 - 回滚：rollback_to_stable → active 切换 + release_audit 验证
F3 - 自动熔断：连续亏损触发 AUTO_DISABLE + 自动回滚到 stable
F4 - 白名单拦截：非白名单参数被 WhitelistViolation 拒绝
F5 - 门禁路径强制：candidate 不经 approved 直接 apply 触发 StateTransitionError
F6 - 风控护栏审批路径（RISK_GUARD gate_type）
F7 - Phase 2.0 数据完整性：2.1 操作后 evaluation_report/metrics_snapshot 行数不变
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import func, select

from src.database.connection import Base
from src.models.trade import Trade
from src.models.evaluation_report import EvaluationReport
from src.models.metrics_snapshot import MetricsSnapshot
from src.models.param_version import ParamVersion, RELEASE_STATE_ACTIVE, RELEASE_STATE_STABLE, RELEASE_STATE_DISABLED
from src.models.release_audit import ReleaseAudit, ACTION_APPLY, ACTION_ROLLBACK, ACTION_AUTO_DISABLE, ACTION_SUBMIT_CANDIDATE
from src.models.learning_audit import LearningAudit

from src.application.phase2_main_flow_service import Phase2MainFlowService
from src.application.phase21_service import Phase21Service
from src.phase2.evaluation_config import EvaluatorConfig
from src.phase21.whitelist import WhitelistViolation
from src.phase21.release_gate import StateTransitionError, ReleaseGateError
from src.phase21.auto_disable_monitor import AutoDisableConfig
from src.repositories.trade_repo import TradeRepository

import src.models  # noqa: F401 — 确保所有 ORM 模型注册到 Base.metadata


# ─────────────────────────────────────────────────────────────────────────────
# Fixture
# ─────────────────────────────────────────────────────────────────────────────

def _dt(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


@pytest.fixture
async def sf():
    """每个测试独立的内存 SQLite 会话工厂。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：种数据
# ─────────────────────────────────────────────────────────────────────────────

async def _seed_trades(sf, strategy_id: str, pnl_list: list) -> None:
    """按 pnl_list 插入 trade 记录（正数盈利，负数亏损）。"""
    async with sf() as session:
        repo = TradeRepository(session)
        for i, pnl in enumerate(pnl_list):
            t = Trade(
                trade_id=f"{strategy_id}-T{i+1}",
                strategy_id=strategy_id,
                symbol="BTCUSDT",
                side="BUY" if pnl >= 0 else "SELL",
                quantity=Decimal("1"),
                price=Decimal("50000"),
                realized_pnl=Decimal(str(pnl)),
                executed_at=_dt(2025, 1, 1) + timedelta(hours=i),
            )
            await repo.create(t)
        await session.commit()


async def _run_evaluation(sf, strategy_id: str, strategy_version_id: str, param_version_id: str):
    """运行一次 Phase 2.0 评估，返回 report。"""
    svc = Phase2MainFlowService(sf)
    cfg = EvaluatorConfig(
        objective_definition={"primary": "pnl"},
        constraint_definition={"min_trade_count": 1, "max_drawdown_pct": 50.0},
        baseline_version_id=None,
    )
    return await svc.run_main_flow(
        strategy_id=strategy_id,
        strategy_version_id=strategy_version_id,
        param_version_id=param_version_id,
        period_start=_dt(2025, 1, 1),
        period_end=_dt(2025, 12, 31),
        config=cfg,
    )


# ─────────────────────────────────────────────────────────────────────────────
# F1: 完整闭环
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f1_full_cycle(sf):
    """
    F1: evaluate(2.0) → suggest → submit_candidate → confirm_manual
        → apply_approved → active → mark_stable → re-evaluate 可查
    """
    strategy_id = "F1-STRATEGY"
    sv_id = "F1-SV1"
    pv_id_initial = "F1-PV-initial"

    # 1. 种 trade 数据（盈利策略）
    await _seed_trades(sf, strategy_id, [100, 50, 80, -20, 60])

    # 2. Phase 2.0 评估
    report = await _run_evaluation(sf, strategy_id, sv_id, pv_id_initial)
    assert report.conclusion in ("pass", "fail")
    report_id_str = str(report.metrics_snapshot_id) if report.metrics_snapshot_id else sv_id

    # 3. Phase 2.1: 产出参数建议
    svc21 = Phase21Service(sf)
    current_params = {
        "max_position_size": 1.0,
        "fixed_order_size": 0.1,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.10,
    }
    suggestion = await svc21.suggest_params(
        evaluation_report_id=sv_id,  # 按 strategy_version_id 查最新报告
        current_params=current_params,
    )
    assert set(suggestion.suggested_params.keys()).issubset(
        {"max_position_size", "fixed_order_size", "stop_loss_pct", "take_profit_pct"}
    ), "建议参数含非白名单键"
    candidate_pv_id = suggestion.param_version_id_candidate

    # 4. submit_candidate
    submit_result = await svc21.submit_candidate(
        strategy_id=strategy_id,
        strategy_version_id=sv_id,
        param_version_id=candidate_pv_id,
        params=suggestion.suggested_params,
        operator_id="F1-operator",
    )
    assert submit_result.to_state == "candidate"

    # 5. confirm_manual (candidate → approved)
    approve_result = await svc21.confirm_manual(
        strategy_id=strategy_id,
        param_version_id=candidate_pv_id,
        operator_id="F1-operator",
    )
    assert approve_result.to_state == "approved"
    assert approve_result.passed is True

    # 6. apply_approved (approved → active)
    apply_result = await svc21.apply_approved(
        strategy_id=strategy_id,
        param_version_id=candidate_pv_id,
        operator_id="F1-operator",
    )
    assert apply_result.to_state == "active"

    # 7. 验证当前 active
    state = await svc21.get_current_and_stable(strategy_id)
    assert state["active"] is not None
    assert state["active"].param_version_id == candidate_pv_id
    assert state["active"].release_state == RELEASE_STATE_ACTIVE

    # 8. mark_stable
    stable_result = await svc21.mark_stable(
        strategy_id=strategy_id,
        param_version_id=candidate_pv_id,
        operator_id="F1-operator",
    )
    assert stable_result.to_state == "stable"
    state2 = await svc21.get_current_and_stable(strategy_id)
    assert state2["stable"].param_version_id == candidate_pv_id

    # 9. re-evaluate（可查到新报告）
    report2 = await _run_evaluation(sf, strategy_id, sv_id, candidate_pv_id)
    assert report2.param_version_id == candidate_pv_id

    # 10. release_audit 记录完整（至少有 SUBMIT_CANDIDATE + 2× APPLY）
    audit_log = await svc21.get_release_audit_log(strategy_id)
    actions = [a.action for a in audit_log]
    assert ACTION_SUBMIT_CANDIDATE in actions
    assert ACTION_APPLY in actions

    # 11. learning_audit 记录存在
    learning_log = await svc21.get_learning_audit_log(strategy_id)
    assert len(learning_log) >= 1
    lr = learning_log[0]
    assert lr.evaluation_report_id is not None
    assert lr.suggested_params is not None
    # 不含 Phase 2.0 报告内容（仅存 ID）
    assert "conclusion" not in (lr.suggested_params or {})
    assert "objective_definition" not in (lr.suggested_params or {})

    print(f"F1 PASS: full cycle audit_log={len(audit_log)} learning_log={len(learning_log)}")


# ─────────────────────────────────────────────────────────────────────────────
# F2: 回滚
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f2_rollback(sf):
    """
    F2: active v1 → mark_stable → 上线 v2 (active) → rollback_to_stable → v1 重新 active
    """
    strategy_id = "F2-STRATEGY"
    sv_id = "F2-SV1"
    pv_v1 = "F2-PV-v1"
    pv_v2 = "F2-PV-v2"
    params_v1 = {"max_position_size": 1.0, "fixed_order_size": 0.1,
                 "stop_loss_pct": 0.05, "take_profit_pct": 0.10}
    params_v2 = {"max_position_size": 0.8, "fixed_order_size": 0.08,
                 "stop_loss_pct": 0.04, "take_profit_pct": 0.09}

    svc21 = Phase21Service(sf)

    # 上线 v1 (candidate → approved → active)
    await svc21.submit_candidate(strategy_id=strategy_id, strategy_version_id=sv_id,
                                  param_version_id=pv_v1, params=params_v1)
    await svc21.confirm_manual(strategy_id=strategy_id, param_version_id=pv_v1, operator_id="op")
    await svc21.apply_approved(strategy_id=strategy_id, param_version_id=pv_v1)
    # 标记 v1 为 stable
    await svc21.mark_stable(strategy_id=strategy_id, param_version_id=pv_v1, operator_id="op")

    state = await svc21.get_current_and_stable(strategy_id)
    assert state["stable"].param_version_id == pv_v1

    # 上线 v2（覆盖 active，stable 指向 v1）
    await svc21.submit_candidate(strategy_id=strategy_id, strategy_version_id=sv_id,
                                  param_version_id=pv_v2, params=params_v2)
    await svc21.confirm_manual(strategy_id=strategy_id, param_version_id=pv_v2, operator_id="op")
    await svc21.apply_approved(strategy_id=strategy_id, param_version_id=pv_v2)

    state2 = await svc21.get_current_and_stable(strategy_id)
    assert state2["active"].param_version_id == pv_v2
    assert state2["stable"].param_version_id == pv_v1

    # 回滚到 v1（stable）
    rollback_result = await svc21.rollback_to_stable(
        strategy_id=strategy_id, operator_id="op", reason="test_rollback"
    )
    assert rollback_result.action == ACTION_ROLLBACK
    assert rollback_result.to_state == RELEASE_STATE_ACTIVE
    assert rollback_result.param_version_id == pv_v1

    state3 = await svc21.get_current_and_stable(strategy_id)
    assert state3["active"].param_version_id == pv_v1
    assert state3["active"].release_state == RELEASE_STATE_ACTIVE

    # v2 应处于 disabled
    async with sf() as session:
        from src.repositories.param_version_repository import ParamVersionRepository
        repo = ParamVersionRepository(session)
        pv2 = await repo.get_by_param_version_id(pv_v2)
        assert pv2.release_state == RELEASE_STATE_DISABLED

    # release_audit 包含 ROLLBACK 记录
    audit_log = await svc21.get_release_audit_log(strategy_id)
    actions = [a.action for a in audit_log]
    assert ACTION_ROLLBACK in actions

    # ROLLBACK 记录包含 from/to 信息
    rollback_audits = [a for a in audit_log if a.action == ACTION_ROLLBACK]
    assert len(rollback_audits) == 1
    ra = rollback_audits[0]
    assert ra.payload is not None
    assert ra.payload.get("from_active") == pv_v2
    assert ra.payload.get("to_active") == pv_v1

    print(f"F2 PASS: rollback audit payload={ra.payload}")


# ─────────────────────────────────────────────────────────────────────────────
# F3: 自动熔断 + 自动回滚
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f3_auto_disable(sf):
    """
    F3: 连续 5 笔亏损触发 AUTO_DISABLE；若有 stable 则自动回滚。
    """
    strategy_id = "F3-STRATEGY"
    sv_id = "F3-SV1"
    pv_stable = "F3-PV-stable"
    pv_active = "F3-PV-active"
    params_stable = {"max_position_size": 1.0, "fixed_order_size": 0.1,
                     "stop_loss_pct": 0.05, "take_profit_pct": 0.10}
    params_active = {"max_position_size": 1.5, "fixed_order_size": 0.15,
                     "stop_loss_pct": 0.08, "take_profit_pct": 0.12}

    svc21 = Phase21Service(
        sf,
        auto_disable_config=AutoDisableConfig(consecutive_loss_trades=5),
    )

    # 上线 stable 版本
    await svc21.submit_candidate(strategy_id=strategy_id, strategy_version_id=sv_id,
                                  param_version_id=pv_stable, params=params_stable)
    await svc21.confirm_manual(strategy_id=strategy_id, param_version_id=pv_stable, operator_id="op")
    await svc21.apply_approved(strategy_id=strategy_id, param_version_id=pv_stable)
    await svc21.mark_stable(strategy_id=strategy_id, param_version_id=pv_stable, operator_id="op")

    # 上线 active 版本
    await svc21.submit_candidate(strategy_id=strategy_id, strategy_version_id=sv_id,
                                  param_version_id=pv_active, params=params_active)
    await svc21.confirm_manual(strategy_id=strategy_id, param_version_id=pv_active, operator_id="op")
    await svc21.apply_approved(strategy_id=strategy_id, param_version_id=pv_active)

    state = await svc21.get_current_and_stable(strategy_id)
    assert state["active"].param_version_id == pv_active
    assert state["stable"].param_version_id == pv_stable

    # 种 5 笔连续亏损 trade
    await _seed_trades(sf, strategy_id, [-100, -50, -80, -60, -70])

    # 触发熔断检测
    ad_result = await svc21.check_auto_disable(strategy_id)
    assert ad_result.triggered is True
    assert "consecutive_loss_trades" in ad_result.trigger_reason
    assert ad_result.prev_active_id == pv_active
    assert ad_result.rolled_back_to == pv_stable

    # active → pv_stable；pv_active → disabled
    state2 = await svc21.get_current_and_stable(strategy_id)
    assert state2["active"].param_version_id == pv_stable
    assert state2["active"].release_state == RELEASE_STATE_ACTIVE

    async with sf() as session:
        from src.repositories.param_version_repository import ParamVersionRepository
        repo = ParamVersionRepository(session)
        pa = await repo.get_by_param_version_id(pv_active)
        assert pa.release_state == RELEASE_STATE_DISABLED

    # release_audit 包含 AUTO_DISABLE
    audit_log = await svc21.get_release_audit_log(strategy_id)
    auto_disable_audits = [a for a in audit_log if a.action == ACTION_AUTO_DISABLE]
    assert len(auto_disable_audits) >= 1
    ad_audit = auto_disable_audits[0]
    assert ad_audit.passed is False
    assert ad_audit.payload is not None
    assert ad_audit.payload.get("trigger_reason") is not None

    print(f"F3 PASS: auto_disable trigger={ad_result.trigger_reason}")


# ─────────────────────────────────────────────────────────────────────────────
# F4: 白名单拦截
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f4_whitelist_enforcement(sf):
    """
    F4: 含非白名单参数（如 strategy_logic_flag）时，submit_candidate 抛 ReleaseGateError。
    """
    strategy_id = "F4-STRATEGY"
    sv_id = "F4-SV1"
    pv_id = "F4-PV-illegal"

    svc21 = Phase21Service(sf)

    # 非白名单参数
    illegal_params = {
        "max_position_size": 1.0,
        "strategy_logic_flag": True,   # 非白名单
        "risk_engine_bypass": False,   # 非白名单（危险）
    }

    with pytest.raises((ReleaseGateError, WhitelistViolation)):
        await svc21.submit_candidate(
            strategy_id=strategy_id,
            strategy_version_id=sv_id,
            param_version_id=pv_id,
            params=illegal_params,
        )

    # 确认未创建任何 param_version 记录
    pvs = await svc21.get_param_versions(strategy_id)
    assert len(pvs) == 0, "非白名单参数不应创建 param_version 记录"

    print("F4 PASS: whitelist enforcement works")


# ─────────────────────────────────────────────────────────────────────────────
# F5: 门禁路径强制 — 禁止跳过 approved 直接 active
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f5_gate_path_enforcement(sf):
    """
    F5: candidate 未经 confirm_manual 直接 apply_approved → StateTransitionError。
    """
    strategy_id = "F5-STRATEGY"
    sv_id = "F5-SV1"
    pv_id = "F5-PV-candidate"
    params = {"max_position_size": 1.0, "fixed_order_size": 0.1,
              "stop_loss_pct": 0.05, "take_profit_pct": 0.10}

    svc21 = Phase21Service(sf)

    await svc21.submit_candidate(
        strategy_id=strategy_id, strategy_version_id=sv_id,
        param_version_id=pv_id, params=params
    )

    # 跳过 confirm_manual，直接 apply_approved → 应报错
    with pytest.raises(StateTransitionError):
        await svc21.apply_approved(strategy_id=strategy_id, param_version_id=pv_id)

    # 状态依然是 candidate
    pvs = await svc21.get_param_versions(strategy_id)
    assert len(pvs) == 1
    assert pvs[0].release_state == "candidate"

    print("F5 PASS: gate path enforcement works")


# ─────────────────────────────────────────────────────────────────────────────
# F6: 风控护栏审批路径
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f6_risk_guard_path(sf):
    """
    F6: candidate → risk_guard_approve → approved → active；
    gate_type=RISK_GUARD 写入 release_audit。
    """
    strategy_id = "F6-STRATEGY"
    sv_id = "F6-SV1"
    pv_id = "F6-PV-rg"
    params = {"max_position_size": 0.5, "fixed_order_size": 0.05,
              "stop_loss_pct": 0.03, "take_profit_pct": 0.08}

    svc21 = Phase21Service(sf)

    await svc21.submit_candidate(
        strategy_id=strategy_id, strategy_version_id=sv_id,
        param_version_id=pv_id, params=params
    )
    rg_result = await svc21.risk_guard_approve(
        strategy_id=strategy_id, param_version_id=pv_id, rule_id="rg-rule-001"
    )
    assert rg_result.to_state == "approved"

    apply_result = await svc21.apply_approved(strategy_id=strategy_id, param_version_id=pv_id)
    assert apply_result.to_state == "active"

    # release_audit 的 APPLY 记录有 gate_type=RISK_GUARD
    audit_log = await svc21.get_release_audit_log(strategy_id)
    rg_audits = [a for a in audit_log if a.gate_type == "RISK_GUARD"]
    assert len(rg_audits) >= 1
    assert rg_audits[0].operator_or_rule_id == "rg-rule-001"

    print("F6 PASS: RISK_GUARD gate_type in release_audit")


# ─────────────────────────────────────────────────────────────────────────────
# F7: Phase 2.0 数据完整性 — 2.1 操作不污染 2.0 表
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f7_phase20_immutability(sf):
    """
    F7: Phase 2.1 操作后 evaluation_report 与 metrics_snapshot 行数不变（B.6）。
    """
    strategy_id = "F7-STRATEGY"
    sv_id = "F7-SV1"
    pv_initial = "F7-PV-initial"
    pv_new = "F7-PV-new"

    await _seed_trades(sf, strategy_id, [100, 50, -20, 80])

    # Phase 2.0 评估
    await _run_evaluation(sf, strategy_id, sv_id, pv_initial)

    async def _count_phase20(session):
        er = int((await session.execute(select(func.count()).select_from(EvaluationReport))).scalar() or 0)
        ms = int((await session.execute(select(func.count()).select_from(MetricsSnapshot))).scalar() or 0)
        return er, ms

    async with sf() as session:
        er_before, ms_before = await _count_phase20(session)

    # 执行一系列 Phase 2.1 操作
    svc21 = Phase21Service(sf)
    params = {"max_position_size": 1.0, "fixed_order_size": 0.1,
              "stop_loss_pct": 0.05, "take_profit_pct": 0.10}
    await svc21.submit_candidate(strategy_id=strategy_id, strategy_version_id=sv_id,
                                  param_version_id=pv_new, params=params)
    await svc21.confirm_manual(strategy_id=strategy_id, param_version_id=pv_new, operator_id="op")
    await svc21.apply_approved(strategy_id=strategy_id, param_version_id=pv_new)
    await svc21.mark_stable(strategy_id=strategy_id, param_version_id=pv_new, operator_id="op")
    await svc21.rollback_to_stable(strategy_id=strategy_id)

    async with sf() as session:
        er_after, ms_after = await _count_phase20(session)

    # Phase 2.0 行数不变（2.1 没有写入 evaluation_report / metrics_snapshot）
    assert er_after == er_before, f"evaluation_report 行数被污染: {er_before} → {er_after}"
    assert ms_after == ms_before, f"metrics_snapshot 行数被污染: {ms_before} → {ms_after}"

    print(f"F7 PASS: 2.0 tables immutable: er={er_before}, ms={ms_before}")


# ─────────────────────────────────────────────────────────────────────────────
# F8: 无 stable 时回滚失败（边界条件）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f8_rollback_no_stable(sf):
    """
    F8: 没有 stable 版本时 rollback_to_stable 应抛 ReleaseGateError。
    """
    strategy_id = "F8-STRATEGY"
    sv_id = "F8-SV1"
    pv_id = "F8-PV-only"
    params = {"max_position_size": 1.0, "fixed_order_size": 0.1,
              "stop_loss_pct": 0.05, "take_profit_pct": 0.10}

    svc21 = Phase21Service(sf)
    await svc21.submit_candidate(strategy_id=strategy_id, strategy_version_id=sv_id,
                                  param_version_id=pv_id, params=params)
    await svc21.confirm_manual(strategy_id=strategy_id, param_version_id=pv_id, operator_id="op")
    await svc21.apply_approved(strategy_id=strategy_id, param_version_id=pv_id)
    # 不 mark_stable

    with pytest.raises(ReleaseGateError):
        await svc21.rollback_to_stable(strategy_id=strategy_id)

    print("F8 PASS: rollback without stable raises ReleaseGateError")


# ─────────────────────────────────────────────────────────────────────────────
# F9: 熔断后无 stable，仅停用不回滚
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f9_auto_disable_no_stable(sf):
    """
    F9: 熔断触发但无 stable 版本 → active → disabled，rolled_back_to=None。
    """
    strategy_id = "F9-STRATEGY"
    sv_id = "F9-SV1"
    pv_id = "F9-PV-active"
    params = {"max_position_size": 1.0, "fixed_order_size": 0.1,
              "stop_loss_pct": 0.05, "take_profit_pct": 0.10}

    svc21 = Phase21Service(
        sf,
        auto_disable_config=AutoDisableConfig(consecutive_loss_trades=3),
    )
    await svc21.submit_candidate(strategy_id=strategy_id, strategy_version_id=sv_id,
                                  param_version_id=pv_id, params=params)
    await svc21.confirm_manual(strategy_id=strategy_id, param_version_id=pv_id, operator_id="op")
    await svc21.apply_approved(strategy_id=strategy_id, param_version_id=pv_id)

    await _seed_trades(sf, strategy_id, [-100, -50, -80])

    result = await svc21.check_auto_disable(strategy_id)
    assert result.triggered is True
    assert result.rolled_back_to is None  # 无 stable，无法回滚

    state = await svc21.get_current_and_stable(strategy_id)
    assert state["active"] is None  # 已停用，无 active

    print("F9 PASS: auto_disable without stable — only disabled, no rollback")
