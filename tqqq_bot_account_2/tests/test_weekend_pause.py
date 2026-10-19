"""
The weekend bot pause (0.1.56): from a Friday time to a Sunday time the bot and
its Gateway are off. The engine stops when the pause starts, and run.sh waits
it out before starting the Gateway.
"""
import re
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from config.schema import AppConfig
from engine.engine import GridEngine
from utils.weekend_pause import main as weekend_pause_main, pause_end, seconds_until

DENVER = ZoneInfo("America/Denver")
NEW_YORK = ZoneInfo("America/New_York")
ADDON_DIR = Path(__file__).resolve().parents[1]


def denver(*args):
    return datetime(*args, tzinfo=DENVER)


# --- the window -----------------------------------------------------------

@pytest.mark.parametrize("now", [
    denver(2026, 10, 21, 12, 0),   # Wednesday
    denver(2026, 10, 23, 18, 14),  # Friday, a minute before the pause
    denver(2026, 10, 25, 9, 0),    # Sunday, the moment it ends
    denver(2026, 10, 25, 20, 0),   # Sunday evening
    denver(2026, 10, 26, 7, 30),   # Monday
])
def test_outside_the_pause(now):
    assert pause_end(now, "18:15", "09:00") is None


@pytest.mark.parametrize("now", [
    denver(2026, 10, 23, 18, 15),  # Friday, the moment it starts
    denver(2026, 10, 23, 23, 48),  # Friday night
    denver(2026, 10, 24, 0, 30),   # Saturday, after IBKR's weekly logout
    denver(2026, 10, 24, 23, 48),  # Saturday night
    denver(2026, 10, 25, 8, 59),   # Sunday, a minute before it ends
])
def test_inside_the_pause_it_ends_sunday_morning(now):
    assert pause_end(now, "18:15", "09:00") == denver(2026, 10, 25, 9, 0)


def test_the_wait_counts_real_seconds_across_the_daylight_saving_change():
    """Daylight saving ends Sunday 1 November 2026 at 02:00, inside the pause: the night is an hour longer."""
    now = denver(2026, 10, 31, 12, 0)
    end = pause_end(now, "18:15", "09:00")
    assert end == denver(2026, 11, 1, 9, 0)
    assert seconds_until(now, end) == 22 * 3600


def test_the_script_prints_zero_outside_the_pause(capsys):
    with patch("utils.weekend_pause.datetime") as clock:
        clock.now.return_value = denver(2026, 10, 21, 12, 0)
        clock.combine = datetime.combine
        weekend_pause_main(["--timezone", "America/Denver", "--start", "18:15", "--end", "09:00"])
    assert capsys.readouterr().out.strip() == "0"


def test_the_script_prints_the_seconds_left_inside_the_pause(capsys):
    with patch("utils.weekend_pause.datetime") as clock:
        clock.now.return_value = denver(2026, 10, 25, 8, 0)
        clock.combine = datetime.combine
        weekend_pause_main(["--timezone", "America/Denver", "--start", "18:15", "--end", "09:00"])
    assert capsys.readouterr().out.strip() == "3600"


# --- the engine -----------------------------------------------------------

def make_engine(enabled=True):
    config = AppConfig(
        google_sheet_id="test_sheet",
        google_credentials_json="{}",
        poll_interval_seconds=1,
        timezone="America/Denver",
        weekend_pause_enabled=enabled,
        weekend_pause_start_friday="18:15",
        weekend_pause_end_sunday="09:00",
    )
    broker = AsyncMock()
    broker.subscribe_to_executions = MagicMock()
    sheet = AsyncMock()
    engine = GridEngine(broker, sheet, config)
    engine._wait_for_initial_price = AsyncMock()
    engine._log_health_once = AsyncMock()
    engine._tick = AsyncMock(side_effect=lambda: engine._shutdown_event.set())
    return engine


def at(engine, now):
    engine._now_et = lambda: now.astimezone(NEW_YORK)


