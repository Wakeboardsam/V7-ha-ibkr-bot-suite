"""
The session-boundary regeneration through the real engine tick.

At 16:00 and 20:00 ET the bot cancels its orders, clears its order tracking and
ends the tick; once IBKR confirms the cancels, later ticks place the orders
again for the new session (SMART/GTC from 16:00, OVERNIGHT/DAY from 20:00).
From Friday 20:00 to Sunday 20:00 it places nothing. The clock here drives both
the engine's boundary check and the order builder's exchange choice.
"""
import datetime as real_datetime
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from brokers.ibkr import order_builder
from engine.engine import GridEngine
from tests.bridge_fakes import NEW_GRID, FakeBroker, FakeSheet, run_ticks
from tests.conftest import pinned_session_now


class SessionBroker(FakeBroker):
    """Records each order's exchange and time in force as the adapter would choose them."""

    def seed_order(self, order_id, action, qty, limit_price, order_type="LMT", aux_price=None):
        super().seed_order(order_id, action, qty, limit_price, order_type, aux_price)
        exchange = order_builder.get_dynamic_exchange()
        self.orders[str(order_id)].update(exchange=exchange, tif=order_builder.get_dynamic_tif(exchange))


@pytest.fixture
def clock(pinned_session_clock):
    fake_datetime_module = SimpleNamespace(
        datetime=SimpleNamespace(now=lambda tz=None: pinned_session_clock["now"]),
        time=real_datetime.time,
    )
    with patch.object(order_builder, "datetime", fake_datetime_module), \
         patch.object(GridEngine, "_is_session_boundary", return_value=False), \
         patch.object(GridEngine, "_is_in_maintenance_window", return_value=False):
        yield pinned_session_clock


def at(clock, day, hour, minute):
    """Moves the clock to 2026-10-<day> hour:minute ET (5 Mon ... 9 Fri, 11 Sun)."""
    clock["now"] = pinned_session_now().replace(day=day, hour=hour, minute=minute)


def grid_orders(broker):
    """(action, qty, limit price) of each live order, ignoring order IDs."""
    return sorted((o["action"], o["qty"], o["limit_price"], o["order_type"]) for o in broker.orders.values())


def events(broker, kind):
    return [e for e in broker.events if e[0] == kind]


async def running_bot(config, clock):
    """Row 7 owned, the bot's grid orders working for the current session."""
    broker = SessionBroker(position=64)
    sheet = FakeSheet({7: "OWNED:1"})
    sheet.grid = NEW_GRID
    engine = GridEngine(broker, sheet, config)
    engine._startup_ok_notification_sent = True
    engine.last_broker_shares = 64
    await run_ticks(engine, 3)
    assert broker.orders, "the running bot has orders working"
    return broker, sheet, engine


async def cross_boundary(broker, engine):
    """One tick with IBKR holding back its cancel confirmations; returns the orders live before it."""
    old_ids = set(broker.orders)
    broker.events.clear()
    broker.lose_next_cancel.update(old_ids)
    await run_ticks(engine, 1)
    return old_ids


async def confirm_cancels_and_settle(broker, engine, ticks=3):
    for oid in list(broker.orders):
        if oid in broker.callbacks:
            broker.complete_cancel(oid)
    broker.events.clear()
    await run_ticks(engine, ticks)


@pytest.mark.asyncio
async def test_tick_across_16_00_cancels_ends_tick_then_replaces_orders_as_gtc(bridge_config, clock):
    at(clock, 7, 15, 30)
    broker, sheet, engine = await running_bot(bridge_config, clock)
    before = grid_orders(broker)

    at(clock, 7, 16, 1)
    old_ids = await cross_boundary(broker, engine)

    assert {e[1] for e in events(broker, "cancel_lost")} == old_ids, "every bot order is cancelled"
    assert not events(broker, "place") and not events(broker, "place_stop"), "the boundary tick ends early"
    assert not set(engine.order_manager.get_tracked_order_ids()) & old_ids, "order tracking is cleared"

    # While IBKR has not confirmed the cancels, nothing is placed over the old orders.
    broker.events.clear()
    await run_ticks(engine, 1)
    assert not events(broker, "place")

    await confirm_cancels_and_settle(broker, engine)
    assert not set(broker.orders) & old_ids
    assert grid_orders(broker) == before, "the same grid is placed again"
    assert {(o["exchange"], o["tif"]) for o in broker.orders.values()} == {("SMART", "GTC")}


