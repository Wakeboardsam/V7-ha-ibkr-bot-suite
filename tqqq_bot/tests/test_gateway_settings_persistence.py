"""The Gateway's own settings file (ibg.xml) survives add-on restarts.

The Gateway saves its settings on a schedule IBC sets, run.sh copies them to
/data every few minutes and once more after the Gateway stops, and Home
Assistant waits long enough for that last copy.
"""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ADDON_DIR = Path(__file__).resolve().parents[1]


def run_sh_text() -> str:
    return (ADDON_DIR / "run.sh").read_text()


def shell_function(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", run_sh_text(), re.S | re.M)
    assert match, f"{name} not found in run.sh"
    return match.group(0)


def test_ibc_has_the_gateway_save_its_settings_every_hour():
    template = (ADDON_DIR / "gateway" / "ibc_config.ini.template").read_text()
    assert "SaveTwsSettingsAt=Every 1 hours\n" in template


def test_settings_are_copied_once_more_after_the_gateway_stops():
    handler = shell_function("shutdown_handler")
    gateway_stopped = handler.index('wait "$IBC_PID"')
    final_copy = handler.index("sync_gateway_settings")
    assert gateway_stopped < final_copy
    # Only when the Gateway was started: during the weekend shutdown nothing changed.
    assert 'if [ -n "${IBC_PID:-}" ]; then\n        list_gateway_settings_files "After the Gateway stopped"' in handler
    assert handler.index('echo "Saving Gateway settings') < final_copy


def test_home_assistant_waits_for_the_final_copy():
    config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
    assert config["timeout"] >= 60


def test_run_sh_no_longer_writes_precautions_into_jts_ini():
    # IBC applies BypassOrderPrecautions and BypassRedirectOrderWarning from its
    # own config; jts.ini does not hold them.
    assert "jts.ini" not in run_sh_text()


@pytest.mark.parametrize("with_settings_file, expected", [
    (True, "Saved ibg.xml found in persistent storage"),
    (False, "No saved ibg.xml in persistent storage yet"),
])
def test_startup_reports_whether_the_settings_file_came_back(tmp_path, with_settings_file, expected):
    persist = tmp_path / "persist"
    user_dir = persist / "root_Jts" / "encodedfolder"
    user_dir.mkdir(parents=True)
    (user_dir / "ibg.Sun.xml").write_text("<backup/>")
    if with_settings_file:
        (user_dir / "ibg.xml").write_text("<settings/>")
    script = (
        f'PERSIST_JTS_DIR="{persist}/root_Jts"\n'
        + shell_function("report_saved_gateway_settings").replace("/data/ibgateway/persist", str(persist))
        + "report_saved_gateway_settings"
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
    assert expected in out
    assert "Saved settings size: " in out
    assert "encodedfolder" not in out


def run_listing(tmp_path, jts):
    script = (
        shell_function("list_gateway_settings_files")
        + f'list_gateway_settings_files "Before the Gateway starts" "{jts}"'
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout


def test_listing_shows_each_settings_folder_with_its_files(tmp_path):
    jts = tmp_path / "Jts"
    current = jts / "gcfpedoofahkknlgmede"
    other = jts / "abcdefghijklmnop"
    current.mkdir(parents=True)
    other.mkdir()
    (current / "ibg.Mon.xml").write_text("<backup/>")
    (other / "ibg.xml").write_text("<settings/>")
    (jts / "ibgateway").mkdir()
    out = run_listing(tmp_path, jts)
    assert out.startswith("[Gateway settings] Before the Gateway starts:\n")
    assert "  folder gcfped...:\n    ibg.Mon.xml 9 bytes " in out
    assert "  folder abcdef...:\n    ibg.xml 11 bytes " in out
    # Full folder names come from the login and stay out of the log.
    assert "gcfpedoofahkknlgmede" not in out
    assert "ibgateway" not in out


def test_listing_says_when_there_are_no_settings_files(tmp_path):
    jts = tmp_path / "Jts"
    jts.mkdir()
    assert "  no ibg*.xml files" in run_listing(tmp_path, jts)


def test_listing_runs_before_start_after_login_and_after_stop():
    text = run_sh_text()
    before = text.index('list_gateway_settings_files "Before the Gateway starts"')
    assert before < text.index("/opt/ibc/gatewaystart.sh")
    after_login = text.index('list_gateway_settings_files "After login"')
    assert text.index('echo "Initial Gateway settings sync complete."') < after_login
    handler = shell_function("shutdown_handler")
    assert handler.index('list_gateway_settings_files "After the Gateway stopped"') < handler.index("sync_gateway_settings")


def test_a_half_written_settings_save_is_not_restored():
    restore = next(line for line in run_sh_text().splitlines()
                   if line.startswith('rsync -a') and '"${PERSIST_JTS_DIR}/" "${ACTIVE_JTS_DIR}/"' in line)
    assert "--exclude='ibg.tmp.xml'" in restore


def test_a_half_written_settings_save_is_not_copied_to_data(tmp_path):
    active = tmp_path / "Jts"
    persist = tmp_path / "persist_Jts"
    java = tmp_path / "java"
    persist_java = tmp_path / "persist_java"
    folder = active / "gcfpedoofahkknlgmede"
    folder.mkdir(parents=True)
    java.mkdir()
    (folder / "ibg.xml").write_text("<settings/>")
    (folder / "ibg.tmp.xml").write_text("<half/>")
    script = (
        f'ACTIVE_JTS_DIR="{active}"; PERSIST_JTS_DIR="{persist}"; PERSIST_JAVA_DIR="{persist_java}"\n'
        + shell_function("sync_gateway_settings").replace("/root/.java/", f"{java}/")
        + "sync_gateway_settings"
    )
    subprocess.run(["bash", "-c", script], check=True)
    saved = persist / "gcfpedoofahkknlgmede"
    assert (saved / "ibg.xml").read_text() == "<settings/>"
    assert not (saved / "ibg.tmp.xml").exists()


def run_log_report(tmp_path, username="realuser"):
    jts = tmp_path / "Jts"
    ibc = tmp_path / "ibc"
    script = (
        f'ACTIVE_JTS_DIR="{jts}"; ACTIVE_IBC_DIR="{ibc}"; IBKR_USERNAME="{username}"\n'
        + shell_function("print_gateway_settings_log_lines")
        + 'print_gateway_settings_log_lines "Two minutes after login"'
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout


def test_log_report_prints_settings_lines_with_secrets_masked(tmp_path):
    folder = tmp_path / "Jts" / "gcfpedoofahkknlgmedekopoh"
    folder.mkdir(parents=True)
    logs = tmp_path / "ibc" / "logs"
    logs.mkdir(parents=True)
    (logs / "ibc-3.23.0_GATEWAY-1019_Tuesday.txt").write_text(
        "Loading settings for realuser\n"
        "settings check IbPassword=secret123\n"
        "Saving Tws settings\n"
        "Could not read /root/Jts/gcfpedoofahkknlgmedekopoh/ibg.xml for U1234567\n"
        "unrelated line\n"
    )
    (folder / "ibgateway.Tue.log").write_bytes(b"\x00\x01\x02binary")
    (tmp_path / "Jts" / "launcher.log").write_text("starting\n")
    out = run_log_report(tmp_path)
    assert out.startswith("[Gateway logs] Two minutes after login: settings-related lines\n")
    assert "  logs/ibc-3.23.0_GATEWAY-1019_Tuesday.txt:\n    Loading settings for ****\n" in out
    assert "    Saving Tws settings\n" in out
    assert "/root/Jts/<folder>/ibg.xml for ****" in out
    assert "    Loading settings for ****\n" in out
    assert "    settings check IbPassword=****\n" in out
    assert "  <folder>/ibgateway.Tue.log: not plain text (9 bytes)" in out
    assert "  launcher.log: no matching lines" in out
    for secret in ("secret123", "realuser", "U1234567", "gcfpedoofahkknlgmedekopoh", "unrelated line"):
        assert secret not in out


def test_log_report_runs_after_login_and_after_stop():
    text = run_sh_text()
    assert '(sleep 120; print_gateway_settings_log_lines "Two minutes after login") &' in text
    assert text.index('BOT_PID=$!') < text.index('print_gateway_settings_log_lines "Two minutes after login"')
    handler = shell_function("shutdown_handler")
    assert 'kill -TERM "$LOG_REPORT_PID"' in handler
    assert handler.index('print_gateway_settings_log_lines "After the Gateway stopped"') < handler.index("sync_gateway_settings")
