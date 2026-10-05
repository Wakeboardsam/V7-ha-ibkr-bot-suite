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
        enabled=True, webhook_url="http://example.invalid/hook", notify_on_halts=True)
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
