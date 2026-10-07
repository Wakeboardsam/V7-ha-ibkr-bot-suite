"""
Each notification has its own switch under `notifications`, all off by default.
These tests check that each switch stops only its own alert, that the Errors
tab is still written when an alert is off, and that the add-on options keep
working after an upgrade from saved 0.1.47 settings.
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from config.schema import AppConfig, NotificationSettings
from engine.engine import GridEngine

ADDON_DIR = Path(__file__).resolve().parents[1]

# Switch -> the event type it controls, for every alert the engine sends
# through a per-alert switch. Fills and startup have their own tests.
ENGINE_SWITCHES = {
    "notify_on_halts": "HALT_RECONCILIATION",
    "notify_on_bridge_halt": "BRIDGE_HALTED",
    "notify_on_reanchor_stalled": "BRIDGE_REANCHOR_STALLED",
    "notify_on_share_mismatch": "SHARE_MISMATCH",
    "notify_on_share_mismatch_cleared": "SHARE_MISMATCH_CLEARED",
    "notify_on_watchdog_restart": "WATCHDOG_RESTART",
    "notify_on_errors": "BOT_ERROR",
    "notify_on_order_submit": "ORDER_PLACED",
}

ALL_SWITCHES = [
    "notify_on_fills", "notify_on_startup_ok", "notify_on_order_submit", "notify_on_halts",
    "notify_on_bridge_halt", "notify_on_reanchor_stalled", "notify_on_share_mismatch",
    "notify_on_share_mismatch_cleared", "notify_on_gateway_login", "notify_on_watchdog_restart",
    "notify_on_errors",
]


def _engine(**switches):
    config = AppConfig(
        google_sheet_id="test_sheet",
        google_credentials_json='{"test": "json"}',
        notifications=NotificationSettings(enabled=True, webhook_url="http://example.invalid/hook", **switches),
    )
    notifier = MagicMock()
    engine = GridEngine(MagicMock(), AsyncMock(), config, notifier=notifier)
    return engine, notifier


async def _drain():
    """Waits for notifications sent off the event loop."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*pending, return_exceptions=True)


async def _trigger_every_alert(engine):
    await engine._halt_for_reconciliation_error(
        code="TEST_HALT", symbol="TQQQ", row=1, action="SELL", details="test halt")
    engine._enter_bridge_halt("test bridge halt")
    await engine._report_bridge_halt()
    engine._bridge_recalc_started_at = datetime.now() - timedelta(seconds=400)
    engine._flush_old_grid_orders_for_reanchor = AsyncMock(return_value=False)
    await engine._bridge_reanchor_ready([])
    engine._notify_share_mismatch(101, 100, "test mismatch")
    engine._share_mismatch = {"broker_shares": 101, "sheet_shares": 100}
    await engine._clear_share_mismatch(100)
    engine._notify_watchdog_restart("test restart")
    engine._notify_error_row("TEST_ERROR", "test error")
    engine._notify_order_placed(kind="grid BUY", action="BUY", row=9, qty=10, price=50.0, order_id=123)
    await _drain()


def _sent(notifier):
    return {c.kwargs.get("event_type") for c in notifier.send.call_args_list}


def test_every_switch_defaults_off():
    settings = NotificationSettings()
    assert settings.enabled is False
    for switch in ALL_SWITCHES:
        assert getattr(settings, switch) is False, switch


