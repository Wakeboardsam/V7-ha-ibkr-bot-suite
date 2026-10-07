"""
Follow-up to the Bridge Anchor re-anchor fix:

  1. Health reports the engine's real execution state.
  2. Health's order comparison understands bridge and trim orders.
  3. A restart in the middle of a re-anchor resumes from saved evidence.
  4. An old-grid BUY that fills before its cancel lands stays accounted for.

Everything runs through the real engine tick, order callbacks, Sheet sync and
Health writer, against the stateful fakes in bridge_fakes.py.
"""
import json
import os
from unittest.mock import MagicMock

import pytest

from config.schema import NotificationSettings
from engine.engine import GridEngine
from tests.bridge_fakes import (
    NEW_GRID, FakeBroker, FakeSheet, bridge_fires, buys_match_sheet, friday_state,
    health_row, run_ticks, track_all,
)

pytestmark = pytest.mark.usefixtures("regular_session")


@pytest.fixture
def config(bridge_config):
    bridge_config.notifications = NotificationSettings(
        # The switches that notify_on_halts alone covered before each alert had its own.
        enabled=True, webhook_url="http://example.invalid/hook", notify_on_halts=True, notify_on_bridge_halt=True, notify_on_reanchor_stalled=True,
        notify_on_share_mismatch=True, notify_on_share_mismatch_cleared=True)
    return bridge_config


def events(notifier, event_type):
    return [c for c in notifier.send.call_args_list if c.kwargs.get("event_type") == event_type]


def mismatch_state(config, notifier, position=126):
    """Two rows owned, broker one share above the Tracker (the 2026-10-02 end state)."""
    broker = FakeBroker(position=position)
    broker.seed_order("986", "SELL", 64, 83.87)
    sheet = FakeSheet({7: "WORKING_SELL:986", 8: "OWNED:820"})
    sheet.grid = NEW_GRID
    engine = GridEngine(broker, sheet, config, notifier=notifier)
    engine._startup_ok_notification_sent = True
    engine.last_broker_shares = position
    track_all(engine, broker, [(7, "986", "SELL")])
    return broker, sheet, engine


