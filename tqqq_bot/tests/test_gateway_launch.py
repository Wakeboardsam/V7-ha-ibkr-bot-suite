"""run.sh starts IBC's launcher directly with the values gatewaystart.sh used to set."""
import re
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parents[1]


def launch_command() -> str:
    text = (ADDON_DIR / "run.sh").read_text()
    match = re.search(r"^APP=GATEWAY .*?displaybannerandlaunch\.sh < /dev/null &\nIBC_PID=\$!$", text, re.S | re.M)
    assert match, "IBC launch command not found in run.sh"
    return match.group(0)


def test_ibc_launcher_gets_the_values_gatewaystart_used_to_set():
    command = launch_command()
    for setting in (
        "TWS_MAJOR_VRSN=1019",
        "IBC_PATH=/opt/ibc",
        'IBC_INI="${IBC_CONFIG_FILE}"',
        'TWS_PATH="${ACTIVE_JTS_DIR}"',
        # Empty: IBC takes the trading mode from config.ini and keeps the
        # settings in TWS_PATH, as before.
        'TWS_SETTINGS_PATH=""',
        'TRADING_MODE=""',
        'LOG_PATH="${ACTIVE_IBC_DIR}/logs"',
        "JAVA_PATH=/opt/ibgateway_jre/bin",
        # A missed 2FA push ends IBC; the add-on's Gateway timeout then restarts it.
        "TWOFA_TIMEOUT_ACTION=exit",
    ):
        assert setting in command


def test_gatewaystart_is_no_longer_used_or_patched():
    assert "/opt/ibc/gatewaystart.sh" not in (ADDON_DIR / "run.sh").read_text()
    assert "gatewaystart.sh" not in (ADDON_DIR / "Dockerfile").read_text()
