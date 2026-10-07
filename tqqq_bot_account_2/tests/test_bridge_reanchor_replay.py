"""
Replay of the 2026-10-02 Bridge Anchor incident, plus the behaviour the
re-anchor sequence must have.

What happened that day (bot log, local time):

  06:59  Row 8 BUY (order 820) placed from the old grid: 62 shares @ 80.39.
         Rows 9 and 10 already had old-grid BUYs (762, 253), 60 shares each.
  08:24  Row 7 SELL filled 65 @ 82.52 and the Bridge Anchor bought 65 @ 82.525.
         G7 was re-anchored, so the Sheet recalculated every level:
         row 7 -> 64 shares, row 8 -> 61 @ 81.70, rows 9/10 -> 59 shares.
  08:25  1 share trimmed, new row 7 SELL placed, bridge re-armed.
         The three old-grid BUYs were left working at the broker.
  09:25  Old order 820 filled for 62 shares; the Sheet said 61.
         Broker 126 vs Sheet 125 -> circuit breaker, every minute.

Required sequence after a Bridge Anchor fill:

  1. cancel every standing order left from the old grid, and wait until the
     broker no longer shows them
  2. the fill price becomes the G7 anchor
  3. wait for the Sheet to recalculate (two identical consecutive reads)
  4. trim excess shares if needed
  5. only then place the new row 7 SELL, the new window BUYs and the bridge

These tests use a small stateful broker and Sheet instead of loose mocks so
that the real state transitions are exercised.
"""
import asyncio
from unittest.mock import MagicMock

import pytest

from brokers.base import OrderResult
from config.schema import NotificationSettings
from engine.engine import GridEngine
from tests.bridge_fakes import (
    NEW_GRID, FakeBroker, FakeSheet, bridge_fires, buys_match_sheet, friday_state, run_ticks,
)

pytestmark = pytest.mark.usefixtures("regular_session")


@pytest.fixture
def config(bridge_config):
    return bridge_config


@pytest.mark.asyncio
async def test_friday_replay_old_grid_buys_are_flushed_after_bridge_fill(config):
    """The incident itself: no old-grid BUY may survive the re-anchor."""
    broker, sheet, engine = friday_state(config)

    await run_ticks(engine, 1)          # steady state before the move
    assert set(broker.orders) == {"223", "818", "820", "762", "253"}

    await bridge_fires(broker)
    await run_ticks(engine, 8)

    # 1. The three old-grid BUYs are gone from the broker.
    assert not {"820", "762", "253"} & set(broker.orders), \
        f"old-grid BUYs still working: {sorted({'820', '762', '253'} & set(broker.orders))}"

    # 2. Whatever BUYs are working now were sized and priced from the new grid.
    assert buys_match_sheet(broker, NEW_GRID) == []

    # 3. The anchor was written with the bridge fill price and position was trimmed to the Sheet.
    assert 82.525 in sheet.anchor_writes
    assert broker.position == NEW_GRID[7][2] == 64

    # 4. Row 7 is protected again: new SELL and a re-armed bridge, both for 64 @ 83.87.
    sells = broker.live(action="SELL")
    assert [(o["qty"], o["limit_price"]) for o in sells] == [(64, 83.87)]
    bridges = broker.live(action="BUY", order_type="STP LMT")
    assert [(o["qty"], o["aux_price"]) for o in bridges] == [(64, 83.87)]

    # 5. Price falls and the row 8 BUY fills: broker and Sheet still agree.
    row8_buy = next(o for o in broker.live(action="BUY", order_type="LMT")
                    if o["limit_price"] == NEW_GRID[8][1])
    broker.fill(row8_buy["order_id"])
    await run_ticks(engine, 3)

    assert broker.position == NEW_GRID[7][2] + NEW_GRID[8][2] == 125
    assert not [e for e in sheet.errors if "CIRCUIT BREAKER" in e]
    assert engine._bridge_state != "BRIDGE_HALTED"
    assert engine._halted_reconciliation is False


