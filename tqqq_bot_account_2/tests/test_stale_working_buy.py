"""
Outside-window WORKING_BUY rows whose order is gone.

Leaving the active window cancels a row's BUY, and the row keeps WORKING_BUY
until IBKR confirms the cancel. When that confirmation is lost, or the row was
already stale before a restart, the row is set to IDLE once two consecutive
ticks see the order gone while broker shares match the Tracker. A BUY that
filled shows as a share mismatch instead and is never cleared this way.
"""
from unittest.mock import patch

import pytest

from engine.engine import GridEngine
from engine.order_manager import OrderManager
from tests.bridge_fakes import friday_state, run_ticks, track_all

pytestmark = pytest.mark.usefixtures("regular_session")

CODE = "STALE_WORKING_BUY_CLEARED"


def cleared(sheet):
    return [e for e in sheet.error_rows if e["code"] == CODE]


def with_row_11_buy(config, oid="999", live=True, tracked=True):
    """friday_state plus a row 11 BUY, outside the 7..10 window."""
    broker, sheet, engine = friday_state(config)
    sheet.statuses[11] = f"WORKING_BUY:{oid}"
    if live:
        broker.seed_order(oid, "BUY", 58, 77.95)
    if tracked:
        track_all(engine, broker, [(11, oid, "BUY")])
    return broker, sheet, engine


async def lose_the_cancel_confirmation(broker, engine, oid="999"):
    """The bot cancels the row 11 BUY; IBKR removes it but no callback arrives."""
    broker.lose_next_cancel.add(oid)
    await run_ticks(engine, 1)
    assert ("cancel_lost", oid) in broker.events
    assert not engine.order_manager.is_tracked(oid)
    broker.orders.pop(oid)


