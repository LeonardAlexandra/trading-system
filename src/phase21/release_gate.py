"""
Phase2.1 T2.1-4：ReleaseGate 发布门禁状态机

发布状态机五态（写死，B.3）：
  candidate → approved → active → stable（人工标记）
                                → disabled（异常触发，B.2）

写回路径（写死，B.3）：
  candidate → approved → active
  禁止：跳过 candidate；跳过 approved；覆盖 stable。

每次状态迁移均写 release_audit 记录（action, gate_type, passed, operator_or_rule_id, payload）。

约束（写死）：
- 仅 active 允许交易。
- 写回对象仅为 param_version（不写 strategy_version）。
- 自动写回默认关闭（auto_apply=False），需显式配置开启并经门禁。
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.models.param_version import (
    ParamVersion,
    RELEASE_STATE_CANDIDATE,
    RELEASE_STATE_APPROVED,
    RELEASE_STATE_ACTIVE,
    RELEASE_STATE_STABLE,
    RELEASE_STATE_DISABLED,
)
from src.models.release_audit import (
    ReleaseAudit,
    ACTION_APPLY,
    ACTION_ROLLBACK,
    ACTION_SUBMIT_CANDIDATE,
    ACTION_REJECT,
    GATE_TYPE_MANUAL,
    GATE_TYPE_RISK_GUARD,
)
from src.phase21.whitelist import validate_params, WhitelistViolation
from src.repositories.param_version_repository import ParamVersionRepository
from src.repositories.release_audit_repository import ReleaseAuditRepository


class ReleaseGateError(Exception):
    pass


class StateTransitionError(ReleaseGateError):
    """非法状态迁移（如跳过 approved 直接 active）。"""


class NotFoundError(ReleaseGateError):
    """找不到对应的 param_version 记录。"""


@dataclass
class GateResult:
    """门禁操作结果。"""
    param_version_id: str
    from_state: str
    to_state: str
    action: str
    passed: bool
    audit_id: Optional[int] = None


class ReleaseGate:
    """
    发布门禁状态机。

    所有状态迁移均写 release_audit（禁止静默丢失审计）。
    """

    def __init__(
        self,
        param_version_repo: ParamVersionRepository,
        release_audit_repo: ReleaseAuditRepository,
    ) -> None:
        self._pv_repo = param_version_repo
        self._audit_repo = release_audit_repo

    # ─────────────────────────────────────────────────────
    # 1. submit_candidate：提交候选参数版本（已在 candidate 态）
    # ─────────────────────────────────────────────────────
    async def submit_candidate(
        self,
        strategy_id: str,
        strategy_version_id: str,
        param_version_id: str,
        params: Dict[str, Any],
        operator_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        """
        提交候选参数版本（candidate 态）。

        - 校验参数白名单（B.1/B.4）。
        - 若 param_version_id 已存在则直接复用，否则创建新记录。
        - 写 release_audit(action=SUBMIT_CANDIDATE, passed=True)。
        """
        try:
            validate_params(params)
        except WhitelistViolation as e:
            raise ReleaseGateError(f"参数白名单校验失败：{e}") from e

        existing = await self._pv_repo.get_by_param_version_id(param_version_id)
        if existing is None:
            pv = ParamVersion(
                param_version_id=param_version_id,
                strategy_id=strategy_id,
                strategy_version_id=strategy_version_id,
                params=params,
                release_state=RELEASE_STATE_CANDIDATE,
            )
            await self._pv_repo.create(pv)
        else:
            if existing.release_state not in (RELEASE_STATE_CANDIDATE,):
                raise StateTransitionError(
                    f"param_version {param_version_id!r} 已处于 {existing.release_state!r}，"
                    f"无法重新提交 candidate"
                )

        audit = ReleaseAudit(
            strategy_id=strategy_id,
            param_version_id=param_version_id,
            action=ACTION_SUBMIT_CANDIDATE,
            gate_type=GATE_TYPE_MANUAL,
            passed=True,
            operator_or_rule_id=operator_id,
            created_at=datetime.now(timezone.utc),
            payload=payload,
        )
        audit_row = await self._audit_repo.append(audit)

        return GateResult(
            param_version_id=param_version_id,
            from_state=RELEASE_STATE_CANDIDATE,
            to_state=RELEASE_STATE_CANDIDATE,
            action=ACTION_SUBMIT_CANDIDATE,
            passed=True,
            audit_id=audit_row.id,
        )

    # ─────────────────────────────────────────────────────
    # 2. confirm_manual：人工审批通过（candidate → approved）
    # ─────────────────────────────────────────────────────
    async def confirm_manual(
        self,
        strategy_id: str,
        param_version_id: str,
        operator_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        """
        人工审批通过：candidate → approved。
        写 release_audit(action=APPLY, gate_type=MANUAL, passed=True)。
        """
        pv = await self._pv_repo.get_by_param_version_id(param_version_id)
        if pv is None:
            raise NotFoundError(f"param_version {param_version_id!r} 不存在")
        if pv.release_state != RELEASE_STATE_CANDIDATE:
            raise StateTransitionError(
                f"只有 candidate 态可人工审批，当前状态: {pv.release_state!r}"
            )

        await self._pv_repo.update_release_state(param_version_id, RELEASE_STATE_APPROVED)

        audit = ReleaseAudit(
            strategy_id=strategy_id,
            param_version_id=param_version_id,
            action=ACTION_APPLY,
            gate_type=GATE_TYPE_MANUAL,
            passed=True,
            operator_or_rule_id=operator_id,
            created_at=datetime.now(timezone.utc),
            payload=payload or {"from": RELEASE_STATE_CANDIDATE, "to": RELEASE_STATE_APPROVED},
        )
        audit_row = await self._audit_repo.append(audit)

        return GateResult(
            param_version_id=param_version_id,
            from_state=RELEASE_STATE_CANDIDATE,
            to_state=RELEASE_STATE_APPROVED,
            action=ACTION_APPLY,
            passed=True,
            audit_id=audit_row.id,
        )

    # ─────────────────────────────────────────────────────
    # 3. risk_guard_approve：风控护栏自动审批（candidate → approved）
    # ─────────────────────────────────────────────────────
    async def risk_guard_approve(
        self,
        strategy_id: str,
        param_version_id: str,
        rule_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        """
        风控护栏自动审批：candidate → approved。
        写 release_audit(action=APPLY, gate_type=RISK_GUARD, passed=True)。
        """
        pv = await self._pv_repo.get_by_param_version_id(param_version_id)
        if pv is None:
            raise NotFoundError(f"param_version {param_version_id!r} 不存在")
        if pv.release_state != RELEASE_STATE_CANDIDATE:
            raise StateTransitionError(
                f"只有 candidate 态可风控护栏审批，当前状态: {pv.release_state!r}"
            )

        await self._pv_repo.update_release_state(param_version_id, RELEASE_STATE_APPROVED)

        audit = ReleaseAudit(
            strategy_id=strategy_id,
            param_version_id=param_version_id,
            action=ACTION_APPLY,
            gate_type=GATE_TYPE_RISK_GUARD,
            passed=True,
            operator_or_rule_id=rule_id,
            created_at=datetime.now(timezone.utc),
            payload=payload or {"from": RELEASE_STATE_CANDIDATE, "to": RELEASE_STATE_APPROVED},
        )
        audit_row = await self._audit_repo.append(audit)

        return GateResult(
            param_version_id=param_version_id,
            from_state=RELEASE_STATE_CANDIDATE,
            to_state=RELEASE_STATE_APPROVED,
            action=ACTION_APPLY,
            passed=True,
            audit_id=audit_row.id,
        )

    # ─────────────────────────────────────────────────────
    # 4. apply_approved：生效（approved → active）
    # ─────────────────────────────────────────────────────
    async def apply_approved(
        self,
        strategy_id: str,
        param_version_id: str,
        operator_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        """
        将已审批版本生效为 active。approved → active。
        禁止跳过 approved 直接从 candidate 生效（StateTransitionError）。
        写 release_audit(action=APPLY, passed=True)。
        """
        pv = await self._pv_repo.get_by_param_version_id(param_version_id)
        if pv is None:
            raise NotFoundError(f"param_version {param_version_id!r} 不存在")
        if pv.release_state != RELEASE_STATE_APPROVED:
            raise StateTransitionError(
                f"只有 approved 态可 apply 为 active，当前状态: {pv.release_state!r}"
            )

        await self._pv_repo.update_release_state(param_version_id, RELEASE_STATE_ACTIVE)

        audit = ReleaseAudit(
            strategy_id=strategy_id,
            param_version_id=param_version_id,
            action=ACTION_APPLY,
            gate_type=GATE_TYPE_MANUAL,
            passed=True,
            operator_or_rule_id=operator_id,
            created_at=datetime.now(timezone.utc),
            payload=payload or {"from": RELEASE_STATE_APPROVED, "to": RELEASE_STATE_ACTIVE},
        )
        audit_row = await self._audit_repo.append(audit)

        return GateResult(
            param_version_id=param_version_id,
            from_state=RELEASE_STATE_APPROVED,
            to_state=RELEASE_STATE_ACTIVE,
            action=ACTION_APPLY,
            passed=True,
            audit_id=audit_row.id,
        )

    # ─────────────────────────────────────────────────────
    # 5. mark_stable：人工标记当前 active 为 stable
    # ─────────────────────────────────────────────────────
    async def mark_stable(
        self,
        strategy_id: str,
        param_version_id: str,
        operator_id: Optional[str] = None,
    ) -> GateResult:
        """
        人工将当前 active 版本标记为 stable（作为回滚基线）。
        active 态同时被标记为 stable；仍允许交易（active + stable 共存于一个版本）。
        """
        pv = await self._pv_repo.get_by_param_version_id(param_version_id)
        if pv is None:
            raise NotFoundError(f"param_version {param_version_id!r} 不存在")
        if pv.release_state != RELEASE_STATE_ACTIVE:
            raise StateTransitionError(
                f"只有 active 态可标记为 stable，当前状态: {pv.release_state!r}"
            )

        await self._pv_repo.update_release_state(param_version_id, RELEASE_STATE_STABLE)

        audit = ReleaseAudit(
            strategy_id=strategy_id,
            param_version_id=param_version_id,
            action=ACTION_APPLY,
            gate_type=GATE_TYPE_MANUAL,
            passed=True,
            operator_or_rule_id=operator_id,
            created_at=datetime.now(timezone.utc),
            payload={"from": RELEASE_STATE_ACTIVE, "to": RELEASE_STATE_STABLE, "note": "mark_stable"},
        )
        audit_row = await self._audit_repo.append(audit)

        return GateResult(
            param_version_id=param_version_id,
            from_state=RELEASE_STATE_ACTIVE,
            to_state=RELEASE_STATE_STABLE,
            action=ACTION_APPLY,
            passed=True,
            audit_id=audit_row.id,
        )

    # ─────────────────────────────────────────────────────
    # 6. rollback_to_stable：一键回滚（active → 上一 stable）
    # ─────────────────────────────────────────────────────
    async def rollback_to_stable(
        self,
        strategy_id: str,
        operator_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> GateResult:
        """
        一键回滚：将当前 active 版本脱离生效（→ disabled），
        将上一 stable 版本重新置为 active。

        写 release_audit(action=ROLLBACK, passed=True)。
        若无 stable 版本则抛 ReleaseGateError。
        """
        active_pv = await self._pv_repo.get_active(strategy_id)
        stable_pv = await self._pv_repo.get_stable(strategy_id)

        if stable_pv is None:
            raise ReleaseGateError(
                f"strategy {strategy_id!r} 没有 stable 版本，无法回滚"
            )

        prev_active_id = active_pv.param_version_id if active_pv else None
        stable_id = stable_pv.param_version_id

        # 当前 active → disabled（脱离生效）
        if active_pv is not None and active_pv.param_version_id != stable_id:
            await self._pv_repo.update_release_state(
                active_pv.param_version_id, RELEASE_STATE_DISABLED
            )

        # stable → active
        await self._pv_repo.update_release_state(stable_id, RELEASE_STATE_ACTIVE)

        payload: Dict[str, Any] = {
            "from_active": prev_active_id,
            "to_active": stable_id,
            "reason": reason or "manual_rollback",
        }
        audit = ReleaseAudit(
            strategy_id=strategy_id,
            param_version_id=stable_id,
            action=ACTION_ROLLBACK,
            gate_type=GATE_TYPE_MANUAL,
            passed=True,
            operator_or_rule_id=operator_id,
            created_at=datetime.now(timezone.utc),
            payload=payload,
        )
        audit_row = await self._audit_repo.append(audit)

        return GateResult(
            param_version_id=stable_id,
            from_state=RELEASE_STATE_STABLE,
            to_state=RELEASE_STATE_ACTIVE,
            action=ACTION_ROLLBACK,
            passed=True,
            audit_id=audit_row.id,
        )

    # ─────────────────────────────────────────────────────
    # 7. reject_candidate：拒绝候选（candidate → candidate，记录 REJECT）
    # ─────────────────────────────────────────────────────
    async def reject_candidate(
        self,
        strategy_id: str,
        param_version_id: str,
        operator_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> GateResult:
        """
        拒绝候选版本：状态保持 candidate（或可标记为 disabled 依实现约定），写 REJECT 审计。
        """
        pv = await self._pv_repo.get_by_param_version_id(param_version_id)
        if pv is None:
            raise NotFoundError(f"param_version {param_version_id!r} 不存在")
        if pv.release_state not in (RELEASE_STATE_CANDIDATE, RELEASE_STATE_APPROVED):
            raise StateTransitionError(
                f"只有 candidate/approved 可被拒绝，当前状态: {pv.release_state!r}"
            )

        await self._pv_repo.update_release_state(param_version_id, RELEASE_STATE_DISABLED)

        audit = ReleaseAudit(
            strategy_id=strategy_id,
            param_version_id=param_version_id,
            action=ACTION_REJECT,
            gate_type=GATE_TYPE_MANUAL,
            passed=False,
            operator_or_rule_id=operator_id,
            created_at=datetime.now(timezone.utc),
            payload={"reason": reason},
        )
        audit_row = await self._audit_repo.append(audit)

        return GateResult(
            param_version_id=param_version_id,
            from_state=pv.release_state,
            to_state=RELEASE_STATE_DISABLED,
            action=ACTION_REJECT,
            passed=False,
            audit_id=audit_row.id,
        )

    # ─────────────────────────────────────────────────────
    # 8. 查询：当前 active 与 stable
    # ─────────────────────────────────────────────────────
    async def get_current_and_stable(self, strategy_id: str) -> Dict[str, Any]:
        """返回 {active: ParamVersion|None, stable: ParamVersion|None}。"""
        active = await self._pv_repo.get_active(strategy_id)
        stable = await self._pv_repo.get_stable(strategy_id)
        return {"active": active, "stable": stable}
