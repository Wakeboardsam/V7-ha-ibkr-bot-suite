"""
One-time move of saved add-on settings from the old flat option names into the
sectioned Configuration page (add-on version 0.1.54).

Home Assistant Supervisor keeps the settings a user saved under their old names
when an add-on update changes its schema; it only leaves them out of
/data/options.json. On start, run.sh calls this script before anything else. It
reads the saved settings through the Supervisor API, and when they still use
the old names it saves them back in the new sections and asks Supervisor to
restart the add-on, which then starts with the user's own values.

Exit codes for run.sh:
  0  nothing to move (fresh install, already moved, or no Supervisor API)
  3  settings moved and a restart was requested; stop and wait for it
  1  old settings were found but could not be moved; stop before IBKR
This file uses only the standard library.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

SUPERVISOR_URL = "http://supervisor"
BACKUP_PATH = "/data/options_before_sections.json"

# New section -> option names, in page order. Option names are unchanged.
SECTIONS = {
    "account": [
        "trading_mode", "ibkr_account_id", "ibkr_username", "ibkr_password",
        "dry_run", "readonly_api",
    ],
    "google_sheet": ["google_sheet_id", "google_credentials_json"],
    "strategy": [
        "enable_bridge_anchor", "anchor_buy_offset", "bridge_max_auto_trim_shares",
        "share_mismatch_mode", "max_spread_pct",
    ],
    "schedule": [
        "timezone", "maintenance_enabled", "maintenance_start_local", "maintenance_end_local",
        "maintenance_cancel_open_orders", "gateway_auto_restart_enabled", "gateway_auto_restart_time",
        "gateway_cold_restart_enabled", "gateway_cold_restart_time",
    ],
    "advanced": [
        "ibkr_port", "ibkr_client_id", "poll_interval_seconds", "heartbeat_interval_seconds",
        "health_log_interval_seconds", "maintenance_reconnect_grace_minutes",
        "gateway_live_wait_timeout_seconds", "gateway_paper_wait_timeout_seconds",
        "mask_account_ids_in_logs", "enable_vnc", "vnc_port",
    ],
}

# Old top-level options that leave the page. paper_trading is replaced by
# trading_mode, which is what the Gateway login always used.
DROPPED = {"active_broker", "paper_trading", "ibkr_host"}
DROPPED_NOTIFICATION_KEYS = {"provider"}

TIME_OPTIONS = {
    "maintenance_start_local", "maintenance_end_local",
    "gateway_auto_restart_time", "gateway_cold_restart_time",
}

TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
    "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
]
TIMEZONE_ALIASES = {
    "US/Eastern": "America/New_York", "EST5EDT": "America/New_York", "America/Detroit": "America/New_York",
    "US/Central": "America/Chicago", "CST6CDT": "America/Chicago",
    "US/Mountain": "America/Denver", "MST7MDT": "America/Denver", "America/Boise": "America/Denver",
    "US/Arizona": "America/Phoenix", "MST": "America/Phoenix",
    "US/Pacific": "America/Los_Angeles", "PST8PDT": "America/Los_Angeles",
    "US/Alaska": "America/Anchorage",
    "US/Hawaii": "Pacific/Honolulu", "HST": "Pacific/Honolulu",
}

LEGACY_KEYS = {key for keys in SECTIONS.values() for key in keys} | DROPPED


class MigrationError(Exception):
    """An old setting cannot be carried over as it is."""


def to_24_hour(value, name: str) -> str:
    """'23:44', '7:05', '11:48 PM' or 'Sunday 06:00 PM' -> 'HH:MM'."""
    text = str(value).strip()
    weekday = re.match(r"^[A-Za-z]+day\s+(.*)$", text)
    if weekday:
        text = weekday.group(1).strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\s*([AaPp])\.?[Mm]\.?)?", text)
    if not match:
        raise MigrationError(f"{name} is not a time ({value!r}); enter it as HH:MM")
    hour, minute, half = int(match.group(1)), int(match.group(2)), match.group(3)
    if half:
        if not 1 <= hour <= 12:
            raise MigrationError(f"{name} is not a valid 12-hour time ({value!r})")
        hour = hour % 12 + (12 if half.lower() == "p" else 0)
    if hour > 23 or minute > 59:
        raise MigrationError(f"{name} is not a valid time ({value!r})")
    return f"{hour:02d}:{minute:02d}"


def to_timezone(value) -> str:
    text = str(value).strip()
    if text in TIMEZONES:
        return text
    if text in TIMEZONE_ALIASES:
        return TIMEZONE_ALIASES[text]
    raise MigrationError(
        f"timezone {text!r} is not one of the US time zones on the new page; choose one under Time zone and schedule"
    )


def needs_migration(stored: dict) -> bool:
    return any(key in stored for key in LEGACY_KEYS)


def migrate(stored: dict) -> dict:
    """
    Returns the new sectioned options from the saved options. Values saved under
    the old names win over the new sections' defaults; a value already saved in
    a section is kept when no old value exists for it.
    """
    result: dict = {}
    for section, keys in SECTIONS.items():
        current = stored.get(section)
        values = dict(current) if isinstance(current, dict) else {}
        for key in keys:
            if key in stored:
                values[key] = stored[key]
        result[section] = values

    notifications = stored.get("notifications")
    if isinstance(notifications, dict):
        result["notifications"] = {
            k: v for k, v in notifications.items() if k not in DROPPED_NOTIFICATION_KEYS
        }

    account = result["account"]
    if "trading_mode" not in stored and "paper_trading" in stored:
        account["trading_mode"] = "paper" if stored["paper_trading"] else "live"
    if account.get("trading_mode") not in ("paper", "live"):
        raise MigrationError(f"trading_mode {account.get('trading_mode')!r} must be paper or live")

    schedule = result["schedule"]
    for key in TIME_OPTIONS:
        if key in schedule:
            schedule[key] = to_24_hour(schedule[key], key)
    if "timezone" in schedule:
        schedule["timezone"] = to_timezone(schedule["timezone"])

    return result


def warnings_for(stored: dict) -> list[str]:
    """Differences between old settings that the move resolves, for the log."""
    notes = []
    if "paper_trading" in stored and "trading_mode" in stored:
        implied = "paper" if stored["paper_trading"] else "live"
        if implied != stored["trading_mode"]:
            notes.append(
                f"paper_trading said {implied} but trading_mode said {stored['trading_mode']}; "
                f"the Gateway always used trading_mode, so Trading mode is {stored['trading_mode']}."
            )
    host = stored.get("ibkr_host")
    if host not in (None, "127.0.0.1", "localhost"):
        notes.append("ibkr_host was not 127.0.0.1; it was already ignored and is now removed.")
    return notes


def redact(text: str, stored: dict) -> str:
    """Removes every saved string value of four or more characters from text."""
    values = []

    def collect(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                collect(v)
        elif isinstance(obj, str) and len(obj) >= 4:
            values.append(obj)

    collect(stored)
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, "[hidden]")
    return text


def _call(method: str, path: str, token: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{SUPERVISOR_URL}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode() or "{}")
        except ValueError:
            return {"result": "error", "message": f"HTTP {e.code}"}


def run(token: str | None, call=_call, backup_path: str = BACKUP_PATH, log=print) -> int:
    if not token:
        log("[Settings] No Supervisor API token; saved settings were not checked for the old layout.")
        return 0

    try:
        info = call("GET", "/addons/self/info", token)
    except Exception as e:
        log(f"[Settings] Could not read saved settings from Supervisor ({type(e).__name__}); continuing.")
        return 0
    if info.get("result") != "ok":
        log("[Settings] Supervisor did not return saved settings; continuing.")
        return 0

    stored = (info.get("data") or {}).get("options") or {}
    if not needs_migration(stored):
        return 0

    log("[Settings] Saved settings use the old layout. Moving them into the new sections.")
    try:
        new_options = migrate(stored)
    except MigrationError as e:
        log(f"[Settings] STOPPED before connecting to IBKR: {redact(str(e), stored)}.")
        log("[Settings] Open the add-on's Configuration tab, fill in that setting, save and start the add-on.")
        return 1
    for note in warnings_for(stored):
        log(f"[Settings] {note}")

    try:
        fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(stored, f, indent=2)
        log(f"[Settings] A copy of the old settings is in {backup_path} inside the add-on.")
    except OSError as e:
        log(f"[Settings] Could not write the backup copy ({type(e).__name__}); continuing with the move.")

    try:
        saved = call("POST", "/addons/self/options", token, {"options": new_options})
    except Exception as e:
        saved = {"result": "error", "message": type(e).__name__}
    if saved.get("result") != "ok":
        reason = redact(str(saved.get("message", "unknown error")), stored)
        log(f"[Settings] STOPPED before connecting to IBKR: Supervisor refused the moved settings ({reason}).")
        log("[Settings] Open the add-on's Configuration tab, re-enter your settings, save and start the add-on.")
        return 1

    log("[Settings] Settings saved in the new layout. Restarting the add-on once to apply them.")
    try:
        restarted = call("POST", "/addons/self/restart", token)
    except Exception:
        # The restart stops this container, so the request can end without a reply.
        log("[Settings] Restart requested. If the add-on has not restarted within a minute, start it again.")
        return 3
    if restarted.get("result") != "ok":
        log("[Settings] STOPPED: the settings are saved, but the restart request failed. Start the add-on again.")
        return 1
    return 3


if __name__ == "__main__":
    sys.exit(run(os.environ.get("SUPERVISOR_TOKEN")))