@pytest.mark.asyncio
async def test_reanchor_sequence_order_cancel_then_trim_then_new_orders(config):
    """Nothing new is placed until the old orders are gone and the Sheet has settled."""
    broker, sheet, engine = friday_state(config)
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 8)

    last_old_cancel = max(
        broker.event_index("cancel", lambda e, oid=oid: e[1] == oid) for oid in ("820", "762", "253")
    )
    trim_placed = broker.event_index("place", lambda e: e[2] == "SELL" and e[3] == 1)
    new_sell_placed = broker.event_index("place", lambda e: e[2] == "SELL" and e[3] == 64)
    first_new_buy = broker.event_index("place", lambda e: e[2] == "BUY")
    bridge_rearmed = broker.event_index("place_stop", lambda e: e[3] == 64)

    assert None not in (trim_placed, new_sell_placed, first_new_buy, bridge_rearmed)
    assert last_old_cancel < trim_placed < new_sell_placed
    assert new_sell_placed <= first_new_buy
    assert new_sell_placed < bridge_rearmed


@pytest.mark.asyncio
async def test_reanchor_waits_for_sheet_to_settle_before_trimming(config):
    """A Sheet that is slow to recalculate must not produce a trim from stale share counts."""
    broker, sheet, engine = friday_state(config)
    sheet.recalc_lag_reads = 3
    await run_ticks(engine, 1)
    await bridge_fires(broker)

    await run_ticks(engine, 3)
    # Still on the old grid (row 7 = 65 shares, equal to the position): nothing may be placed yet.
    assert broker.event_index("place") is None
    assert broker.event_index("place_stop") is None
    assert engine._bridge_state == "ANCHOR_RECALC_PENDING"

    await run_ticks(engine, 8)
    assert broker.position == 64
    assert buys_match_sheet(broker, NEW_GRID) == []


@pytest.mark.asyncio
async def test_reanchor_waits_for_old_row7_sell_before_reconciling_shares(config):
    """Bridge fills while the old row 7 SELL is still working: wait, do not halt the bridge flow."""
    broker, sheet, engine = friday_state(config)
    await run_ticks(engine, 1)

    broker.fill("818", price=82.525)      # bridge first; SELL 223 still working, position 130
    await asyncio.sleep(0.01)
    await run_ticks(engine, 4)

    assert engine._bridge_state == "ANCHOR_RECALC_PENDING"
    assert broker.event_index("place") is None, "no trim or new order while the old SELL is live"

    broker.fill("223", price=82.52)       # the delayed SELL fill arrives
    await asyncio.sleep(0.01)
    await run_ticks(engine, 8)

    assert engine._bridge_state != "BRIDGE_HALTED"
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]


@pytest.mark.asyncio
async def test_reanchor_resends_a_cancel_whose_confirmation_was_lost(config):
    """A cancel the broker never confirms must be sent again, not waited on forever."""
    broker, sheet, engine = friday_state(config)
    engine._cancel_resend_seconds = 0
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 10)

    assert broker.event_index("cancel_lost", lambda e: e[1] == "820") is not None
    assert "820" not in broker.orders
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]
    assert buys_match_sheet(broker, NEW_GRID) == []


@pytest.mark.asyncio
async def test_reanchor_does_not_resend_a_recent_cancel(config):
    """Within the resend window a pending cancel is left alone."""
    broker, sheet, engine = friday_state(config)
    broker.lose_next_cancel = {"820"}
    await run_ticks(engine, 1)
    await bridge_fires(broker)
    await run_ticks(engine, 5)

    assert "820" in broker.orders
    assert len([e for e in broker.events if e[0] in ("cancel", "cancel_lost") and e[1] == "820"]) == 1
    assert engine._bridge_state == "ANCHOR_RECALC_PENDING"
    assert broker.event_index("place") is None


@pytest.mark.asyncio
async def test_reanchor_releases_old_buy_that_vanished_without_a_callback(config):
    """An old BUY the broker no longer shows, with no callback, must not block the row 7 SELL."""
    broker, sheet, engine = friday_state(config)
    await run_ticks(engine, 1)
    broker.orders.pop("820")              # gone at the broker, no cancel or fill callback
    await bridge_fires(broker)
    await run_ticks(engine, 10)

    assert not engine.order_manager.is_tracked("820")
    assert broker.position == 64
    assert [(o["qty"], o["limit_price"]) for o in broker.live(action="SELL")] == [(64, 83.87)]
    assert buys_match_sheet(broker, NEW_GRID) == []
    assert engine._bridge_state != "BRIDGE_HALTED"


