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


def pinned_session_now():
    """A Wednesday in the middle of the session that started Tuesday 20:00 ET."""
    import zoneinfo
    from datetime import datetime
    return datetime(2026, 10, 7, 11, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York"))


@pytest.fixture(autouse=True)
def pinned_session_clock(request, monkeypatch):
    """
    Runs every tick's session-boundary check against a fixed weekday clock, with
    the current session already set up, as a bot that has been running since the
    session opened would be. Tests that exercise the boundary move the clock
    through this fixture's value, or opt out with @pytest.mark.real_session_clock.
    """
    if request.node.get_closest_marker("real_session_clock"):
        yield
        return
    import engine.engine
    clock = {"now": pinned_session_now()}
    # Some tests import the engine as app.engine.engine, a separate module copy.
    modules = {sys.modules[name] for name in ("engine.engine", "app.engine.engine") if name in sys.modules}
    for module in modules:
        engine_class = module.GridEngine
        original_init = engine_class.__init__

        def init_with_session_set_up(self, *args, _original_init=original_init, **kwargs):
            _original_init(self, *args, **kwargs)
            self._last_grid_regeneration = clock["now"]

        monkeypatch.setattr(engine_class, "__init__", init_with_session_set_up)
        monkeypatch.setattr(engine_class, "_now_et", lambda self: clock["now"])
    yield clock
