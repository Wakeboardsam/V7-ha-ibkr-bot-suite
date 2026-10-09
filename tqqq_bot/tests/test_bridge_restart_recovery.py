"""
Bridge Anchor recovery after a restart.

A restarted engine tracks nothing. The Bridge Anchor that row 7 of the Tracker
names, still live at the broker with row 7's terms, is the bot's own order and
is kept: it is not cancelled and placed again. A bridge-like order the Tracker
does not name, or a named one with other terms, still halts reconciliation as
before. A new Bridge Anchor replaces an old ID on row 7 instead of standing
beside it.
"""
from unittest.mock import patch

import pytest

from engine.engine import GridEngine
from engine.order_manager import OrderManager
from tests.bridge_fakes import bridge_fires, friday_state, run_ticks

pytestmark = pytest.mark.usefixtures("regular_session")

LIVE_ORDERS = {"223", "818", "820", "762", "253"}


def restart(broker, sheet, config):
    """A fresh engine on the same broker and Tracker, as after an add-on restart."""
    broker.callbacks.clear()
    engine = GridEngine(broker, sheet, config)
    engine._startup_ok_notification_sent = True
    engine.last_broker_shares = broker.position
    return engine


def bridge_events(broker):
    return [e for e in broker.events if e[0] in ("place_stop", "cancel", "cancel_lost")]


def bridge_parts(sheet):
    return [p for p in sheet.statuses[7].split("|") if p.startswith("BRIDGE_BUY:")]


@pytest.mark.asyncio
async def test_restart_keeps_the_live_bridge_named_in_the_tracker(bridge_config):
    broker, sheet, _ = friday_state(bridge_config)
    engine = restart(broker, sheet, bridge_config)

    await run_ticks(engine, 5)

    assert bridge_events(broker) == [], "the live Bridge is neither cancelled nor placed again"
    assert set(broker.orders) == LIVE_ORDERS
    assert engine.order_manager.get_order_ids_for_action(7, "BRIDGE_BUY") == ["818"]
    assert sheet.statuses[7] == "WORKING_SELL:223|BRIDGE_BUY:818"


@pytest.mark.asyncio
async def test_restart_halts_on_a_bridge_like_order_the_tracker_does_not_name(bridge_config):
    """Unchanged: an order the Tracker does not name is external, so reconciliation halts."""
    broker, sheet, _ = friday_state(bridge_config)
    broker.seed_order("950", "BUY", 65, 84.02, order_type="STP LMT", aux_price=82.52)
    engine = restart(broker, sheet, bridge_config)

    await run_ticks(engine, 3)

    assert engine._halted_reconciliation
    assert any("950" in e for e in sheet.errors)
    assert bridge_events(broker) == []
    assert not engine.order_manager.is_tracked("950")


@pytest.mark.asyncio
async def test_restart_halts_on_a_named_bridge_whose_terms_no_longer_match_row_7(bridge_config):
    """Unchanged: a named Bridge with other terms is not the bot's intent, so it is not kept."""
    broker, sheet, _ = friday_state(bridge_config)
    broker.orders["818"].update(aux_price=81.20, limit_price=82.70)  # an older row 7 sell target
    engine = restart(broker, sheet, bridge_config)

    await run_ticks(engine, 3)

    assert engine._halted_reconciliation
    assert not engine.order_manager.is_tracked("818")
    assert bridge_events(broker) == []


@pytest.mark.asyncio
async def test_restart_after_the_bridge_vanished_places_exactly_one_bridge(bridge_config):
    broker, sheet, _ = friday_state(bridge_config)
    broker.orders.pop("818")  # gone at IBKR while the add-on was down
    engine = restart(broker, sheet, bridge_config)

    await run_ticks(engine, 6)

    events = bridge_events(broker)
    assert [e[0] for e in events] == ["place_stop"], events
    new_id = events[0][1]
    assert sheet.statuses[7] == f"WORKING_SELL:223|BRIDGE_BUY:{new_id}"


@pytest.mark.asyncio
async def test_bridge_fill_right_after_a_restart_starts_the_reanchor(bridge_config):
    broker, sheet, _ = friday_state(bridge_config)
    engine = restart(broker, sheet, bridge_config)
    await run_ticks(engine, 1)
    assert engine.order_manager.is_tracked("818") and engine.order_manager.is_tracked("223")

    await bridge_fires(broker)
    await run_ticks(engine, 1)

    assert engine._bridge_state == "ANCHOR_RECALC_PENDING"
    assert not engine._halted_reconciliation
    assert not {"820", "762", "253"} & set(broker.orders), "the old grid BUYs are flushed"


@pytest.mark.asyncio
async def test_a_bridge_the_bot_is_cancelling_is_not_kept_while_the_confirmation_is_late(bridge_config):
    """
    A cancel the bot sent whose confirmation is late (as at a session boundary)
    is not undone by keeping the order, and no second Bridge is placed while the
    old one may still be live. Once it is gone, one Bridge replaces it on row 7.
    """
    broker, sheet, engine = friday_state(bridge_config)
    broker.lose_next_cancel.add("818")
    await engine._cancel_order_with_intent("818", reason="session_boundary_regeneration")
    engine.order_manager = OrderManager()

    for _ in range(3):
        broker.lose_next_cancel.add("818")
        await run_ticks(engine, 1)
        assert "818" in broker.orders
        assert not engine.order_manager.is_tracked("818")
    assert not [e for e in broker.events if e[0] == "place_stop"]

    broker.complete_cancel("818")
    broker.events.clear()
    await run_ticks(engine, 4)

    placed = [e for e in broker.events if e[0] == "place_stop"]
    assert len(placed) == 1, broker.events
    assert bridge_parts(sheet) == [f"BRIDGE_BUY:{placed[0][1]}"]
    assert engine.order_manager.get_order_ids_for_action(7, "BRIDGE_BUY") == [placed[0][1]]


@pytest.mark.asyncio
async def test_no_bridge_is_kept_during_the_overnight_session(bridge_config):
    broker, sheet, _ = friday_state(bridge_config)
    engine = restart(broker, sheet, bridge_config)

    with patch("brokers.ibkr.order_builder.get_dynamic_exchange", return_value="OVERNIGHT"):
        await run_ticks(engine, 3)

    assert ("cancel", "818") in broker.events
    assert not [e for e in broker.events if e[0] == "place_stop"]