# --------------------------------------------------------------------------
# 1. Health reports the actual execution state
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_shows_pause_during_share_mismatch_and_running_after_verified_recovery(config):
    notifier = MagicMock()
    broker, sheet, engine = mismatch_state(config, notifier)

    await run_ticks(engine, 3)
    row = await health_row(engine, sheet)

    assert row["status"] == "PAUSED_SHARE_MISMATCH: broker 126, tracker 125"
    assert row["snapshot_status"] == "OK", "broker data availability is reported separately"
    assert engine._halted_reconciliation is False, "an ordinary mismatch must stay recoverable"
    assert broker.event_index("place") is None

    # Errors rows and the notification describe the same condition.
    breaker_rows = [r for r in sheet.error_rows if r["code"] == "SHARE_MISMATCH"]
    assert breaker_rows and all(r["bot_status"] == row["status"] for r in breaker_rows)
    assert len(events(notifier, "SHARE_MISMATCH")) == 1
    assert events(notifier, "SHARE_MISMATCH")[0].kwargs["extra"]["bot_status"] == row["status"]

    # Operator sells the extra share. Until a tick verifies it, Health must not change.
    broker.position = 125
    assert (await health_row(engine, sheet))["status"] == "PAUSED_SHARE_MISMATCH: broker 126, tracker 125"

    await run_ticks(engine, 2)
    row = await health_row(engine, sheet)
    assert row["status"] == "Running"

    cleared = [r for r in sheet.error_rows if r["code"] == "SHARE_MISMATCH_CLEARED"]
    assert len(cleared) == 1 and cleared[0]["bot_status"] == "Running" and cleared[0]["severity"] == "INFO"
    assert len(events(notifier, "SHARE_MISMATCH_CLEARED")) == 1
    # Trading really resumed: the unprotected row 8 now has its SELL.
    assert (61, 83.03) in [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")]


@pytest.mark.asyncio
async def test_halt_mode_mismatch_writes_one_errors_row_and_one_alert_per_distinct_mismatch(config):
    notifier = MagicMock()
    broker, sheet, engine = mismatch_state(config, notifier)

    def mismatch_rows():
        return [r for r in sheet.error_rows if r["code"] == "SHARE_MISMATCH"]

    await run_ticks(engine, 5)
    assert len(mismatch_rows()) == 1, "the same mismatch is written once, not every tick"
    alerts = events(notifier, "SHARE_MISMATCH")
    assert len(alerts) == 1
    assert alerts[0].kwargs["severity"] == "critical", "sent as a high-importance alert"
    assert "No orders are being placed" in alerts[0].kwargs["message"]

    # A different mismatch is a new event: one more row and one more alert.
    broker.position = 127
    await run_ticks(engine, 3)
    assert len(mismatch_rows()) == 2
    assert len(events(notifier, "SHARE_MISMATCH")) == 2

    # After a verified recovery, the same counts recurring are reported again.
    broker.position = 125
    await run_ticks(engine, 2)
    broker.position = 126
    await run_ticks(engine, 3)
    assert len(mismatch_rows()) == 3
    assert len(events(notifier, "SHARE_MISMATCH")) == 3


@pytest.mark.asyncio
async def test_halt_mode_mismatch_errors_row_is_retried_after_a_failed_write(config):
    notifier = MagicMock()
    broker, sheet, engine = mismatch_state(config, notifier)
    sheet.fail_error_writes = 1

    await run_ticks(engine, 1)
    assert [r for r in sheet.error_rows if r["code"] == "SHARE_MISMATCH"] == []

    await run_ticks(engine, 3)
    assert len([r for r in sheet.error_rows if r["code"] == "SHARE_MISMATCH"]) == 1


@pytest.mark.asyncio
async def test_health_shows_limited_trading_in_warn_mode(config):
    config.share_mismatch_mode = "warn"
    notifier = MagicMock()
    broker, sheet, engine = mismatch_state(config, notifier)

    await run_ticks(engine, 3)
    row = await health_row(engine, sheet)

    assert row["status"] == "LIMITED_SHARE_MISMATCH: broker 126, tracker 125"
    assert engine._halted_reconciliation is False
    # warn mode keeps SELLs working and places no BUYs.
    assert (61, 83.03) in [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")]
    assert broker.live(action="BUY") == []
    assert "SELLs continue" in events(notifier, "SHARE_MISMATCH")[0].kwargs["message"]

    broker.position = 125
    await run_ticks(engine, 2)
    assert (await health_row(engine, sheet))["status"] == "Running"


@pytest.mark.asyncio
async def test_health_shows_bridge_wait_then_trim_wait_then_running(config):
    broker, sheet, engine = friday_state(config)
    broker.fill_marketable_sells = False        # keep the trim working so the wait is visible
    await run_ticks(engine, 1)
    assert (await health_row(engine, sheet))["status"] == "Running"

    await bridge_fires(broker)
    await run_ticks(engine, 1)
    assert (await health_row(engine, sheet))["status"] == "WAITING_BRIDGE_RECALC"

    await run_ticks(engine, 1)                  # second identical read: trim placed
    trim = [o for o in broker.live(action="SELL") if o["qty"] == 1]
    assert len(trim) == 1
    await run_ticks(engine, 1)
    row = await health_row(engine, sheet)
    assert row["status"] == "WAITING_TRIM"
    assert row["order_match_status"] == "MATCH", "a 1-share trim is not compared with row 7's 64 shares"

    broker.fill(trim[0]["order_id"], price=82.06)
    await run_ticks(engine, 3)
    assert (await health_row(engine, sheet))["status"] == "Running"
    assert broker.position == 64


@pytest.mark.asyncio
async def test_health_shows_terminal_reconciliation_halt(config):
    notifier = MagicMock()
    broker, sheet, engine = mismatch_state(config, notifier, position=125)
    await engine._halt_for_reconciliation_error(
        code="SELL_POSITION_MISMATCH_HALT", symbol="TQQQ", row=7, action="SELL", details="test halt")
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"

    await run_ticks(engine, 3)                  # a latched halt does not clear by itself
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"


@pytest.mark.asyncio
async def test_health_keeps_dry_run_designation_when_running(config):
    config.dry_run = True
    broker, sheet, engine = mismatch_state(config, MagicMock(), position=125)
    await run_ticks(engine, 1)
    assert (await health_row(engine, sheet))["status"] == "Running (Mode=DRY_RUN)"


@pytest.mark.asyncio
async def test_health_shows_maintenance_pause(config):
    from unittest.mock import patch
    broker, sheet, engine = mismatch_state(config, MagicMock(), position=125)
    with patch.object(GridEngine, "_is_in_maintenance_window", return_value=True):
        await run_ticks(engine, 1)
        assert (await health_row(engine, sheet))["status"] == "PAUSED_MAINTENANCE"
    assert (await health_row(engine, sheet))["status"] == "Running"


@pytest.mark.asyncio
async def test_released_old_buy_that_secretly_filled_is_not_trimmed(config):
    """
    An old BUY vanishes from the broker with no callback and is released. If
    the position then shows more excess than the bridge fill explains, the
    shares are not sold, whatever the trim limit.
    """
    config.bridge_max_auto_trim_shares = 100
    notifier = MagicMock()
    broker, sheet, engine = friday_state(config, notifier)
    engine._startup_ok_notification_sent = True
    await run_ticks(engine, 1)
    broker.orders.pop("820")                    # gone, no callback...
    await bridge_fires(broker)
    broker.position += 62                       # ...because it filled
    await run_ticks(engine, 8)

    assert engine._bridge_state == "BRIDGE_HALTED"
    assert broker.event_index("place") is None and broker.position == 127
    assert (await health_row(engine, sheet))["status"] == \
        "BRIDGE_HALTED: broker 127 vs tracker 64, old BUY 820 may have filled unreported"
    assert len(events(notifier, "BRIDGE_HALTED")) == 1


# --------------------------------------------------------------------------
# 2. Health order comparison for bridge and trim orders
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_valid_bridge_order_is_a_match(config):
    broker, sheet, engine = friday_state(config)    # includes bridge 818: 65 @ stop 82.52 / limit 84.02
    await run_ticks(engine, 1)
    row = await health_row(engine, sheet)
    assert row["order_match_status"] == "MATCH"
    assert row["unmatched_broker_orders"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("limit_price", 90.00),     # limit is not sell target + offset
    ("aux_price", 81.00),       # stop is not the sell target
    ("qty", 60),                # not row 7's share count
    ("order_type", "LMT"),      # not a stop-limit
    ("action", "SELL"),         # wrong side
])
async def test_health_bridge_order_with_wrong_terms_is_flagged(config, field, value):
    broker, sheet, engine = friday_state(config)
    await engine._tick()
    broker.orders["818"][field] = value
    row = await health_row(engine, sheet)
    assert row["order_match_status"] == "MISMATCH"
    assert row["unmatched_broker_orders"] == "818"


@pytest.mark.asyncio
async def test_health_trim_order_with_wrong_quantity_is_flagged(config):
    broker, sheet, engine = friday_state(config)
    broker.fill_marketable_sells = False
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 3)
    trim = next(o for o in broker.live(action="SELL") if o["qty"] == 1)
    assert (await health_row(engine, sheet))["order_match_status"] == "MATCH"

    broker.orders[trim["order_id"]]["qty"] = 3
    row = await health_row(engine, sheet)
    assert row["order_match_status"] == "MISMATCH"
    assert row["unmatched_broker_orders"] == trim["order_id"]


# --------------------------------------------------------------------------
# 3. Restart during a re-anchor
# --------------------------------------------------------------------------

