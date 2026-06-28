import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta
from typing import List

from engine.engine import GridEngine
from engine.grid_state import GridState, GridRow
from engine.order_manager import OrderManager

@pytest.fixture
def mock_broker():
    broker = AsyncMock()
    broker.get_open_orders = AsyncMock(return_value=[])
    broker.get_position_snapshot = AsyncMock()
    return broker

@pytest.fixture
def engine(mock_broker):
    sheet = AsyncMock()
    config = MagicMock()
    eng = GridEngine(broker=mock_broker, sheet=sheet, config=config)
    eng._halt_for_reconciliation_error = AsyncMock()
    eng._update_row_status_in_memory = MagicMock()
    return eng

@pytest.mark.asyncio
async def test_pre_sell_guard_successful_placement(engine, mock_broker):
    """
    Scenario 1:
    - broker position = 314
    - tracker owned rows total = 314
    - previous sell orders totaling 314 receive Cancelled callbacks
    - fresh broker open orders = []
    - bot attempts to replace a missing sell for 83 shares
    - expected: no SELL_POSITION_MISMATCH_HALT, available_to_sell = 314, order placement allowed
    """
    broker_shares = 314
    requested_qty = 83
    row_index = 7

    # Simulate recent cancellation
    engine._recent_session_cancels["old_order"] = datetime.now()

    open_orders = [] # Fresh fetch returns empty
    mock_broker.get_open_orders.return_value = open_orders

    can_place = await engine._run_pre_sell_guard(requested_qty, row_index, "SELL", open_orders, broker_shares)

    assert can_place is True
    engine._halt_for_reconciliation_error.assert_not_called()

@pytest.mark.asyncio
async def test_pre_sell_guard_partial_active_sells(engine, mock_broker):
    """
    Scenario 2:
    - broker position = 314
    - one active broker SELL remains open for 80 shares
    - bot attempts a new SELL for 83
    - expected available_to_sell = 234, placement allowed
    """
    broker_shares = 314
    requested_qty = 83
    row_index = 6

    open_orders = [
        {'order_id': 'active1', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 80, 'remaining_qty': 80, 'status': 'Submitted'},
        {'order_id': 'cancelled1', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 100, 'remaining_qty': 100, 'status': 'Cancelled'},
    ]

    can_place = await engine._run_pre_sell_guard(requested_qty, row_index, "SELL", open_orders, broker_shares)

    assert can_place is True
    engine._halt_for_reconciliation_error.assert_not_called()

@pytest.mark.asyncio
async def test_pre_sell_guard_halt_on_oversell(engine, mock_broker):
    """
    Scenario 3:
    - broker position = 314
    - active broker SELL orders remaining total = 314
    - bot attempts another SELL for 83
    - expected: hard guard halts/blocks because available_to_sell = 0
    """
    broker_shares = 314
    requested_qty = 83
    row_index = 5

    open_orders = [
        {'order_id': 'active1', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 314, 'remaining_qty': 314, 'status': 'Submitted'},
    ]

    can_place = await engine._run_pre_sell_guard(requested_qty, row_index, "SELL", open_orders, broker_shares)

    assert can_place is False
    engine._halt_for_reconciliation_error.assert_called_once()
    assert engine._halt_for_reconciliation_error.call_args[1]['code'] == 'SELL_POSITION_MISMATCH_HALT'

@pytest.mark.asyncio
async def test_pre_sell_guard_debounce_stale_data(engine, mock_broker):
    """
    Scenario:
    - Recent cancellation was recorded.
    - Fresh fetch still shows the order as 'Submitted' (stale).
    - Expected: skip cycle (return False) but do not halt.
    """
    broker_shares = 314
    requested_qty = 83
    row_index = 7

    engine._recent_session_cancels["stale_order"] = datetime.now()

    open_orders = [
        {'order_id': 'stale_order', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 83, 'status': 'Submitted'},
    ]
    mock_broker.get_open_orders.return_value = open_orders

    can_place = await engine._run_pre_sell_guard(requested_qty, row_index, "SELL", open_orders, broker_shares)

    assert can_place is False
    engine._halt_for_reconciliation_error.assert_not_called()

