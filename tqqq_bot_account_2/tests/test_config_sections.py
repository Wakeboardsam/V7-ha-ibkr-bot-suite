"""
The sectioned Configuration page (0.1.54): moving saved settings from the old
flat option names, reading the sections, and run.sh's option and time handling.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from config.loader import flatten_options, load_config
from config.migrate_options import (
    SECTIONS, MigrationError, migrate, needs_migration, run, to_24_hour, to_timezone, warnings_for,
)

ADDON_DIR = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())

# The options as an installed add-on saved them before 0.1.54 (example values).
LEGACY = {
    "active_broker": "ibkr",
    "paper_trading": False,
    "dry_run": False,
    "ibkr_host": "127.0.0.1",
    "ibkr_port": 7497,
    "ibkr_client_id": 1,
    "ibkr_account_id": "DU1234567",
    "google_sheet_id": "example_sheet_id",
    "google_credentials_json": "{\"client_email\": \"bot@example.iam.gserviceaccount.com\"}",
    "poll_interval_seconds": 45,
    "heartbeat_interval_seconds": 60,
    "health_log_interval_seconds": 300,
    "anchor_buy_offset": 1.5,
    "share_mismatch_mode": "warn",
    "max_spread_pct": 0.5,
    "enable_bridge_anchor": True,
    "bridge_max_auto_trim_shares": 5,
    "maintenance_enabled": True,
    "maintenance_start_local": "23:44",
    "maintenance_end_local": "00:00",
    "maintenance_reconnect_grace_minutes": 30,
    "maintenance_cancel_open_orders": True,
    "timezone": "America/Denver",
    "gateway_auto_restart_enabled": False,
    "gateway_auto_restart_time": "11:48 PM",
    "gateway_cold_restart_enabled": True,
    "gateway_cold_restart_time": "06:00 PM",
    "gateway_live_wait_timeout_seconds": 3600,
    "gateway_paper_wait_timeout_seconds": 300,
    "mask_account_ids_in_logs": True,
    "ibkr_username": "example_user",
    "ibkr_password": "example-password-123",
    "trading_mode": "live",
    "readonly_api": False,
    "enable_vnc": False,
    "vnc_port": 5900,
    "notifications": {
        "enabled": True,
        "provider": "home_assistant_webhook",
        "webhook_url": "http://homeassistant.local:8123/api/webhook/example-hook",
        "timeout_seconds": 3.0,
        "dedupe_window_seconds": 300,
        "notify_on_fills": True,
        "notify_on_startup_ok": False,
        "notify_on_order_submit": False,
        "notify_on_halts": True,
        "notify_on_bridge_halt": True,
        "notify_on_reanchor_stalled": False,
        "notify_on_share_mismatch": True,
        "notify_on_share_mismatch_cleared": False,
        "notify_on_gateway_login": True,
        "notify_on_watchdog_restart": False,
        "notify_on_errors": False,
    },
}


def supervisor_stored_after_update(legacy: dict) -> dict:
    """What Supervisor returns as options after the update: new defaults merged with the old saved keys."""
    stored = json.loads(json.dumps(CONFIG["options"]))
    for key, value in legacy.items():
        if key == "notifications":
            stored["notifications"].update(value)
        else:
            stored[key] = value
    return stored


def validate_against_schema(options: dict, schema: dict) -> None:
    """The checks Supervisor makes for the types this add-on uses."""
    assert set(options) == set(schema), (set(options) ^ set(schema))
    for key, typ in schema.items():
        value = options[key]
        if isinstance(typ, dict):
            validate_against_schema(value, typ)
        elif typ == "bool":
            assert isinstance(value, bool), key
        elif typ in ("str", "password"):
            assert isinstance(value, str), key
        elif typ == "port":
            assert isinstance(value, int) and 1 <= value <= 65535, key
        elif typ.startswith("int"):
            assert isinstance(value, int) and not isinstance(value, bool), key
            low = re.match(r"int\((\d+)?,", typ)
            if low and low.group(1):
                assert value >= int(low.group(1)), key
        elif typ.startswith("float"):
            assert isinstance(value, (int, float)) and not isinstance(value, bool), key
            low = re.match(r"float\((\d+)?,", typ)
            if low and low.group(1):
                assert value >= float(low.group(1)), key
        elif typ.startswith("list("):
            assert value in typ[5:-1].split("|"), (key, value)
        elif typ.startswith("match("):
            assert re.fullmatch(typ[6:-1], value), (key, value)
        else:
            raise AssertionError(f"unhandled schema type {typ} for {key}")


# --- the new page ---------------------------------------------------------

def test_page_sections_cover_every_option_once():
    sections = [k for k in CONFIG["schema"] if k != "notifications"]
    assert sections == list(SECTIONS)
    for section, keys in SECTIONS.items():
        assert list(CONFIG["schema"][section]) == keys
        assert list(CONFIG["options"][section]) == keys


def test_default_options_pass_the_schema():
    validate_against_schema(CONFIG["options"], CONFIG["schema"])


def test_a_fresh_install_cannot_trade():
    account = CONFIG["options"]["account"]
    assert account["trading_mode"] == "paper"
    assert account["dry_run"] is True
    assert account["readonly_api"] is True
    assert account["ibkr_account_id"] == "DU1234567"


def test_every_option_has_a_name_and_description():
    translations = yaml.safe_load((ADDON_DIR / "translations" / "en.yaml").read_text())["configuration"]
    for section, fields in CONFIG["schema"].items():
        assert translations[section]["name"] and translations[section]["description"], section
        for key in fields:
            entry = translations[section]["fields"][key]
            assert entry["name"] and entry["description"], f"{section}.{key}"
        assert set(translations[section]["fields"]) == set(fields), section


# --- moving saved settings ------------------------------------------------

def test_saved_settings_move_into_the_sections_unchanged():
    stored = supervisor_stored_after_update(LEGACY)
    assert needs_migration(stored)

    moved, problems = migrate(stored)

    assert problems == []
    validate_against_schema(moved, CONFIG["schema"])
    for section, keys in SECTIONS.items():
        for key in keys:
            expected = LEGACY[key]
            if key == "gateway_auto_restart_time":
                expected = "23:48"
            elif key == "gateway_cold_restart_time":
                expected = "18:00"
            assert moved[section][key] == expected, key
    assert moved["notifications"] == {k: v for k, v in LEGACY["notifications"].items() if k != "provider"}


def test_moved_settings_read_back_as_the_same_bot_configuration(tmp_path):
    moved, _ = migrate(supervisor_stored_after_update(LEGACY))
    path = tmp_path / "options.json"
    path.write_text(json.dumps(moved))

    config = load_config(str(path))

    assert config.trading_mode == "live"
    assert config.paper_trading is False
    assert config.dry_run is False
    assert config.ibkr_account_id == "DU1234567"
    assert config.ibkr_port == 7497
    assert config.ibkr_host == "127.0.0.1"
    assert config.poll_interval_seconds == 45
    assert config.share_mismatch_mode == "warn"
    assert config.google_sheet_id == "example_sheet_id"
    assert config.maintenance_start_local == "23:44"
    assert config.notifications.enabled is True
    assert config.notifications.notify_on_gateway_login is True


def test_new_layout_is_left_alone():
    assert not needs_migration(json.loads(json.dumps(CONFIG["options"])))


def test_trading_mode_decides_when_the_old_settings_disagreed():
    stored = supervisor_stored_after_update({**LEGACY, "paper_trading": True, "trading_mode": "live"})
    assert migrate(stored)[0]["account"]["trading_mode"] == "live"
    assert any("trading_mode" in note for note in warnings_for(stored))


def test_paper_trading_alone_sets_the_mode():
    legacy = {k: v for k, v in LEGACY.items() if k != "trading_mode"}
    stored = supervisor_stored_after_update(legacy)
    stored["account"]["trading_mode"] = "paper"  # the new default
    stored["paper_trading"] = False
    assert migrate(stored)[0]["account"]["trading_mode"] == "live"


@pytest.mark.parametrize("value, expected", [
    ("23:44", "23:44"), ("7:05", "07:05"), ("11:48 PM", "23:48"), ("06:00 PM", "18:00"),
    ("12:00 AM", "00:00"), ("12:30 PM", "12:30"), ("Sunday 06:00 PM", "18:00"), ("9:15 am", "09:15"),
])
def test_old_times_become_24_hour(value, expected):
    assert to_24_hour(value, "t") == expected


@pytest.mark.parametrize("value", ["24:00", "13:00 PM", "noon", "", "7"])
def test_an_unreadable_time_is_not_guessed(value):
    with pytest.raises(MigrationError):
        to_24_hour(value, "t")


def test_time_zone_names_map_to_the_dropdown():
    assert to_timezone("America/Denver") == "America/Denver"
    assert to_timezone("US/Mountain") == "America/Denver"
    with pytest.raises(MigrationError):
        to_timezone("Europe/London")


# --- the start-up step ----------------------------------------------------

class FakeSupervisor:
    def __init__(self, stored, options_result="ok", restart=None):
        self.stored = stored
        self.options_result = options_result
        self.restart = restart or {"result": "ok", "data": {}}
        self.calls = []

    def __call__(self, method, path, token, body=None):
        self.calls.append((method, path, body))
        if path == "/addons/self/info":
            return {"result": "ok", "data": {"options": self.stored}}
        if path == "/addons/self/options":
            if self.options_result == "ok":
                return {"result": "ok", "data": {}}
            return {"result": "error", "message": self.options_result}
        if path == "/addons/self/restart":
            if isinstance(self.restart, Exception):
                raise self.restart
            return self.restart
        raise AssertionError(path)


def test_old_settings_are_saved_in_the_new_layout_then_the_add_on_restarts(tmp_path):
    supervisor = FakeSupervisor(supervisor_stored_after_update(LEGACY))
    lines = []

    status = run("token", call=supervisor, log=lines.append)

    assert status == 3
    assert [c[1] for c in supervisor.calls] == ["/addons/self/info", "/addons/self/options", "/addons/self/restart"]
    sent = supervisor.calls[1][2]["options"]
    validate_against_schema(sent, CONFIG["schema"])
    assert sent["account"]["ibkr_account_id"] == "DU1234567"
    assert not any("example-password-123" in line or "DU1234567" in line for line in lines)


def test_nothing_happens_when_the_settings_are_already_in_sections(tmp_path):
    supervisor = FakeSupervisor(json.loads(json.dumps(CONFIG["options"])))
    assert run("token", call=supervisor, log=lambda *_: None) == 0
    assert [c[1] for c in supervisor.calls] == ["/addons/self/info"]


def test_without_a_supervisor_token_start_up_continues():
    assert run(None, call=None, log=lambda *_: None) == 0


def test_a_refused_save_stops_the_add_on_without_showing_secrets(tmp_path):
    supervisor = FakeSupervisor(
        supervisor_stored_after_update(LEGACY),
        options_result="expected int for dictionary value @ data['account']. Got 'example-password-123'",
    )
    lines = []

    status = run("token", call=supervisor, log=lines.append)

    assert status == 1
    assert "/addons/self/restart" not in [c[1] for c in supervisor.calls]
    assert any("STOPPED" in line for line in lines)
    assert not any("example-password-123" in line for line in lines)


def test_a_value_that_cannot_be_moved_keeps_every_other_setting_and_stops_in_watch_only(tmp_path):
    """
    An old time zone outside the list gets the new default, but the login,
    account, Sheet and every other value are still saved in the sections, so
    correcting that one field on the page loses nothing. The add-on stops
    without restarting, in Watch only until the operator has checked it.
    """
    supervisor = FakeSupervisor(supervisor_stored_after_update({**LEGACY, "timezone": "Europe/London"}))
    lines = []

    status = run("token", call=supervisor, log=lines.append)

    assert status == 1
    assert [c[1] for c in supervisor.calls] == ["/addons/self/info", "/addons/self/options"]
    sent = supervisor.calls[1][2]["options"]
    validate_against_schema(sent, CONFIG["schema"])
    assert sent["schedule"]["timezone"] == "America/Denver"
    assert sent["account"]["dry_run"] is True
    assert sent["account"]["trading_mode"] == "live"
    assert sent["account"]["ibkr_username"] == "example_user"
    assert sent["account"]["ibkr_password"] == "example-password-123"
    assert sent["google_sheet"]["google_sheet_id"] == "example_sheet_id"
    assert sent["advanced"]["poll_interval_seconds"] == 45
    assert any("timezone" in line for line in lines)
    assert any("Watch only" in line for line in lines)
    assert not needs_migration(sent)


def test_an_unreadable_old_time_gets_the_default_and_the_rest_moves():
    moved, problems = migrate(supervisor_stored_after_update({**LEGACY, "gateway_auto_restart_time": "late"}))
    assert moved["schedule"]["gateway_auto_restart_time"] == "23:48"
    assert moved["schedule"]["gateway_cold_restart_time"] == "18:00"
    assert moved["account"]["ibkr_username"] == "example_user"
    assert len(problems) == 1 and "gateway_auto_restart_time" in problems[0]


def placeholder_options(tmp_path, account_id):
    options = json.loads(json.dumps(CONFIG["options"]))
    options["account"]["ibkr_account_id"] = account_id
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options))
    return str(path)


class UnreachableSupervisor:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, token, body=None):
        self.calls.append(path)
        raise ConnectionRefusedError()


def test_an_unreadable_supervisor_stops_an_add_on_still_on_placeholders(tmp_path):
    """After the update the page shows defaults until the move runs; saving it then would discard the old values."""
    lines = []
    status = run("token", call=UnreachableSupervisor(),
                 options_path=placeholder_options(tmp_path, "DU1234567"), log=lines.append)
    assert status == 1
    assert any("do not save the Configuration page" in line for line in lines)


def test_an_unreadable_supervisor_does_not_block_a_configured_add_on(tmp_path):
    supervisor = UnreachableSupervisor()
    status = run("token", call=supervisor, options_path=placeholder_options(tmp_path, "configured_account"), log=lambda *_: None)
    assert status == 0
    assert supervisor.calls == ["/addons/self/info"]


def test_a_supervisor_error_reply_is_treated_like_an_unreadable_one(tmp_path):
    def refuses(method, path, token, body=None):
        return {"result": "error", "message": "403"}
    assert run("token", call=refuses, options_path=placeholder_options(tmp_path, "DU1234567"), log=lambda *_: None) == 1


def test_a_restart_request_cut_off_by_the_restart_waits_for_it(tmp_path):
    supervisor = FakeSupervisor(supervisor_stored_after_update(LEGACY), restart=ConnectionResetError())
    assert run("token", call=supervisor, log=lambda *_: None) == 3


def test_a_refused_restart_stops_the_add_on(tmp_path):
    supervisor = FakeSupervisor(supervisor_stored_after_update(LEGACY), restart={"result": "error", "message": "x"})
    assert run("token", call=supervisor, log=lambda *_: None) == 1


# --- reading the sections -------------------------------------------------

def test_sections_are_read_under_the_bot_option_names():
    flat = flatten_options(json.loads(json.dumps(CONFIG["options"])))
    assert flat["trading_mode"] == "paper" and flat["paper_trading"] is True
    assert flat["ibkr_port"] == 7497
    assert flat["notifications"]["enabled"] is False
    assert not set(SECTIONS) & set(flat)


def test_a_flat_configuration_is_read_as_before():
    flat = {"google_sheet_id": "x", "google_credentials_json": "{}", "paper_trading": True}
    assert flatten_options(flat) is flat


# --- run.sh ---------------------------------------------------------------

def run_sh_function(name: str) -> str:
    text = (ADDON_DIR / "run.sh").read_text()
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
    assert match, name
    return match.group(0)


@pytest.mark.parametrize("value, expected", [
    ("23:48", "11:48 PM"), ("00:05", "12:05 AM"), ("12:00", "12:00 PM"), ("09:30", "09:30 AM"), ("13:07", "01:07 PM"),
])
def test_run_sh_gives_ibc_the_daily_restart_in_12_hour_time(value, expected):
    script = run_sh_function("to_ibc_12_hour") + f'to_ibc_12_hour "{value}"'
    assert subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout == expected


def test_run_sh_keeps_a_saved_false_and_fills_missing_values(tmp_path):
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"schedule": {"gateway_auto_restart_enabled": False}, "account": {}}))
    script = run_sh_function("opt").replace("/data/options.json", str(options)) + (
        "opt '.schedule.gateway_auto_restart_enabled' 'true'; "
        "opt '.account.readonly_api' 'true'; "
        "opt '.account.ibkr_username' '\"\"'; echo end"
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.split("\n")
    assert out[:4] == ["false", "true", "", "end"]


def test_the_real_http_calls_reach_supervisor_with_the_token(tmp_path, monkeypatch):
    """Runs the start-up step against a local HTTP server standing in for Supervisor."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import config.migrate_options as module

    stored = supervisor_stored_after_update(LEGACY)
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            seen.append(("GET", self.path, self.headers.get("Authorization"), None))
            self._reply(200, {"result": "ok", "data": {"options": stored}})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            seen.append(("POST", self.path, self.headers.get("Authorization"), body))
            self._reply(200, {"result": "ok", "data": {}})

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(module, "SUPERVISOR_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        status = module.run("secret-token", log=lambda *_: None)
    finally:
        server.shutdown()

    assert status == 3
    assert [(m, p) for m, p, _, _ in seen] == [
        ("GET", "/addons/self/info"), ("POST", "/addons/self/options"), ("POST", "/addons/self/restart"),
    ]
    assert all(auth == "Bearer secret-token" for _, _, auth, _ in seen)
    validate_against_schema(seen[1][3]["options"], CONFIG["schema"])