async def run_until_just_before_trim(config, lose_cancels=()):
    """Bridge filled, anchor written, Sheet recalculated to 64, trim not yet placed."""
    broker, sheet, engine = friday_state(config)
    broker.lose_next_cancel = set(lose_cancels)
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 1)
    assert engine._bridge_state == "ANCHOR_RECALC_PENDING"
    assert broker.position == 65 and sheet.grid[7][2] == 64
    assert broker.event_index("place") is None
    return broker, sheet, engine


def restart(broker, sheet, config, notifier=None):
    """A new process: nothing tracked, no bridge state in memory, same data folder."""
    engine = GridEngine(broker, sheet, config, notifier=notifier)
    engine._startup_ok_notification_sent = True
    return engine


@pytest.mark.asyncio
async def test_restart_before_trim_resumes_reanchor_from_saved_record(config):
    broker, sheet, old_engine = await run_until_just_before_trim(config)
    assert os.path.exists(old_engine._bridge_state_path)
    assert sheet.statuses[7] == "OWNED:818"

    engine = restart(broker, sheet, config)
    await run_ticks(engine, 1)
    assert (await health_row(engine, sheet))["status"] == "WAITING_BRIDGE_RECALC"

    await run_ticks(engine, 6)

    assert broker.event_index("place", lambda e: e[2] == "SELL" and e[3] == 1) is not None, "the 1-share trim"
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]
    assert buys_match_sheet(broker, NEW_GRID) == []
    assert not [e for e in sheet.errors if "CIRCUIT BREAKER" in e]
    assert not os.path.exists(engine._bridge_state_path), "record is removed once the re-anchor is done"
    assert (await health_row(engine, sheet))["status"] == "Running"


@pytest.mark.asyncio
async def test_restart_with_old_buys_still_working_cancels_them_before_resuming(config):
    broker, sheet, _ = await run_until_just_before_trim(config, lose_cancels=("820", "762", "253"))
    assert {"820", "762", "253"} <= set(broker.orders)

    engine = restart(broker, sheet, config)
    await run_ticks(engine, 8)

    assert not {"820", "762", "253"} & set(broker.orders)
    assert broker.position == 64
    assert buys_match_sheet(broker, NEW_GRID) == []
    assert engine._halted_reconciliation is False


@pytest.mark.asyncio
async def test_restart_without_record_pauses_and_never_trims_on_a_share_difference(config):
    broker, sheet, old_engine = await run_until_just_before_trim(config)
    os.remove(old_engine._bridge_state_path)
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 5)

    assert engine._bridge_state != "ANCHOR_RECALC_PENDING"
    assert broker.event_index("place") is None, "no trim and no SELL without evidence of a bridge fill"
    assert broker.position == 65
    assert (await health_row(engine, sheet))["status"] == "PAUSED_SHARE_MISMATCH: broker 65, tracker 64"
    assert len(events(notifier, "SHARE_MISMATCH")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["other_account", "other_order", "corrupt"])
async def test_restart_ignores_a_record_that_does_not_match(config, tamper):
    broker, sheet, old_engine = await run_until_just_before_trim(config)
    path = old_engine._bridge_state_path
    record = json.load(open(path))
    if tamper == "other_account":
        record["account"] = "0" * 16
    elif tamper == "other_order":
        record["bridge_order_id"] = "111"
    with open(path, "w") as f:
        f.write("{not json" if tamper == "corrupt" else json.dumps(record))

    engine = restart(broker, sheet, config, MagicMock())
    await run_ticks(engine, 4)

    assert engine._bridge_state != "ANCHOR_RECALC_PENDING"
    assert broker.event_index("place") is None
    assert (await health_row(engine, sheet))["status"].startswith("PAUSED_SHARE_MISMATCH")
    if tamper == "other_order":
        assert not os.path.exists(path), "a record for another order is discarded after two reads"


@pytest.mark.asyncio
async def test_restart_recovery_survives_one_bad_read_of_row_7(config):
    """A single blank read of row 7 at startup must not throw the evidence away."""
    broker, sheet, _ = await run_until_just_before_trim(config)
    engine = restart(broker, sheet, config)

    sheet.statuses[7] = ""                      # transient blank cell
    await run_ticks(engine, 1)
    assert broker.event_index("place") is None and broker.event_index("cancel_lost") is None
    assert os.path.exists(engine._bridge_state_path)

    sheet.statuses[7] = "OWNED:818"
    await run_ticks(engine, 6)
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]


@pytest.mark.asyncio
async def test_restart_with_old_buy_that_filled_while_down_halts_instead_of_trimming(config):
    """
    The Tracker still lists BUY 820 but the broker no longer has it, and the
    position is 62 shares higher. Even with a trim limit large enough to cover
    it, those shares are not sold: the bridge fill explains only one of them.
    """
    config.bridge_max_auto_trim_shares = 100
    broker, sheet, _ = await run_until_just_before_trim(config, lose_cancels=("820",))
    sheet.statuses[8] = "WORKING_BUY:820"       # the status as the dead process left it
    broker.orders.pop("820")                    # filled while the bot was down
    broker.position = 127
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 6)

    assert engine._bridge_state == "BRIDGE_HALTED"
    assert broker.event_index("place") is None and broker.position == 127
    status = (await health_row(engine, sheet))["status"]
    assert status == "BRIDGE_HALTED: broker 127 vs tracker 64, old BUY 820 may have filled unreported"
    assert len(events(notifier, "BRIDGE_HALTED")) == 1


@pytest.mark.asyncio
async def test_restart_with_old_buy_gone_and_only_bridge_excess_resumes(config):
    """Same stale Tracker status, but the position shows only the bridge's one extra share."""
    broker, sheet, _ = await run_until_just_before_trim(config, lose_cancels=("820",))
    sheet.statuses[8] = "WORKING_BUY:820"
    broker.orders.pop("820")                    # cancelled while the bot was down

    engine = restart(broker, sheet, config)
    await run_ticks(engine, 8)

    assert engine._bridge_state != "BRIDGE_HALTED"
    assert broker.position == 64
    assert buys_match_sheet(broker, NEW_GRID) == []