@pytest.mark.asyncio
async def test_lost_cancel_confirmation_clears_the_row_after_two_ticks(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    await lose_the_cancel_confirmation(broker, engine)
    assert sheet.statuses[11] == "WORKING_BUY:999"

    await run_ticks(engine, 1)
    assert sheet.statuses[11] == "WORKING_BUY:999", "one sighting is not enough"
    assert cleared(sheet) == []

    await run_ticks(engine, 1)
    assert sheet.statuses[11] == "IDLE"
    rows = cleared(sheet)
    assert len(rows) == 1 and rows[0]["severity"] == "INFO"
    assert "WORKING_BUY:999" in rows[0]["details"]

    await run_ticks(engine, 3)
    assert sheet.statuses[11] == "IDLE"
    assert len(cleared(sheet)) == 1
    assert not engine._halted_reconciliation
    assert broker.position == 65
    assert sheet.statuses[7] == "WORKING_SELL:223|BRIDGE_BUY:818"
    assert {sheet.statuses[r] for r in (8, 9, 10)} == {"WORKING_BUY:820", "WORKING_BUY:762", "WORKING_BUY:253"}


@pytest.mark.asyncio
async def test_a_buy_still_live_at_the_broker_is_left_alone(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    for _ in range(5):
        broker.lose_next_cancel.add("999")
        await run_ticks(engine, 1)

    assert "999" in broker.orders
    assert sheet.statuses[11] == "WORKING_BUY:999"
    assert cleared(sheet) == []


@pytest.mark.asyncio
async def test_a_stale_row_from_before_a_restart_is_cleared(bridge_config):
    broker, sheet, _ = with_row_11_buy(bridge_config, live=False, tracked=False)
    broker.callbacks.clear()
    engine = GridEngine(broker, sheet, bridge_config)
    engine._startup_ok_notification_sent = True
    engine.last_broker_shares = broker.position

    await run_ticks(engine, 4)

    assert sheet.statuses[11] == "IDLE"
    assert len(cleared(sheet)) == 1
    assert not engine._halted_reconciliation


@pytest.mark.asyncio
async def test_a_silent_full_fill_is_never_set_to_idle(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    broker.lose_next_cancel.add("999")
    await run_ticks(engine, 1)
    # The BUY filled at IBKR instead of cancelling, and no report arrived.
    broker.callbacks.pop("999", None)
    broker.fill("999")
    assert broker.position == 123

    seen = []
    for _ in range(4):
        await run_ticks(engine, 1)
        seen.append(sheet.statuses[11])

    assert "IDLE" not in seen, seen
    assert cleared(sheet) == []
    assert any(s.startswith("OWNED:") for s in seen), "the existing missed-fill repair owns the row"


@pytest.mark.asyncio
async def test_a_partial_fill_is_never_set_to_idle(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    broker.lose_next_cancel.add("999")
    await run_ticks(engine, 1)
    # 20 shares executed before IBKR cancelled the rest; no report arrived.
    broker.partial_fill("999", 20)
    broker.orders.pop("999")

    await run_ticks(engine, 4)

    assert sheet.statuses[11] == "WORKING_BUY:999"
    assert cleared(sheet) == []


@pytest.mark.asyncio
async def test_an_unavailable_broker_snapshot_starts_the_count_again(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    await lose_the_cancel_confirmation(broker, engine)

    await run_ticks(engine, 1)  # first sighting
    broker.synchronized = False
    await run_ticks(engine, 1)  # broker state unknown: the tick stops early
    broker.synchronized = True
    await run_ticks(engine, 1)  # a first sighting again
    assert sheet.statuses[11] == "WORKING_BUY:999"
    assert cleared(sheet) == []

    await run_ticks(engine, 1)
    assert sheet.statuses[11] == "IDLE"


@pytest.mark.asyncio
async def test_a_share_mismatch_between_sightings_starts_the_count_again(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    await lose_the_cancel_confirmation(broker, engine)

    await run_ticks(engine, 1)  # first sighting
    broker.position += 5
    await run_ticks(engine, 1)  # shares disagree: no sighting
    broker.position -= 5
    await run_ticks(engine, 1)  # a first sighting again
    assert sheet.statuses[11] == "WORKING_BUY:999"
    assert cleared(sheet) == []

    await run_ticks(engine, 1)
    assert sheet.statuses[11] == "IDLE"


@pytest.mark.asyncio
async def test_the_order_reappearing_starts_the_count_again(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    await lose_the_cancel_confirmation(broker, engine)

    await run_ticks(engine, 1)  # first sighting
    broker.seed_order("999", "BUY", 58, 77.95)  # a later snapshot shows it live after all
    broker.lose_next_cancel.add("999")
    await run_ticks(engine, 1)  # live again: no sighting, the bot cancels it again
    assert ("cancel_lost", "999") in broker.events[-2:]
    broker.orders.pop("999")
    await run_ticks(engine, 1)  # a first sighting again
    assert sheet.statuses[11] == "WORKING_BUY:999"
    assert cleared(sheet) == []

    await run_ticks(engine, 1)
    assert sheet.statuses[11] == "IDLE"
    assert len(cleared(sheet)) == 1


@pytest.mark.asyncio
async def test_a_late_cancel_confirmation_clears_the_row_as_before(bridge_config):
    """The ordinary path is unchanged: a confirmation that does arrive sets IDLE with no stale-row log."""
    broker, sheet, engine = with_row_11_buy(bridge_config)
    broker.lose_next_cancel.add("999")
    await run_ticks(engine, 1)
    broker.complete_cancel("999")
    await run_ticks(engine, 1)

    assert sheet.statuses[11] == "IDLE"
    assert cleared(sheet) == []


@pytest.mark.asyncio
async def test_a_changed_order_id_starts_the_count_again(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    await lose_the_cancel_confirmation(broker, engine)

    await run_ticks(engine, 1)  # first sighting of 999
    sheet.statuses[11] = "WORKING_BUY:1001"  # edited on the Tracker
    await run_ticks(engine, 1)  # first sighting of 1001
    assert sheet.statuses[11] == "WORKING_BUY:1001"
    assert cleared(sheet) == []

    await run_ticks(engine, 1)
    assert sheet.statuses[11] == "IDLE"
    assert "WORKING_BUY:1001" in cleared(sheet)[0]["details"]


@pytest.mark.asyncio
async def test_a_queued_status_write_for_the_row_prevents_the_clear(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    await lose_the_cancel_confirmation(broker, engine)

    real_write = sheet.update_row_status

    async def row_11_write_fails(row_index, status):
        if row_index == 11:
            raise RuntimeError("Sheets API unavailable")
        await real_write(row_index, status)

    sheet.update_row_status = row_11_write_fails
    engine._update_row_status_in_memory(11, "WORKING_BUY:999")
    await run_ticks(engine, 4)

    assert 11 in engine.pending_status_updates
    assert cleared(sheet) == []
    assert engine.pending_status_updates[11] == "WORKING_BUY:999"


@pytest.mark.asyncio
async def test_a_pending_ownership_update_prevents_the_clear(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    await lose_the_cancel_confirmation(broker, engine)

    async def writes_fail(row_index, status):
        raise RuntimeError("Sheets API unavailable")

    sheet.update_row_status = writes_fail
    engine._update_row_status_in_memory(11, "OWNED:999")
    await run_ticks(engine, 4)

    assert cleared(sheet) == []
    assert engine.pending_status_updates.get(11) == "OWNED:999"


@pytest.mark.asyncio
async def test_rows_inside_the_window_are_not_cleared_this_way(bridge_config):
    """An in-window row with its BUY gone gets a new BUY, as before, not IDLE."""
    broker, sheet, engine = friday_state(bridge_config)
    broker.orders.pop("253")
    engine.order_manager = OrderManager()
    track_all(engine, broker, [(7, "223", "SELL"), (7, "818", "BRIDGE_BUY"), (8, "820", "BUY"), (9, "762", "BUY")])

    await run_ticks(engine, 4)

    assert cleared(sheet) == []
    assert sheet.statuses[10] != "IDLE"


@pytest.mark.asyncio
async def test_nothing_is_cleared_while_reconciliation_is_halted(bridge_config):
    broker, sheet, engine = with_row_11_buy(bridge_config)
    await lose_the_cancel_confirmation(broker, engine)
    engine._halted_reconciliation = True

    with patch.object(engine, "_execution_status", return_value="HALTED"):
        await run_ticks(engine, 4)

    assert sheet.statuses[11] == "WORKING_BUY:999"
    assert cleared(sheet) == []
