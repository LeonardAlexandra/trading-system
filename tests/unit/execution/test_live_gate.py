"""
PR16：多重 Live 门禁单元测试。
任意门禁未满足 → 禁止真实交易；dry_run 时通过；Paper 适配器不触发门禁。
"""
import os
import pytest

from src.execution.live_gate import check_live_gates
from src.common.reason_codes import (
    LIVE_GATE_ACCOUNT_NOT_ALLOWED,
    LIVE_GATE_ALLOW_REAL_TRADING_OFF,
    LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED,
    LIVE_GATE_CONFIRM_TOKEN_MISSING,
    LIVE_GATE_CONFIRM_TOKEN_MISMATCH,
    LIVE_GATE_LIVE_ENABLED_REQUIRED,
)


def test_live_gate_dry_run_passes():
    """dry_run=True 时门禁通过（不发起真实请求）。"""
    r = check_live_gates(
        dry_run=True,
        live_enabled=False,
        allow_real_trading=False,
        live_allowlist_accounts=[],
        live_confirm_token_configured="",
        account_id=None,
        exchange_profile=None,
        is_live_endpoint=False,
    )
    assert r.allowed is True


def test_live_gate_allow_real_trading_off_rejects():
    """is_live_endpoint=True 时 allow_real_trading=False 拒绝（仅 live endpoint 才校验）。"""
    r = check_live_gates(
        dry_run=False,
        live_enabled=True,
        allow_real_trading=False,
        live_allowlist_accounts=[],
        live_confirm_token_configured="",
        account_id="acc-1",
        exchange_profile="okx_demo",
        is_live_endpoint=True,
    )
    assert r.allowed is False
    assert r.reason_code == LIVE_GATE_ALLOW_REAL_TRADING_OFF


def test_live_gate_allowlist_rejects_when_not_in_list():
    """is_live_endpoint=True 时 live_allowlist_accounts 非空且 account_id 不在列表则拒绝。"""
    r = check_live_gates(
        dry_run=False,
        live_enabled=True,
        allow_real_trading=True,
        live_allowlist_accounts=["acc-a", "acc-b"],
        live_confirm_token_configured="",
        account_id="acc-other",
        exchange_profile="okx_demo",
        is_live_endpoint=True,
    )
    assert r.allowed is False
    assert r.reason_code == LIVE_GATE_ACCOUNT_NOT_ALLOWED


def test_live_gate_allowlist_passes_when_in_list(monkeypatch):
    """account_id 在 allowlist 内且 token 一致时通过（非 live endpoint）。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "secret-token")
    r = check_live_gates(
        dry_run=False,
        live_enabled=True,
        allow_real_trading=True,
        live_allowlist_accounts=["acc-a"],
        live_confirm_token_configured="secret-token",
        account_id="acc-a",
        exchange_profile="okx_demo",
        is_live_endpoint=False,
    )
    assert r.allowed is True


def test_live_gate_allowlist_accounts_empty_rejects():
    """PR17a：is_live_endpoint=True 时 live_allowlist_accounts 为空则拒绝。"""
    r = check_live_gates(
        dry_run=False,
        live_enabled=True,
        allow_real_trading=True,
        live_allowlist_accounts=[],
        live_confirm_token_configured="t",
        account_id="acc-1",
        exchange_profile="okx_live",
        is_live_endpoint=True,
    )
    assert r.allowed is False
    assert r.reason_code == LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED


def test_live_gate_confirm_token_missing_rejects(monkeypatch):
    """is_live_endpoint=True 时配置或 env 缺失 token 则拒绝 LIVE_GATE_CONFIRM_TOKEN_MISSING。"""
    monkeypatch.delenv("LIVE_CONFIRM_TOKEN", raising=False)
    r = check_live_gates(
        dry_run=False,
        live_enabled=True,
        allow_real_trading=True,
        live_allowlist_accounts=["acc-1"],
        live_confirm_token_configured="t",
        account_id="acc-1",
        exchange_profile="okx_demo",
        is_live_endpoint=True,
    )
    assert r.allowed is False
    assert r.reason_code == LIVE_GATE_CONFIRM_TOKEN_MISSING


def test_live_gate_confirm_token_mismatch_rejects(monkeypatch):
    """is_live_endpoint=True 时两端均有 token 但不一致则拒绝 LIVE_GATE_CONFIRM_TOKEN_MISMATCH。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "env-token")
    r = check_live_gates(
        dry_run=False,
        live_enabled=True,
        allow_real_trading=True,
        live_allowlist_accounts=["acc-1"],
        live_confirm_token_configured="wrong-token",
        account_id="acc-1",
        exchange_profile="okx_demo",
        is_live_endpoint=True,
    )
    assert r.allowed is False
    assert r.reason_code == LIVE_GATE_CONFIRM_TOKEN_MISMATCH


def test_live_gate_live_enabled_false_rejects():
    """PR17b：is_live_endpoint=True 时 live_enabled=False 则拒绝。"""
    r = check_live_gates(
        dry_run=False,
        live_enabled=False,
        allow_real_trading=True,
        live_allowlist_accounts=["acc-1"],
        live_confirm_token_configured="t",
        account_id="acc-1",
        exchange_profile="okx_live",
        is_live_endpoint=True,
    )
    assert r.allowed is False
    assert r.reason_code == LIVE_GATE_LIVE_ENABLED_REQUIRED


def test_live_gate_pr17b_all_gates_pass_allowed(monkeypatch):
    """PR17b：门禁全过（含 live_enabled）则允许 live create_order。"""
    monkeypatch.setenv("LIVE_CONFIRM_TOKEN", "t")
    r = check_live_gates(
        dry_run=False,
        live_enabled=True,
        allow_real_trading=True,
        live_allowlist_accounts=["acc-1"],
        live_confirm_token_configured="t",
        account_id="acc-1",
        exchange_profile="okx_live",
        is_live_endpoint=True,
    )
    assert r.allowed is True