@pytest.mark.asyncio
async def test_restart_recovery_that_cannot_reconcile_halts_and_notifies(config):
    """Record is valid, but the broker holds far more than the trim limit allows."""
    broker, sheet, _ = await run_until_just_before_trim(config)
    broker.position = 80
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 6)

    assert engine._bridge_state == "BRIDGE_HALTED"
    assert broker.event_index("place") is None
    status = (await health_row(engine, sheet))["status"]
    assert status == "BRIDGE_HALTED: broker 80 vs tracker 64, excess 16 is above the trim limit"
    assert len(events(notifier, "BRIDGE_HALTED")) == 1
    assert events(notifier, "SHARE_MISMATCH") == [], "the bridge halt is the one reported condition"

    # A halted re-anchor is the operator's to finish: a second restart must not resume and trim.
    assert not os.path.exists(engine._bridge_state_path)
    broker.position = 66
    again = restart(broker, sheet, config, MagicMock())
    await run_ticks(again, 5)
    assert again._bridge_state != "ANCHOR_RECALC_PENDING"
    assert broker.event_index("place") is None and broker.position == 66
    assert (await health_row(again, sheet))["status"] == "PAUSED_SHARE_MISMATCH: broker 66, tracker 64"


# --------------------------------------------------------------------------
# 4. An old-grid BUY fills before its cancel completes
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_old_buy_fills_in_full_while_cancel_is_pending(config):
    """
    Order 820 fills for 62 shares after the Tracker's row 8 became 61. All 62
    shares stay accounted for: row 8 is owned, and the two shares the broker
    holds above the Tracker (one from the bridge, one from 820) are sold by a
    trim that is within the trim limit.
    """
    notifier = MagicMock()
    broker, sheet, engine = friday_state(config, notifier)
    engine._startup_ok_notification_sent = True
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 1)
    assert "820" in broker.orders and sheet.grid[8] == NEW_GRID[8]

    broker.fill("820", price=80.39)             # 62 shares; position 127
    await run_ticks(engine, 8)

    assert broker.event_index("fill", lambda e: e[1] == "820" and e[3] == 62) is not None
    assert sheet.statuses[8].startswith("WORKING_SELL:"), "row 8 is owned, not dropped"
    trims = [e for e in broker.events if e[0] == "place" and e[2] == "SELL" and e[3] == 2]
    assert len(trims) == 1, "exactly the two excess shares are trimmed"
    assert broker.position == NEW_GRID[7][2] + NEW_GRID[8][2] == 125
    assert sorted((o["qty"], o["limit_price"]) for o in broker.live(action="SELL")) == [(61, 83.03), (64, 83.87)]
    assert broker.live(action="BUY", order_type="STP LMT") == [], "no bridge while two rows are owned"
    assert not [e for e in sheet.errors if "CIRCUIT BREAKER" in e]
    assert engine._bridge_state != "BRIDGE_HALTED" and engine._halted_reconciliation is False
    assert (await health_row(engine, sheet))["status"] == "Running"


@pytest.mark.asyncio
async def test_old_buy_small_partial_fill_before_cancel_is_trimmed(config):
    """3 shares of 820 execute, then the cancel lands: 3 + 1 excess shares are trimmed."""
    broker, sheet, engine = friday_state(config)
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 1)

    broker.partial_fill("820", 3)               # position 68
    broker.complete_cancel("820")
    await run_ticks(engine, 8)

    trims = [e for e in broker.events if e[0] == "place" and e[2] == "SELL" and e[3] == 4]
    assert len(trims) == 1
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]
    assert engine._bridge_state != "BRIDGE_HALTED"


@pytest.mark.asyncio
async def test_old_buy_large_partial_fill_before_cancel_is_a_stable_reported_halt(config):
    """
    10 shares of 820 execute, then the cancel lands. 11 excess shares is above
    the trim limit, so nothing is sold automatically: the bridge flow halts,
    says why in Health, notifies once, and stays that way.
    """
    notifier = MagicMock()
    broker, sheet, engine = friday_state(config, notifier)
    engine._startup_ok_notification_sent = True
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 1)

    broker.partial_fill("820", 10)              # position 75
    broker.complete_cancel("820")
    await run_ticks(engine, 10)

    assert engine._bridge_state == "BRIDGE_HALTED"
    assert broker.position == 75, "no automatic sale above the trim limit"
    assert broker.event_index("place") is None
    assert engine._halted_reconciliation is False
    status = (await health_row(engine, sheet))["status"]
    assert status == "BRIDGE_HALTED: broker 75 vs tracker 64, excess 11 is above the trim limit"
    assert any("Broker: 75, Tracker: 64" in e for e in sheet.errors)
    assert len(events(notifier, "BRIDGE_HALTED")) == 1
    assert events(notifier, "BRIDGE_HALTED")[0].kwargs["extra"]["bot_status"] == status
    assert events(notifier, "SHARE_MISMATCH") == []


# --------------------------------------------------------------------------
# 5. Gaps reproduced against 375c33f
# --------------------------------------------------------------------------

async def run_until_old_buy_released_unexplained(config, notifier=None):
    """
    Old BUY 820 leaves the broker with no callback and three shares appear that
    nothing explains. The bot has released 820 and set row 8 to IDLE, and has
    not yet compared shares. Broker 68 = bridge 65 + 3; Tracker row 7 = 64.
    """
    broker, sheet, engine = friday_state(config, notifier)
    engine._startup_ok_notification_sent = True
    await run_ticks(engine, 1)
    broker.orders.pop("820")
    await bridge_fires(broker)
    broker.position += 3
    sheet.recalc_lag_reads = 4                  # the Sheet is still recalculating
    await run_ticks(engine, 2)
    await engine._sync_to_sheet()               # any order callback triggers this write
    assert not engine.order_manager.is_tracked("820")
    assert sheet.statuses[8] == "IDLE"
    assert json.load(open(engine._bridge_state_path))["unresolved_buys"] == ["820"], \
        "the record names 820 by the time its Tracker row is cleared"
    assert engine._bridge_state == "ANCHOR_RECALC_PENDING"
    assert broker.event_index("place") is None
    return broker, sheet, engine