@pytest.mark.asyncio
async def test_all_switches_on_sends_every_alert():
    engine, notifier = _engine(**{s: True for s in ALL_SWITCHES})
    await _trigger_every_alert(engine)
    assert _sent(notifier) == set(ENGINE_SWITCHES.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("switch", sorted(ENGINE_SWITCHES))
async def test_each_switch_stops_only_its_own_alert(switch):
    switches = {s: True for s in ALL_SWITCHES}
    switches[switch] = False
    engine, notifier = _engine(**switches)

    await _trigger_every_alert(engine)

    assert _sent(notifier) == set(ENGINE_SWITCHES.values()) - {ENGINE_SWITCHES[switch]}


@pytest.mark.asyncio
async def test_all_switches_off_sends_nothing():
    engine, notifier = _engine()
    await _trigger_every_alert(engine)
    notifier.send.assert_not_called()


@pytest.mark.asyncio
async def test_repeated_error_alerts_once_until_cleared():
    engine, notifier = _engine(notify_on_errors=True)

    engine._notify_error_row("ENGINE_TICK_ERROR", "Engine tick error: boom")
    engine._notify_error_row("ENGINE_TICK_ERROR", "Engine tick error: boom")
    await _drain()
    assert notifier.send.call_count == 1

    engine._notify_error_row("ENGINE_TICK_ERROR", "Engine tick error: other")
    await _drain()
    assert notifier.send.call_count == 2

    # A successful tick clears the code, so the same text alerts again later.
    engine._error_alerts_sent.pop("ENGINE_TICK_ERROR", None)
    engine._notify_error_row("ENGINE_TICK_ERROR", "Engine tick error: other")
    await _drain()
    assert notifier.send.call_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("errors_on", [True, False])
async def test_errors_row_is_written_whether_or_not_the_alert_is_on(errors_on):
    engine, notifier = _engine(notify_on_errors=errors_on)
    engine.broker.get_verified_symbol_snapshot = AsyncMock(return_value=SimpleNamespace(
        snapshot_status="UNAVAILABLE", account_id_masked="DU****", snapshot_error="no data"))

    await engine._log_health_once()
    await engine._log_health_once()
    await _drain()

    codes = [c.kwargs.get("code") for c in engine.sheet.log_error.call_args_list]
    assert codes.count("POSITION_SNAPSHOT_UNAVAILABLE") == 1
    alerts = [c for c in notifier.send.call_args_list if c.kwargs.get("event_type") == "BOT_ERROR"]
    assert len(alerts) == (1 if errors_on else 0)


@pytest.mark.asyncio
async def test_order_placed_alert_is_off_by_default_even_with_notifications_on():
    engine, notifier = _engine()
    engine._notify_order_placed(kind="trim SELL", action="SELL", row=7, qty=3, price=60.0, order_id=5)
    await _drain()
    notifier.send.assert_not_called()


def _supervisor_merge(defaults, saved):
    """Home Assistant Supervisor merges saved options over defaults, recursing into dicts."""
    merged = dict(defaults)
    for key, value in saved.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _supervisor_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def test_upgrade_from_saved_0_1_47_settings_keeps_choices_and_adds_new_switches_off():
    addon = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
    saved = dict(addon["options"])
    saved["notifications"] = {
        "enabled": True, "provider": "home_assistant_webhook", "webhook_url": "http://example.invalid/hook",
        "timeout_seconds": 3.0, "dedupe_window_seconds": 300,
        "notify_on_fills": True, "notify_on_errors": True, "notify_on_halts": True,
        "notify_on_order_submit": False, "notify_on_startup_ok": True,
    }

    merged = _supervisor_merge(addon["options"], saved)["notifications"]

    assert set(merged) == set(addon["schema"]["notifications"])
    for key in ("notify_on_fills", "notify_on_errors", "notify_on_halts", "notify_on_startup_ok"):
        assert merged[key] is True, key
    for key in set(ALL_SWITCHES) - set(saved["notifications"]):
        assert merged[key] is False, key
    NotificationSettings(**merged)


def test_saved_disabled_switches_stay_disabled_after_upgrade():
    addon = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
    saved = {"notifications": {"enabled": True, "notify_on_halts": False, "notify_on_fills": False}}
    merged = _supervisor_merge(addon["options"], saved)["notifications"]
    assert merged["notify_on_halts"] is False
    assert merged["notify_on_fills"] is False


def test_config_yaml_lists_every_switch_off():
    addon = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
    for switch in ALL_SWITCHES:
        assert addon["options"]["notifications"][switch] is False, switch
        assert addon["schema"]["notifications"][switch] == "bool", switch


def test_every_notification_option_has_a_name_and_description():
    addon = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
    translations = yaml.safe_load((ADDON_DIR / "translations" / "en.yaml").read_text())
    section = translations["configuration"]["notifications"]
    assert section["name"] and section["description"]
    for key in addon["schema"]["notifications"]:
        field = section["fields"][key]
        assert field["name"].strip() and field["description"].strip(), key
