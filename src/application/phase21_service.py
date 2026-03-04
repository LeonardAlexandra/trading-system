"""
Phase2.1：Phase21Service — 应用层入口（封装事务边界）

提供 Phase 2.1 的完整业务操作入口：
- suggest_params：基于 evaluation_report 产出参数建议
- submit_candidate：提交候选版本
- confirm_manual：人工审批
- risk_guard_approve：风控护栏审批
- apply_approved：生效为 active
- mark_stable：标记为稳定基线
- rollback_to_stable：一键回滚
- reject_candidate：拒绝候选
- check_auto_disable：异常检测与熔断
- get_current_and_stable：查询当前状态
- get_release_audit_log：审计日志查询
- get_learning_audit_log：学习日志查询

约束（写死）：
- 不写 Phase 2.0 表（evaluation_report / metrics_snapshot）（B.6）。
- Optimizer 输入仅为 evaluation_report（由调用方传入或按 ID 查询）（B.5）。
- 所有状态迁移均写 release_audit。
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.evaluation_report import EvaluationReport
from src.models.param_version import ParamVersion
from src.models.release_audit import ReleaseAudit
from src.models.learning_audit import LearningAudit
from src.phase21.auto_disable_monitor import AutoDisableConfig, AutoDisableMonitor, AutoDisableResult
from src.phase21.optimizer import Optimizer, ParamSuggestion
from src.phase21.release_gate import GateResult, ReleaseGate
from src.repositories.evaluation_report_repository import EvaluationReportRepository
from src.repositories.learning_audit_repository import LearningAuditRepository
from src.repositories.param_version_repository import ParamVersionRepository
from src.repositories.release_audit_repository import ReleaseAuditRepository


class Phase21Service:
    """Phase 2.1 应用层服务：封装会话与事务边界。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        auto_disable_config: Optional[AutoDisableConfig] = None,
    ) -> None:
        self._sf = session_factory
        self._ad_config = auto_disable_config or AutoDisableConfig()

    # ── 1. 参数建议 ─────────────────────────────────────────────────────────
    async def suggest_params(
        self,
        *,
        evaluation_report_id: str,
        current_params: Dict[str, Any],
        param_version_id: Optional[str] = None,
    ) -> ParamSuggestion:
        """
        基于 evaluation_report_id 查询 Phase 2.0 报告，产出参数建议。
        写 learning_audit（ID 引用，不写报告内容）。
        """
        async with self._sf() as session:
            report_repo = EvaluationReportRepository(session)
            # 按 ID 查询 Phase 2.0 报告（仅使用 EvaluationReportRepository，禁止扫描 trade 表）
            reports = await report_repo.get_by_strategy_version(evaluation_report_id)
            report = None
            # evaluation_report_id 实际上是 report.id（BigInt）的字符串形式
            # 也支持 strategy_version_id 查询后取最新一条
            if reports:
                report = reports[0]
            else:
                # 尝试按数字 ID 查询
                from sqlalchemy import select as sa_select
                stmt = sa_select(EvaluationReport).where(
                    EvaluationReport.id == int(evaluation_report_id)
                    if evaluation_report_id.isdigit()
                    else EvaluationReport.strategy_version_id == evaluation_report_id
                )
                result = await session.execute(stmt)
                report = result.scalar_one_or_none()

            if report is None:
                raise ValueError(f"evaluation_report {evaluation_report_id!r} 不存在")

            audit_repo = LearningAuditRepository(session)
            optimizer = Optimizer(audit_repo)
            suggestion = await optimizer.suggest(
                report=report,
                current_params=current_params,
                param_version_id=param_version_id,
            )
            await session.commit()
            return suggestion

    # ── 2. submit_candidate ─────────────────────────────────────────────────
    async def submit_candidate(
        self,
        *,
        strategy_id: str,
        strategy_version_id: str,
        param_version_id: str,
        params: Dict[str, Any],
        operator_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        async with self._sf() as session:
            gate = self._make_gate(session)
            result = await gate.submit_candidate(
                strategy_id=strategy_id,
                strategy_version_id=strategy_version_id,
                param_version_id=param_version_id,
                params=params,
                operator_id=operator_id,
                payload=payload,
            )
            await session.commit()
            return result

    # ── 3. confirm_manual ───────────────────────────────────────────────────
    async def confirm_manual(
        self,
        *,
        strategy_id: str,
        param_version_id: str,
        operator_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        async with self._sf() as session:
            gate = self._make_gate(session)
            result = await gate.confirm_manual(
                strategy_id=strategy_id,
                param_version_id=param_version_id,
                operator_id=operator_id,
                payload=payload,
            )
            await session.commit()
            return result

    # ── 4. risk_guard_approve ───────────────────────────────────────────────
    async def risk_guard_approve(
        self,
        *,
        strategy_id: str,
        param_version_id: str,
        rule_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        async with self._sf() as session:
            gate = self._make_gate(session)
            result = await gate.risk_guard_approve(
                strategy_id=strategy_id,
                param_version_id=param_version_id,
                rule_id=rule_id,
                payload=payload,
            )
            await session.commit()
            return result

    # ── 5. apply_approved ───────────────────────────────────────────────────
    async def apply_approved(
        self,
        *,
        strategy_id: str,
        param_version_id: str,
        operator_id: Optional[str] = None,
    ) -> GateResult:
        async with self._sf() as session:
            gate = self._make_gate(session)
            result = await gate.apply_approved(
                strategy_id=strategy_id,
                param_version_id=param_version_id,
                operator_id=operator_id,
            )
            await session.commit()
            return result

    # ── 6. mark_stable ──────────────────────────────────────────────────────
    async def mark_stable(
        self,
        *,
        strategy_id: str,
        param_version_id: str,
        operator_id: Optional[str] = None,
    ) -> GateResult:
        async with self._sf() as session:
            gate = self._make_gate(session)
            result = await gate.mark_stable(
                strategy_id=strategy_id,
                param_version_id=param_version_id,
                operator_id=operator_id,
            )
            await session.commit()
            return result

    # ── 7. rollback_to_stable ───────────────────────────────────────────────
    async def rollback_to_stable(
        self,
        *,
        strategy_id: str,
        operator_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> GateResult:
        async with self._sf() as session:
            gate = self._make_gate(session)
            result = await gate.rollback_to_stable(
                strategy_id=strategy_id,
                operator_id=operator_id,
                reason=reason,
            )
            await session.commit()
            return result

    # ── 8. reject_candidate ─────────────────────────────────────────────────
    async def reject_candidate(
        self,
        *,
        strategy_id: str,
        param_version_id: str,
        operator_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> GateResult:
        async with self._sf() as session:
            gate = self._make_gate(session)
            result = await gate.reject_candidate(
                strategy_id=strategy_id,
                param_version_id=param_version_id,
                operator_id=operator_id,
                reason=reason,
            )
            await session.commit()
            return result

    # ── 9. check_auto_disable ───────────────────────────────────────────────
    async def check_auto_disable(
        self,
        strategy_id: str,
        *,
        db_ok: bool = True,
        exchange_ok: bool = True,
    ) -> AutoDisableResult:
        async with self._sf() as session:
            monitor = AutoDisableMonitor(
                session=session,
                param_version_repo=ParamVersionRepository(session),
                release_audit_repo=ReleaseAuditRepository(session),
                config=self._ad_config,
            )
            result = await monitor.check_and_disable(
                strategy_id, db_ok=db_ok, exchange_ok=exchange_ok
            )
            await session.commit()
            return result

    # ── 10. 查询 ────────────────────────────────────────────────────────────
    async def get_current_and_stable(self, strategy_id: str) -> Dict[str, Any]:
        async with self._sf() as session:
            gate = self._make_gate(session)
            return await gate.get_current_and_stable(strategy_id)

    async def get_release_audit_log(self, strategy_id: str) -> List[ReleaseAudit]:
        async with self._sf() as session:
            repo = ReleaseAuditRepository(session)
            return await repo.get_by_strategy_id(strategy_id)

    async def get_learning_audit_log(self, strategy_id: str) -> List[LearningAudit]:
        async with self._sf() as session:
            repo = LearningAuditRepository(session)
            return await repo.get_by_strategy_id(strategy_id)

    async def get_param_versions(self, strategy_id: str) -> List[ParamVersion]:
        async with self._sf() as session:
            repo = ParamVersionRepository(session)
            return await repo.get_by_strategy_id(strategy_id)

    # ── 内部工厂 ────────────────────────────────────────────────────────────
    def _make_gate(self, session: AsyncSession) -> ReleaseGate:
        return ReleaseGate(
            param_version_repo=ParamVersionRepository(session),
            release_audit_repo=ReleaseAuditRepository(session),
        )