@pytest.mark.asyncio
async def test_stale_grid_buy_needs_two_consecutive_ticks(config):
    """A sighting followed by a tick that does not evaluate the grid does not count."""
    broker = FakeBroker(position=64)
    broker.seed_order("986", "SELL", 64, 83.87)
    broker.seed_order("820", "BUY", 62, 80.39)
    sheet = FakeSheet({7: "WORKING_SELL:986", 8: "WORKING_BUY:820"})
    sheet.grid = NEW_GRID
    engine = GridEngine(broker, sheet, config)
    engine.last_broker_shares = 64
    engine.order_manager.track(7, OrderResult(order_id="986", status="submitted"), "SELL",
                               broker=broker, on_update=engine._handle_order_update)
    engine.order_manager.track(8, OrderResult(order_id="820", status="submitted"), "BUY",
                               broker=broker, on_update=engine._handle_order_update)

    await run_ticks(engine, 1)                         # first sighting
    engine._session_cancel_settlement_required = True  # next tick ends before grid evaluation
    await run_ticks(engine, 1)
    await run_ticks(engine, 1)                         # sighting again: still only the first in a row
    assert "820" in broker.orders

    await run_ticks(engine, 1)
    assert "820" not in broker.orders


@pytest.mark.asyncio
async def test_stale_grid_buy_is_replaced_when_sheet_row_changes(config):
    """Standing check: a working BUY that no longer matches its row is cancelled and re-placed."""
    broker = FakeBroker(position=64)
    broker.seed_order("986", "SELL", 64, 83.87)
    broker.seed_order("820", "BUY", 62, 80.39)          # old-grid order on row 8
    sheet = FakeSheet({7: "WORKING_SELL:986", 8: "WORKING_BUY:820"})
    sheet.grid = NEW_GRID
    engine = GridEngine(broker, sheet, config)
    engine.last_broker_shares = 64
    engine.order_manager.track(7, OrderResult(order_id="986", status="submitted"), "SELL",
                               broker=broker, on_update=engine._handle_order_update)
    engine.order_manager.track(8, OrderResult(order_id="820", status="submitted"), "BUY",
                               broker=broker, on_update=engine._handle_order_update)

    await run_ticks(engine, 1)
    assert "820" in broker.orders, "one mismatching read is not enough to cancel"

    await run_ticks(engine, 3)
    assert "820" not in broker.orders
    row8 = [o for o in broker.live(action="BUY", order_type="LMT") if o["limit_price"] == 81.70]
    assert [(o["qty"]) for o in row8] == [61]


@pytest.mark.asyncio
async def test_stale_grid_buy_check_ignores_unreadable_sheet_row(config):
    """A row that reads as zero shares / zero price must never cause a cancel."""
    broker = FakeBroker(position=64)
    broker.seed_order("986", "SELL", 64, 83.87)
    broker.seed_order("820", "BUY", 61, 81.70)
    sheet = FakeSheet({7: "WORKING_SELL:986", 8: "WORKING_BUY:820"})
    sheet.grid = dict(NEW_GRID)
    sheet.grid[8] = (0.0, 0.0, 0)
    engine = GridEngine(broker, sheet, config)
    engine.last_broker_shares = 64
    engine.order_manager.track(7, OrderResult(order_id="986", status="submitted"), "SELL",
                               broker=broker, on_update=engine._handle_order_update)
    engine.order_manager.track(8, OrderResult(order_id="820", status="submitted"), "BUY",
                               broker=broker, on_update=engine._handle_order_update)

    await run_ticks(engine, 4)
    assert "820" in broker.orders


