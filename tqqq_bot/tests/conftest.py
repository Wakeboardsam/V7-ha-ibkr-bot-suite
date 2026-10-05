import sys
from unittest.mock import MagicMock
sys.modules['ib_insync'] = MagicMock()

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_bridge_state_file(tmp_path, monkeypatch):
    """Keeps the bridge re-anchor record out of /data and private to each test."""
    import engine.engine as engine_module
    monkeypatch.setattr(engine_module, "BRIDGE_REANCHOR_STATE_PATH", str(tmp_path / "bridge_reanchor_state.json"))


@pytest.fixture
def bridge_config():
    """Engine configuration used by the stateful Bridge Anchor tests."""
    from config.schema import AppConfig
    return AppConfig(
        active_broker="ibkr",
        paper_trading=True,
        ibkr_host="127.0.0.1",
        ibkr_port=7497,
        ibkr_client_id=1,
        ibkr_account_id="DU1234567",
        google_sheet_id="fake_id",
        google_credentials_json="{}",
        anchor_buy_offset=1.5,
        enable_bridge_anchor=True,
        bridge_max_auto_trim_shares=5,
        share_mismatch_mode="halt",
        maintenance_enabled=False,
    )


@pytest.fixture
def regular_session():
    """Pins the trading session so stateful tests do not depend on the wall clock."""
    from engine.engine import GridEngine
    with patch("brokers.ibkr.order_builder.get_dynamic_exchange", return_value="SMART"), \
         patch("brokers.ibkr.order_builder.get_dynamic_tif", return_value="GTC"), \
         patch.object(GridEngine, "_is_session_boundary", return_value=False), \
         patch.object(GridEngine, "_is_in_maintenance_window", return_value=False):
        yield
