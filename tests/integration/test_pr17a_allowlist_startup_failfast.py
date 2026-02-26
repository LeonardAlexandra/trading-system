"""
PR17a：Live allowlist 启动期 fail-fast。
live_enabled=true 或 allow_real_trading=true 时：
- live_allowlist_accounts 为空 → LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED
- live_allowlist_symbols 为空 → LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED
"""
import pytest

from src.config.app_config import load_app_config
from src.common.config_errors import ConfigValidationError
from src.common.reason_codes import (
    LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED,
    LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED,
)


def test_live_enabled_allowlist_accounts_empty_fail_fast(tmp_path):
    """live_enabled=true 且 live_allowlist_accounts 为空 → 启动 fail-fast。"""
    db_url = "sqlite+aiosqlite:///" + (tmp_path / "pr17a.db").as_posix()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"""
database:
  url: {db_url!r}
execution:
  batch_size: 10
  live_enabled: true
  live_allowlist_symbols: [BTC-USDT]
  qty_precision_by_symbol:
    BTC-USDT: 8
strategies:
  S1:
    enabled: true
    account_id: acc1
    exchange_profile_id: paper
exchange_profiles:
  paper:
    id: paper
    mode: paper
accounts:
  acc1:
    exchange_profile_id: paper
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED


def test_live_enabled_allowlist_symbols_empty_fail_fast(tmp_path):
    """live_enabled=true 且 live_allowlist_symbols 为空 → 启动 fail-fast。"""
    db_url = "sqlite+aiosqlite:///" + (tmp_path / "pr17a2.db").as_posix()
    config_path = tmp_path / "config2.yaml"
    config_path.write_text(f"""
database:
  url: {db_url!r}
execution:
  batch_size: 10
  live_enabled: true
  live_allowlist_accounts: [acc1]
strategies:
  S1:
    enabled: true
    account_id: acc1
    exchange_profile_id: paper
exchange_profiles:
  paper:
    id: paper
    mode: paper
accounts:
  acc1:
    exchange_profile_id: paper
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == LIVE_GATE_ALLOWLIST_SYMBOLS_REQUIRED


def test_allow_real_trading_allowlist_accounts_empty_fail_fast(tmp_path):
    """allow_real_trading=true 且 live_allowlist_accounts 为空 → 启动 fail-fast。"""
    db_url = "sqlite+aiosqlite:///" + (tmp_path / "pr17a3.db").as_posix()
    config_path = tmp_path / "config3.yaml"
    config_path.write_text(f"""
database:
  url: {db_url!r}
execution:
  batch_size: 10
  allow_real_trading: true
  live_allowlist_symbols: [BTC-USDT]
  qty_precision_by_symbol:
    BTC-USDT: 8
strategies:
  S1:
    enabled: true
exchange_profiles:
  paper:
    id: paper
    mode: paper
accounts: {{}}
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == LIVE_GATE_ALLOWLIST_ACCOUNTS_REQUIRED