@pytest.mark.asyncio
async def test_the_engine_stops_when_the_pause_starts():
    engine = make_engine()
    at(engine, denver(2026, 10, 23, 18, 20))

    await engine.run()

    engine._tick.assert_not_called()
    assert engine.weekend_pause_started is True
    engine._log_health_once.assert_awaited_once()
    assert engine._execution_status() == "WEEKEND_SHUTDOWN: back on Sunday 09:00"
    engine.broker.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_the_engine_trades_on_outside_the_pause():
    engine = make_engine()
    at(engine, denver(2026, 10, 23, 18, 10))

    await engine.run()

    engine._tick.assert_awaited_once()
    assert engine.weekend_pause_started is False


@pytest.mark.asyncio
async def test_a_disabled_pause_never_stops_the_engine():
    engine = make_engine(enabled=False)
    at(engine, denver(2026, 10, 24, 12, 0))

    await engine.run()

    engine._tick.assert_awaited_once()
    assert engine.weekend_pause_started is False


@pytest.mark.asyncio
async def test_main_tells_run_sh_the_pause_started():
    import app.main as main_module

    class Exited(Exception):
        pass

    config = MagicMock(active_broker="schwab", dry_run=True)
    with patch.object(main_module, "load_config", return_value=config), \
         patch.object(main_module, "validate_ibkr_settings", return_value=[]), \
         patch.object(main_module, "SheetInterface"), \
         patch.object(main_module, "SchwabAdapter"), \
         patch.object(main_module, "HomeAssistantNotifier"), \
         patch.object(main_module, "GridEngine") as engine_class, \
         patch("sys.exit", side_effect=Exited) as exit_call:
        engine_class.return_value.run = AsyncMock()
        engine_class.return_value.weekend_pause_started = True
        with pytest.raises(Exited):
            await main_module.main()

    exit_call.assert_called_once_with(main_module.WEEKEND_PAUSE_EXIT_CODE)
    assert main_module.WEEKEND_PAUSE_EXIT_CODE == 10


# --- run.sh ---------------------------------------------------------------

def run_sh_text() -> str:
    return (ADDON_DIR / "run.sh").read_text()


def test_run_sh_uses_the_same_exit_code_as_the_bot():
    import app.main as main_module
    assert f"WEEKEND_PAUSE_EXIT_CODE={main_module.WEEKEND_PAUSE_EXIT_CODE}\n" in run_sh_text()


def test_run_sh_waits_out_the_pause_before_starting_the_gateway():
    text = run_sh_text()
    assert text.index('PAUSE_SECONDS=$(weekend_pause_seconds_left)') < text.index("/opt/ibc/gatewaystart.sh")
    assert text.index("trap 'STOP_REQUESTED=true; shutdown_handler'") < text.index('PAUSE_SECONDS=$(weekend_pause_seconds_left)')


@pytest.mark.parametrize("enabled, expected", [("true", "42"), ("false", "0")])
def test_run_sh_asks_the_pause_script_only_when_the_pause_is_on(tmp_path, enabled, expected):
    match = re.search(r"^weekend_pause_seconds_left\(\) \{\n.*?^\}\n", run_sh_text(), re.S | re.M)
    assert match
    fake = tmp_path / "weekend_pause.py"
    fake.write_text("print(42)\n")
    script = (
        f'WEEKEND_PAUSE_ENABLED={enabled}; TIMEZONE=America/Denver; '
        'WEEKEND_PAUSE_START_FRIDAY=18:15; WEEKEND_PAUSE_END_SUNDAY=09:00\n'
        + match.group(0).replace("/app/utils/weekend_pause.py", str(fake))
        + "weekend_pause_seconds_left"
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
    assert out.strip() == expected


def test_ibc_no_longer_gets_a_sunday_cold_restart():
    template = (ADDON_DIR / "gateway" / "ibc_config.ini.template").read_text()
    assert "ColdRestartTime" not in template
    assert "COLD_RESTART" not in run_sh_text()
