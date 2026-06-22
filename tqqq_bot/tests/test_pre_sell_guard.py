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
