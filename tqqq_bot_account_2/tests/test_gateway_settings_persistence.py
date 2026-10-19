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
    assert 'if [ -n "${IBC_PID:-}" ]; then\n        echo "Saving Gateway settings' in handler


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