@pytest.mark.asyncio
async def test_share_mismatch_cancels_live_bridge_and_notifies_once(config):
    """
    The state the account was left in on 2026-10-02: two rows owned, broker one
    share above the Sheet, Bridge Anchor 990 still armed. The mismatch check must
    not leave the bridge live, and must tell the operator once, not every minute.
    """
    config.notifications = NotificationSettings(enabled=True, webhook_url="http://example.invalid/hook",
                                                notify_on_share_mismatch=True)
    notifier = MagicMock()

    broker = FakeBroker(position=126)
    broker.seed_order("986", "SELL", 64, 83.87)
    broker.seed_order("990", "BUY", 64, 85.37, order_type="STP LMT", aux_price=83.87)
    sheet = FakeSheet({7: "WORKING_SELL:986|BRIDGE_BUY:990", 8: "OWNED:820"})
    sheet.grid = NEW_GRID
    engine = GridEngine(broker, sheet, config, notifier=notifier)
    engine._startup_ok_notification_sent = True
    engine.last_broker_shares = 126
    engine.order_manager.track(7, OrderResult(order_id="986", status="submitted"), "SELL",
                               broker=broker, on_update=engine._handle_order_update)
    engine.order_manager.track(7, OrderResult(order_id="990", status="submitted"), "BRIDGE_BUY",
                               broker=broker, on_update=engine._handle_order_update)

    await run_ticks(engine, 3)

    assert "990" not in broker.orders, "Bridge Anchor must not stay armed during a share mismatch"
    assert "986" in broker.orders, "the protective row 7 SELL is left alone"
    assert broker.event_index("place") is None, "a mismatch places nothing"
    assert "BRIDGE_BUY" not in sheet.statuses[7]

    mismatch_calls = [c for c in notifier.send.call_args_list
                      if c.kwargs.get("event_type") == "SHARE_MISMATCH"]
    assert len(mismatch_calls) == 1
    assert mismatch_calls[0].kwargs["extra"]["broker_shares"] == 126
    assert mismatch_calls[0].kwargs["extra"]["sheet_shares"] == 125


@pytest.mark.asyncio
async def test_replay_2026_10_06_row7_sells_and_bridge_does_not_fill(config):
    """
    2026-10-06 04:12: the row 7 SELL filled and the Bridge Anchor did not. With
    no shares left this is an ordinary full sell-out: cancel the bridge, cancel
    the old buys, re-anchor, buy the new anchor. Row 7 was instead written as
    'OWNED:0|IDLE', which claimed 63 shares the broker did not hold and halted
    the bot.
    """
    broker, sheet, engine = friday_state(config)
    await run_ticks(engine, 1)

    broker.fill("223", price=82.52)             # row 7 sells; bridge 818 stays untriggered
    await asyncio.sleep(0.01)
    assert sheet.statuses[7] == "IDLE"

    await run_ticks(engine, 6)

    assert engine._halted_reconciliation is False
    assert "OWNED" not in sheet.statuses[7], f"row 7 must not claim shares: {sheet.statuses[7]}"
    assert not [e for e in sheet.errors if "halt" in e.lower()]
    assert "818" not in broker.orders, "the unfilled bridge is cancelled"
    assert not {"820", "762", "253"} & set(broker.orders), "old-grid buys are cancelled"
    assert sheet.anchor_writes, "G7 is re-anchored"
    assert broker.position == 0
    # The only order left is the new anchor BUY for row 7, from the recalculated grid.
    assert [(o["action"], o["qty"], o["limit_price"]) for o in broker.orders.values()] == \
        [("BUY", NEW_GRID[7][2], round(NEW_GRID[7][1] + 1.5, 2))]
    assert sheet.statuses[7].startswith("WORKING_BUY:")


def test_removing_a_part_never_invents_ownership():
    from engine.engine import _remove_status_part
    assert _remove_status_part("IDLE", "BRIDGE_BUY:") == "IDLE"
    assert _remove_status_part("BRIDGE_BUY:217", "BRIDGE_BUY:") == "IDLE"
    assert _remove_status_part("IDLE|BRIDGE_BUY:217", "BRIDGE_BUY:") == "IDLE"
    assert _remove_status_part("WORKING_BUY:209", "WORKING_BUY:") == "IDLE"
    # A row that held shares keeps them.
    assert _remove_status_part("WORKING_SELL:7", "WORKING_SELL:") == "OWNED:0"
    assert _remove_status_part("WORKING_SELL:7|BRIDGE_BUY:221", "BRIDGE_BUY:") == "WORKING_SELL:7"
    assert _remove_status_part("OWNED:5|BRIDGE_BUY:221", "BRIDGE_BUY:") == "OWNED:5"