@pytest.mark.asyncio
async def test_unexplained_fill_halts_without_restart(config):
    broker, sheet, engine = await run_until_old_buy_released_unexplained(config)
    await run_ticks(engine, 6)
    assert engine._bridge_state == "BRIDGE_HALTED"
    assert broker.position == 68 and broker.event_index("place") is None


@pytest.mark.asyncio
async def test_unexplained_fill_still_halts_after_restart(config):
    """The uncertainty about order 820 must survive a restart: nothing is sold."""
    broker, sheet, _ = await run_until_old_buy_released_unexplained(config)
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 8)

    assert broker.event_index("place") is None, "four shares within the trim limit must not be sold"
    assert broker.position == 68
    assert engine._bridge_state == "BRIDGE_HALTED"
    status = (await health_row(engine, sheet))["status"]
    assert status == "BRIDGE_HALTED: broker 68 vs tracker 64, old BUY 820 may have filled unreported"
    assert len(events(notifier, "BRIDGE_HALTED")) == 1


@pytest.mark.asyncio
async def test_unresolved_buy_is_saved_before_its_tracker_status_is_cleared(config):
    """If the record cannot be written, the Tracker row keeps the order id as the evidence."""
    broker, sheet, engine = friday_state(config)
    await run_ticks(engine, 1)
    broker.orders.pop("820")
    await bridge_fires(broker)
    engine._bridge_state_path = os.path.join(os.path.dirname(engine._bridge_state_path), "missing", "state.json")
    await run_ticks(engine, 2)
    await engine._sync_to_sheet()

    assert not engine.order_manager.is_tracked("820")
    assert sheet.statuses[8] == "WORKING_BUY:820"


@pytest.mark.asyncio
async def test_bridge_halt_errors_row_carries_code_reason_and_status(config):
    broker, sheet, engine = friday_state(config, MagicMock())
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 1)
    broker.partial_fill("820", 10)
    broker.complete_cancel("820")
    await run_ticks(engine, 6)

    status = (await health_row(engine, sheet))["status"]
    assert status.startswith("BRIDGE_HALTED: ")
    halt_rows = [r for r in sheet.error_rows if "Bridge flow halted" in r["details"]]
    assert len(halt_rows) == 1, "one Errors row for the halt, not a generic one plus a second"
    assert halt_rows[0]["code"] == "BRIDGE_HALTED"
    assert halt_rows[0]["bot_status"] == status
    assert "Broker: 75, Tracker: 64" in halt_rows[0]["details"]
    assert all(r["bot_status"] for r in sheet.error_rows), "every Errors row states the engine status"


async def run_until_trim_working(config):
    broker, sheet, engine = friday_state(config)
    broker.fill_marketable_sells = False
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 3)
    trim = next(o for o in broker.live(action="SELL") if o["qty"] == 1)
    assert (await health_row(engine, sheet))["status"] == "WAITING_TRIM"
    assert sheet.statuses[7] == f"OWNED:818|TRIM_SELL:{trim['order_id']}"
    return broker, sheet, engine, trim["order_id"]


@pytest.mark.asyncio
async def test_restart_while_trim_is_working_restores_waiting_trim(config):
    broker, sheet, _, trim_id = await run_until_trim_working(config)

    engine = restart(broker, sheet, config)
    await run_ticks(engine, 2)

    assert engine._halted_reconciliation is False
    row = await health_row(engine, sheet)
    assert row["status"] == "WAITING_TRIM"
    assert row["order_match_status"] == "MATCH"
    assert [e for e in broker.events if e[0] == "place" and e[2] == "SELL" and e[3] == 1] \
        == [e for e in broker.events if e[0] == "place" and e[1] == trim_id], "no second trim"

    broker.fill(trim_id, price=82.06)
    await run_ticks(engine, 3)
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]
    assert (await health_row(engine, sheet))["status"] == "Running"
    assert not os.path.exists(engine._bridge_state_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("qty", 3), ("limit_price", 70.00), ("action", "BUY"), ("order_type", "MKT"),
])
async def test_restart_does_not_adopt_a_trim_whose_terms_differ(config, field, value):
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.orders[trim_id][field] = value
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 3)

    assert not engine.order_manager.is_tracked(trim_id)
    assert engine._bridge_state != "TRIM_PENDING"
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"
    assert len(events(notifier, "HALT_RECONCILIATION")) == 1
    assert [e for e in broker.events if e[0] == "place"] == [e for e in broker.events if e[0] == "place" and e[1] == trim_id]


@pytest.mark.asyncio
async def test_restart_after_trim_filled_while_down_does_not_trim_again(config):
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.orders.pop(trim_id)
    broker.position = 64                        # the trim filled while the bot was down

    engine = restart(broker, sheet, config)
    await run_ticks(engine, 6)

    assert [e for e in broker.events if e[0] == "place" and e[2] == "SELL" and e[3] == 1] \
        == [e for e in broker.events if e[0] == "place" and e[1] == trim_id]
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]
    assert (await health_row(engine, sheet))["status"] == "Running"


@pytest.mark.asyncio
async def test_health_plain_stop_order_is_not_a_valid_bridge(config):
    """A plain stop with the bridge's price fields is still not a stop-limit."""
    broker, sheet, engine = friday_state(config)
    await engine._tick()
    broker.orders["818"]["order_type"] = "STP"
    row = await health_row(engine, sheet)
    assert row["order_match_status"] == "MISMATCH"
    assert row["unmatched_broker_orders"] == "818"


