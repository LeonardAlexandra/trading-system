"""
PR16c：qty 精度按 symbol 覆盖 + live_allowlist_symbols 门禁。
- unit：symbol 覆盖精度生效；非 allowlist 使用全局 fallback。
- integration：live_allowlist_symbols 中 symbol 缺 qty_precision_by_symbol 配置 → 启动 fail-fast。
"""
import pytest

from src.config.app_config import load_app_config
from src.common.config_errors import ConfigValidationError
from src.common.reason_codes import LIVE_GATE_SYMBOL_PRECISION_MISSING


def test_live_allowlist_symbols_missing_qty_precision_fail_fast(tmp_path):
    """
    PR16c：live_allowlist_symbols 非空时，每个 symbol 须在 qty_precision_by_symbol 中显式配置，否则启动 fail-fast。
    """
    db_url = "sqlite+aiosqlite:///" + (tmp_path / "pr16c.db").as_posix()
    config_path = tmp_path / "pr16c_config.yaml"
    config_path.write_text(f"""
database:
  url: {db_url!r}
execution:
  batch_size: 10
  live_allowlist_symbols:
    - BTC-USDT
    - ETH-USDT
  qty_precision_by_symbol:
    BTC-USDT: 6
strategies:
  strat-1:
    enabled: true
exchange_profiles:
  paper:
    id: paper
    name: paper
    mode: paper
accounts:
  acc1:
    account_id: acc1
    exchange_profile_id: paper
""")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_app_config(str(config_path))
    assert exc_info.value.reason_code == LIVE_GATE_SYMBOL_PRECISION_MISSING
    assert "ETH-USDT" in (exc_info.value.message or "")


def test_live_allowlist_symbols_all_have_precision_passes(tmp_path):
    """live_allowlist_symbols 中每个 symbol 均在 qty_precision_by_symbol 中配置则通过。"""
    db_url = "sqlite+aiosqlite:///" + (tmp_path / "pr16c_ok.db").as_posix()
    config_path = tmp_path / "pr16c_ok_config.yaml"
    config_path.write_text(f"""
database:
  url: {db_url!r}
execution:
  batch_size: 10
  live_allowlist_symbols:
    - BTC-USDT
    - ETH-USDT
  qty_precision_by_symbol:
    BTC-USDT: 6
    ETH-USDT: 4
strategies:
  strat-1:
    enabled: true
exchange_profiles:
  paper:
    id: paper
    name: paper
    mode: paper
accounts:
  acc1:
    account_id: acc1
    exchange_profile_id: paper
""")
    app_config = load_app_config(str(config_path))
    assert app_config.execution.live_allowlist_symbols == ["BTC-USDT", "ETH-USDT"]
    assert app_config.execution.qty_precision_by_symbol.get("BTC-USDT") == 6
    assert app_config.execution.qty_precision_by_symbol.get("ETH-USDT") == 4