@pytest.mark.asyncio
async def test_pre_sell_guard_tick_integration(engine, mock_broker):
    """
    Integration test proving the live scenario via `_tick`:
    - Tracker row is OWNED:0 / live Y
    - Broker position is sufficient
    - Recent session cancellation exists in engine._recent_session_cancels
    - Fresh broker get_open_orders returns []
    - Expected: _tick successfully places the replacement SELL without halting.
    """
    # 1. Configuration
    engine.config.dry_run = False
    engine.config.maintenance_enabled = False
    engine.config.share_mismatch_mode = "halt"
    engine.config.ibkr_account_id = None
    engine.config.enable_bridge_anchor = False
    engine.config.max_spread_pct = 1.0
    engine.config.anchor_buy_offset = 0.05
    engine.config.bridge_max_auto_trim_shares = 999

    # 2. Broker Mocking
    from brokers.base import PositionSnapshot, OrderResult
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 314})
    mock_broker.get_open_orders.return_value = []
    mock_broker.ensure_connected = AsyncMock()
    mock_broker.get_wallet_balance = AsyncMock(return_value=1000.0)
    mock_broker.get_price = AsyncMock(return_value=150.0)
    # Mocking get_next_order_id to return sequential IDs to avoid overlapping dictionary issues if that's what's happening
    mock_broker.get_next_order_id = AsyncMock(side_effect=["new-sell-1", "new-sell-2", "new-sell-3", "new-sell-4"])

    async def side_effect_place_order(ticker, action, qty, limit_price, on_update=None, order_id=None, **kwargs):
        return OrderResult(order_id=order_id, status="submitted")

    mock_broker.place_limit_order = AsyncMock(side_effect=side_effect_place_order)
    mock_broker.subscribe_to_updates = MagicMock()

    # 3. Sheet Mocking (Grid total exactly matches broker 314, row 7 active)
    engine.sheet.write_cash_value = AsyncMock(return_value=True)
    engine.sheet.log_error = AsyncMock(return_value=True)
    engine.sheet.update_row_status = AsyncMock(return_value=True)

    from engine.grid_state import GridState, GridRow
    grid = GridState(rows={
        7: GridRow(row_index=7, status="OWNED:0", has_y=True, buy_price=100.0, sell_price=120.0, shares=83),
        8: GridRow(row_index=8, status="OWNED:0", has_y=True, buy_price=100.0, sell_price=110.0, shares=80),
        9: GridRow(row_index=9, status="OWNED:0", has_y=True, buy_price=100.0, sell_price=110.0, shares=77),
        10: GridRow(row_index=10, status="OWNED:0", has_y=True, buy_price=100.0, sell_price=110.0, shares=74)
    })
    engine.sheet.fetch_grid = AsyncMock(return_value=grid)
    engine.grid_state = grid

    # Un-mock _update_row_status_in_memory so it actually works in integration tests
    engine._update_row_status_in_memory = GridEngine._update_row_status_in_memory.__get__(engine, GridEngine)

    # 4. State
    engine._recent_session_cancels["order_123"] = datetime.now()
    engine.last_price = 150.0
    engine.row_cooldowns = {}
    engine._write_fresh_anchor_ask = AsyncMock()

    # Pre-check mismatch helper
    from engine.engine import _calculate_partial_fill_adjusted_required_shares
    raw, adj, part, rem, invalid = _calculate_partial_fill_adjusted_required_shares(grid.rows, [], None)
    assert adj == 314

    # Run Tick
    await engine._tick()

    # Assert
    assert engine._halted_reconciliation is False
    engine._halt_for_reconciliation_error.assert_not_called()

    assert mock_broker.place_limit_order.call_count == 4

    # Ensure OrderManager tracked the new orders properly
    assert engine.order_manager.has_open_sell(7)
    assert engine.order_manager.has_open_sell(8)
    assert engine.order_manager.has_open_sell(9)
    assert engine.order_manager.has_open_sell(10)

    # Check pending status updates
    engine.sheet.update_row_status.assert_any_call(7, "WORKING_SELL:new-sell-1")
    engine.sheet.update_row_status.assert_any_call(8, "WORKING_SELL:new-sell-2")
    engine.sheet.update_row_status.assert_any_call(9, "WORKING_SELL:new-sell-3")
    engine.sheet.update_row_status.assert_any_call(10, "WORKING_SELL:new-sell-4")

    # Check args
    calls = mock_broker.place_limit_order.call_args_list
    assert calls[0].kwargs["ticker"] == "TQQQ"
    assert calls[0].kwargs["action"] == "SELL"
    assert calls[0].kwargs["qty"] == 83
    assert calls[0].kwargs["limit_price"] == 120.0
    assert calls[0].kwargs["order_id"] == "new-sell-1"

@pytest.mark.asyncio
async def test_pre_sell_guard_debounce_exception(engine, mock_broker):
    """
    Scenario:
    - Recent cancellation was recorded.
    - Fresh fetch raises an Exception.
    - Expected: skip cycle (return False) but do not halt or crash.
    """
    broker_shares = 314
    requested_qty = 83
    row_index = 7

    engine._recent_session_cancels["stale_order"] = datetime.now()

    mock_broker.get_open_orders.side_effect = Exception("API disconnected")

    can_place = await engine._run_pre_sell_guard(requested_qty, row_index, "SELL", [], broker_shares)

    assert can_place is False
    engine._halt_for_reconciliation_error.assert_not_called()

@pytest.mark.asyncio
async def test_pre_sell_guard_unknown_status(engine, mock_broker):
    """
    Scenario:
    - Broker returns an unknown status (neither ACTIVE nor TERMINAL).
    - Expected: skip cycle (return False) but do not halt or crash.
    """
    broker_shares = 314
    requested_qty = 83
    row_index = 7

    open_orders = [
        {'order_id': 'weird_status', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 83, 'status': 'UnknownApiState123'},
    ]
    mock_broker.get_open_orders.return_value = open_orders

    can_place = await engine._run_pre_sell_guard(requested_qty, row_index, "SELL", open_orders, broker_shares)

    assert can_place is False
    engine._halt_for_reconciliation_error.assert_not_called()