@pytest.mark.asyncio
async def test_unexplained_fill_still_halts_after_repeated_restarts(config):
    broker, sheet, _ = await run_until_old_buy_released_unexplained(config)
    for _ in range(3):
        engine = restart(broker, sheet, config)
        await run_ticks(engine, 1)
    await run_ticks(engine, 8)
    assert engine._bridge_state == "BRIDGE_HALTED"
    assert broker.event_index("place") is None and broker.position == 68


@pytest.mark.asyncio
async def test_restart_cancels_saved_trim_when_the_excess_is_gone(config):
    """
    The saved trim is still working, but the position already equals the
    Tracker. Refusing to adopt it is not enough: left at the broker it would
    fill and take the position below the Tracker. It is cancelled, then halted.
    """
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 64
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 4)

    assert trim_id not in broker.orders, "the trim must not stay live at the broker"
    assert broker.event_index("cancel", lambda e: e[1] == trim_id) is not None
    assert broker.position == 64
    assert [e for e in broker.events if e[0] == "place"] == [e for e in broker.events if e[0] == "place" and e[1] == trim_id]
    status = (await health_row(engine, sheet))["status"]
    assert status == f"BRIDGE_HALTED: saved trim SELL {trim_id} for 1 shares does not match the broker's excess of 0; trim not resumed"
    assert engine._halted_reconciliation is False
    assert len(events(notifier, "BRIDGE_HALTED")) == 1
    assert "TRIM_SELL" not in sheet.statuses[7]
    assert not os.path.exists(engine._bridge_state_path)


@pytest.mark.asyncio
async def test_restart_trim_that_fills_during_its_cancel_is_accounted_and_halts(config):
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 64
    broker.lose_next_cancel = {trim_id}
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 1)
    assert broker.event_index("cancel_lost", lambda e: e[1] == trim_id) is not None
    assert engine.order_manager.is_tracked(trim_id), "the fill must reach the engine as a known order"

    broker.fill(trim_id, price=82.06)           # fills before the cancel lands: 63 shares
    await run_ticks(engine, 4)

    assert broker.position == 63
    assert "TRIM_SELL" not in sheet.statuses[7], "the fill was handled as the bot's own trim"
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"
    assert len(events(notifier, "HALT_RECONCILIATION")) == 1
    assert [e for e in broker.events if e[0] == "place"] == [e for e in broker.events if e[0] == "place" and e[1] == trim_id]


@pytest.mark.asyncio
async def test_restart_resends_trim_cancel_that_was_not_confirmed(config):
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 64
    broker.lose_next_cancel = {trim_id}

    engine = restart(broker, sheet, config)
    engine._cancel_resend_seconds = 0
    await run_ticks(engine, 5)

    assert trim_id not in broker.orders
    assert broker.position == 64
    assert (await health_row(engine, sheet))["status"].startswith("BRIDGE_HALTED: ")


@pytest.mark.asyncio
async def test_refused_trim_cancel_does_not_stop_reconciliation_from_halting(config):
    """If the broker will not take the cancel, the tick must still reach reconciliation."""
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 64
    broker.refuse_cancel = {trim_id}
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 3)
    assert (await health_row(engine, sheet))["status"].startswith("BRIDGE_HALTED: ")
    assert len([e for e in broker.events if e[0] == "cancel_refused"]) >= 2, "the cancel keeps being retried"

    broker.position = 60                        # broker falls below the Tracker
    await run_ticks(engine, 2)
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"
    assert len(events(notifier, "HALT_RECONCILIATION")) == 1


@pytest.mark.asyncio
async def test_restart_cancels_saved_trim_when_the_excess_is_larger_than_the_trim(config):
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 70                        # 6 above the Tracker; the saved trim sells 1

    engine = restart(broker, sheet, config)
    await run_ticks(engine, 4)

    assert trim_id not in broker.orders and broker.position == 70
    assert (await health_row(engine, sheet))["status"] == \
        f"BRIDGE_HALTED: saved trim SELL {trim_id} for 1 shares does not match the broker's excess of 6; trim not resumed"


@pytest.mark.asyncio
async def test_second_restart_while_trim_cancel_is_pending_still_cancels_it(config):
    """The record must outlive the first cancel attempt, or a second restart loses the trim."""
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 64
    broker.lose_next_cancel = {trim_id}

    first = restart(broker, sheet, config)
    await run_ticks(first, 1)
    assert trim_id in broker.orders and os.path.exists(first._bridge_state_path)

    second = restart(broker, sheet, config)
    await run_ticks(second, 4)
    assert trim_id not in broker.orders
    assert second._halted_reconciliation is False
    assert (await health_row(second, sheet))["status"].startswith("BRIDGE_HALTED: ")


@pytest.mark.asyncio
async def test_bridge_halt_errors_row_is_retried_until_written_without_repeat_notifications(config):
    notifier = MagicMock()
    broker, sheet, engine = friday_state(config, notifier)
    engine._startup_ok_notification_sent = True
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 1)
    broker.partial_fill("820", 10)
    broker.complete_cancel("820")
    sheet.fail_error_writes = 2                 # the halt row fails twice, then the Sheet recovers
    await run_ticks(engine, 8)

    halt_rows = [r for r in sheet.error_rows if "Bridge flow halted" in r["details"]]
    assert len(halt_rows) == 1, "written once it succeeds, and only once"
    assert halt_rows[0]["code"] == "BRIDGE_HALTED"
    assert "Broker: 75, Tracker: 64" in halt_rows[0]["details"]
    assert halt_rows[0]["bot_status"] == (await health_row(engine, sheet))["status"]
    assert len(events(notifier, "BRIDGE_HALTED")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("order_type,halts", [("STP LMT", False), ("STP", True)])
async def test_startup_reconciliation_uses_the_strict_bridge_check(config, order_type, halts):
    """Reconciliation and Health must agree on what a valid bridge order is."""
    broker, sheet, _ = friday_state(config)
    broker.orders["818"]["order_type"] = order_type
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 1)

    assert engine._halted_reconciliation is halts
    if halts:
        assert events(notifier, "HALT_RECONCILIATION")[0].kwargs["extra"]["code"] == "EXTERNAL_OPEN_ORDER_RECONCILE_REQUIRED"
        assert "818" in broker.orders, "an order that is not verifiably the bot's is left alone"
        assert (await health_row(engine, sheet))["order_match_status"] == "MISMATCH"