@pytest.mark.asyncio
async def test_tick_across_20_00_replaces_orders_on_the_overnight_session(bridge_config, clock):
    at(clock, 7, 19, 0)
    broker, sheet, engine = await running_bot(bridge_config, clock)

    at(clock, 7, 20, 1)
    old_ids = await cross_boundary(broker, engine)
    assert {e[1] for e in events(broker, "cancel_lost")} == old_ids
    assert not events(broker, "place") and not events(broker, "place_stop")

    await confirm_cancels_and_settle(broker, engine)
    assert broker.orders and not set(broker.orders) & old_ids
    assert {(o["exchange"], o["tif"]) for o in broker.orders.values()} == {("OVERNIGHT", "DAY")}
    assert not broker.live(order_type="STP LMT"), "the Bridge Anchor is not armed overnight"
    # The grid itself is unchanged: a SELL for row 7 and the BUYs below it.
    assert ("SELL", 64, 83.87, "LMT") in grid_orders(broker)


@pytest.mark.asyncio
async def test_later_tick_in_the_same_session_does_not_regenerate_again(bridge_config, clock):
    at(clock, 7, 15, 30)
    broker, sheet, engine = await running_bot(bridge_config, clock)
    at(clock, 7, 16, 1)
    await cross_boundary(broker, engine)
    await confirm_cancels_and_settle(broker, engine)
    working = dict(broker.orders)

    at(clock, 7, 19, 30)
    broker.events.clear()
    await run_ticks(engine, 3)

    assert not events(broker, "cancel") and not events(broker, "cancel_lost")
    assert broker.orders == working


@pytest.mark.asyncio
async def test_friday_20_00_cancels_and_places_nothing_until_sunday_20_00(bridge_config, clock):
    at(clock, 9, 19, 0)
    broker, sheet, engine = await running_bot(bridge_config, clock)

    at(clock, 9, 20, 1)
    old_ids = await cross_boundary(broker, engine)
    assert {e[1] for e in events(broker, "cancel_lost")} == old_ids
    await confirm_cancels_and_settle(broker, engine)
    assert engine._is_weekend_gap is True
    assert broker.orders == {}, "nothing is placed in the weekend gap"

    at(clock, 10, 12, 0)  # Saturday
    await run_ticks(engine, 2)
    assert broker.orders == {}

    at(clock, 11, 20, 1)  # Sunday evening: the overnight session opens
    await run_ticks(engine, 3)
    assert engine._is_weekend_gap is False
    assert broker.orders
    assert {(o["exchange"], o["tif"]) for o in broker.orders.values()} == {("OVERNIGHT", "DAY")}


@pytest.mark.asyncio
async def test_first_tick_after_a_start_sets_up_the_session_and_keeps_working_orders(bridge_config, clock):
    """
    A fresh start has no record of setting up the session, so its first tick
    does it. Nothing is tracked yet at that point, so no order is cancelled; the
    tick ends, and later ticks re-track the working orders from the Tracker.
    """
    at(clock, 7, 11, 0)
    broker, sheet, engine = await running_bot(bridge_config, clock)
    working = dict(broker.orders)

    restarted = GridEngine(broker, sheet, bridge_config)
    restarted._last_grid_regeneration = datetime.min.replace(tzinfo=clock["now"].tzinfo)
    restarted._startup_ok_notification_sent = True
    restarted.last_broker_shares = 64
    broker.events.clear()

    await run_ticks(restarted, 1)
    assert restarted._last_grid_regeneration == clock["now"]
    assert broker.events == [], "the first tick neither cancels nor places"

    await run_ticks(restarted, 3)
    # The grid's limit orders and the Bridge Anchor are kept and re-tracked.
    limit_ids = {oid for oid, o in working.items() if o["order_type"] == "LMT"}
    assert events(broker, "cancel") == []
    assert events(broker, "place_stop") == []
    assert {oid: o for oid, o in broker.orders.items() if o["order_type"] == "LMT"} == \
        {oid: working[oid] for oid in limit_ids}
    assert limit_ids <= set(restarted.order_manager.get_tracked_order_ids())