@pytest.mark.asyncio
async def test_restart_after_trim_cancelled_while_down_halts_and_places_no_new_trim(config):
    """A running bot halts when its trim is cancelled; a restarted one must not replace it."""
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.orders.pop(trim_id)                  # cancelled while the bot was down; position still 65
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 6)

    assert [e for e in broker.events if e[0] == "place" and e[2] == "SELL"] \
        == [e for e in broker.events if e[0] == "place" and e[1] == trim_id], "no replacement trim, no SELL"
    assert broker.position == 65
    status = (await health_row(engine, sheet))["status"]
    assert status == f"BRIDGE_HALTED: trim SELL {trim_id} is no longer at the broker and the broker holds 1 shares above the tracker"
    assert len(events(notifier, "BRIDGE_HALTED")) == 1
    assert not os.path.exists(engine._bridge_state_path)


@pytest.mark.asyncio
async def test_trim_placement_that_raises_after_reaching_the_broker_is_not_repeated(config):
    """The order went out but the call failed: the next tick must wait for it, not send a second trim."""
    broker, sheet, engine = friday_state(config)
    broker.fill_marketable_sells = False
    broker.raise_after_next_sell_placement = True
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 1)
    with pytest.raises(TimeoutError):
        await engine._tick()                    # trim reaches the broker, then the call raises

    await run_ticks(engine, 4)
    trims = [o for o in broker.live(action="SELL") if o["qty"] == 1]
    assert len(trims) == 1, "exactly one trim for one excess share"
    assert (await health_row(engine, sheet))["status"] == "WAITING_TRIM"

    broker.fill(trims[0]["order_id"], price=82.06)
    await run_ticks(engine, 3)
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]


# --------------------------------------------------------------------------
# 6. Gaps reproduced against 86e2fb4
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trim_cancel_and_halt_row_keep_retrying_during_a_reconciliation_halt(config):
    """
    A reconciliation halt blocks trading. It must not block the cancel of a
    trim that has to go, or the Errors row that still has to be written.
    """
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 64
    broker.refuse_cancel = {trim_id}
    sheet.fail_error_writes = 10 ** 6           # the Sheet rejects Errors rows for now
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 3)
    broker.position = 60                        # broker falls below the Tracker
    await run_ticks(engine, 2)
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"
    assert trim_id in broker.orders
    assert not [r for r in sheet.error_rows if r["code"] == "BRIDGE_HALTED"]

    # Broker and Sheet recover while the engine stays halted.
    broker.refuse_cancel = set()
    sheet.fail_error_writes = 0
    placed_before = len([e for e in broker.events if e[0] in ("place", "place_stop")])
    await run_ticks(engine, 4)

    assert trim_id not in broker.orders, "the trim must be cancelled even though trading is halted"
    assert broker.position == 60, "the trim did not sell another share"
    halt_rows = [r for r in sheet.error_rows if r["code"] == "BRIDGE_HALTED"]
    assert len(halt_rows) == 1 and trim_id in halt_rows[0]["details"]
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION", "the halt itself stays latched"
    assert len([e for e in broker.events if e[0] in ("place", "place_stop")]) == placed_before, "no new orders while halted"
    assert len(events(notifier, "HALT_RECONCILIATION")) == 1
    assert len(events(notifier, "BRIDGE_HALTED")) == 1


@pytest.mark.asyncio
async def test_cancel_requirement_survives_a_second_restart_even_if_the_position_matches_again(config):
    """
    First restart: broker and Tracker both 64, so the saved 1-share trim must be
    cancelled; the cancel is not confirmed. The position then becomes 65, which
    happens to equal what the trim would sell. A second restart must still
    cancel it and stay halted, not resume it as a normal working trim.
    """
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 64
    broker.lose_next_cancel = {trim_id}

    first = restart(broker, sheet, config)
    await run_ticks(first, 1)
    record = json.load(open(first._bridge_state_path))
    assert record["trim_cancel_required"] is True
    assert "does not match the broker's excess of 0" in record["halt_reason"]
    assert trim_id in broker.orders

    broker.position = 65
    notifier = MagicMock()
    second = restart(broker, sheet, config, notifier)
    await run_ticks(second, 1)
    assert (await health_row(second, sheet))["status"] != "WAITING_TRIM"

    await run_ticks(second, 4)
    assert trim_id not in broker.orders
    assert broker.event_index("fill", lambda e: e[1] == trim_id) is None, "the trim was cancelled, not filled"
    assert broker.position == 65
    status = (await health_row(second, sheet))["status"]
    assert status == f"BRIDGE_HALTED: saved trim SELL {trim_id} for 1 shares does not match the broker's excess of 0; trim not resumed"
    assert [e for e in broker.events if e[0] == "place"] == [e for e in broker.events if e[0] == "place" and e[1] == trim_id]
    assert len(events(notifier, "BRIDGE_HALTED")) == 1


@pytest.mark.asyncio
async def test_reanchor_flush_keeps_retrying_during_a_reconciliation_halt(config):
    """An old-grid BUY whose cancel was lost must still be cancelled if the engine then halts."""
    broker, sheet, engine = friday_state(config, MagicMock())
    engine._cancel_resend_seconds = 0
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    assert "820" in broker.orders

    await engine._halt_for_reconciliation_error(
        code="SELL_POSITION_MISMATCH_HALT", symbol="TQQQ", row=7, action="SELL", details="test halt")
    placed_before = len([e for e in broker.events if e[0] in ("place", "place_stop")])
    await run_ticks(engine, 3)

    assert "820" not in broker.orders
    assert len([e for e in broker.events if e[0] in ("place", "place_stop")]) == placed_before
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"


@pytest.mark.asyncio
async def test_restart_trim_cancel_inside_the_session_boundary_window_is_not_a_boundary_event(config):
    """03:45-04:05 ET: the bot's own cancel of the saved trim must not be read as an IBKR session cancel."""
    from unittest.mock import patch
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 64
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    with patch.object(GridEngine, "_is_session_boundary", return_value=True):
        await run_ticks(engine, 4)

    assert trim_id not in broker.orders
    assert engine._halted_reconciliation is False
    assert not sheet.statuses[7].startswith("ERROR_RECONCILE_REQUIRED")
    assert (await health_row(engine, sheet))["status"].startswith("BRIDGE_HALTED: saved trim SELL")
    assert events(notifier, "HALT_RECONCILIATION") == []


# --------------------------------------------------------------------------
# 7. Reconnect while halted: an empty order list is not proof an order is gone
# --------------------------------------------------------------------------

def placements(broker):
    return [e for e in broker.events if e[0] in ("place", "place_stop")]


@pytest.mark.asyncio
async def test_halted_trim_cancel_survives_unsynchronized_broker_reads(config):
    broker, sheet, _, trim_id = await run_until_trim_working(config)
    broker.position = 64
    broker.refuse_cancel = {trim_id}
    sheet.fail_error_writes = 10 ** 6
    notifier = MagicMock()

    engine = restart(broker, sheet, config, notifier)
    await run_ticks(engine, 3)
    broker.position = 60
    await run_ticks(engine, 2)
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"
    placed_before = len(placements(broker))

    # Reconnect: snapshot not ready, order cache empty, the trim still live at IBKR.
    broker.synchronized = False
    broker.refuse_cancel = set()
    sheet.fail_error_writes = 0                 # the Sheet is back; the owed Errors row must still go out
    await run_ticks(engine, 3)

    assert engine.order_manager.is_tracked(trim_id), "an empty list from an unready broker is not confirmation"
    assert engine._restart_trim_cancel_id == trim_id
    assert json.load(open(engine._bridge_state_path))["trim_cancel_required"] is True
    assert trim_id in broker.orders
    assert len([r for r in sheet.error_rows if r["code"] == "BRIDGE_HALTED"]) == 1, "Errors retry does not need the broker"

    broker.synchronized = True                  # broker data recovers
    await run_ticks(engine, 3)

    assert trim_id not in broker.orders, "cancellation resumes after recovery"
    assert broker.event_index("fill", lambda e: e[1] == trim_id) is None
    assert broker.position == 60
    assert len(placements(broker)) == placed_before, "no new orders"
    assert engine._halted_reconciliation is True
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"


@pytest.mark.asyncio
async def test_halted_reanchor_buy_cancel_survives_unsynchronized_broker_reads(config):
    broker, sheet, engine = friday_state(config, MagicMock())
    engine._cancel_resend_seconds = 0
    await run_ticks(engine, 1)
    broker.refuse_cancel = {"820"}
    await bridge_fires(broker)
    assert "820" in broker.orders
    await engine._halt_for_reconciliation_error(
        code="SELL_POSITION_MISMATCH_HALT", symbol="TQQQ", row=7, action="SELL", details="test halt")
    placed_before = len(placements(broker))

    broker.synchronized = False
    await run_ticks(engine, 3)

    assert engine.order_manager.is_tracked("820")
    assert sheet.statuses[8] == "WORKING_BUY:820", "the Tracker row is not cleared on an unready read"
    assert engine._reanchor_unresolved_buys == []
    assert json.load(open(engine._bridge_state_path))["unresolved_buys"] == []

    broker.synchronized = True
    broker.refuse_cancel = set()
    await run_ticks(engine, 3)

    assert "820" not in broker.orders
    assert broker.event_index("cancel", lambda e: e[1] == "820") is not None
    assert len(placements(broker)) == placed_before
    assert engine._halted_reconciliation is True
    assert (await health_row(engine, sheet))["status"] == "HALTED_RECONCILIATION"


# --------------------------------------------------------------------------
# Other-errors alerts: each completed share repair is a new event
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_each_automatic_share_repair_alerts_even_with_identical_text(config):
    config.notifications.notify_on_errors = True
    notifier = MagicMock()
    # Rows 7 and 8 hold 125 shares; row 9's BUY filled while its fill report was lost.
    broker = FakeBroker(position=125 + 59)
    broker.seed_order("986", "SELL", 64, 83.87)
    sheet = FakeSheet({7: "WORKING_SELL:986", 8: "OWNED:820", 9: "WORKING_BUY:777"})
    sheet.grid = NEW_GRID
    engine = GridEngine(broker, sheet, config, notifier=notifier)
    engine._startup_ok_notification_sent = True
    engine.last_broker_shares = broker.position
    track_all(engine, broker, [(7, "986", "SELL")])

    await run_ticks(engine, 1)
    assert sheet.statuses[9].startswith("OWNED:")
    await run_ticks(engine, 2)  # normal ticks in between

    # Row 10's new BUY also fills with its fill report lost: a second, separate
    # repair of the same share count, so its Errors row has the same text.
    row10_id = sheet.statuses[10].split(":")[1]
    broker.orders.pop(row10_id)
    broker.position += 59
    await run_ticks(engine, 1)
    assert sheet.statuses[10].startswith("OWNED:")

    repairs = [r for r in sheet.error_rows if r["code"] == "SHARE_RECONCILED"]
    alerts = [c for c in events(notifier, "BOT_ERROR") if c.kwargs["extra"]["code"] == "SHARE_RECONCILED"]
    assert len(repairs) == 2
    assert len(alerts) == 2, "each repair is its own event"
