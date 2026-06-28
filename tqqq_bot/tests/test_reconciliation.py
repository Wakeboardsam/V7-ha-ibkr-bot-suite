import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

from config.schema import AppConfig
from engine.engine import GridEngine
from engine.grid_state import GridState, GridRow
from brokers.base import OrderResult, PositionSnapshot
from sheets.interface import SheetInterface

@pytest.fixture
def mock_config():
    return AppConfig(
        google_sheet_id="test_sheet",
        google_credentials_json="{}",
        ibkr_host="127.0.0.1",
        ibkr_port=7497,
        ibkr_client_id=1,
        ibkr_paper=True,
        poll_interval_seconds=1,
        dry_run=False,
        maintenance_enabled=False,
    )

@pytest.fixture
def mock_broker():
    broker = AsyncMock()
    broker.get_open_orders.return_value = []
    broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0})
    broker.get_wallet_balance.return_value = 100000.0
    broker.get_price.return_value = 80.0
    broker.get_next_order_id.return_value = "100"
    return broker

@pytest.fixture
def mock_sheet():
    sheet = AsyncMock(spec=SheetInterface)
    sheet.fetch_grid.return_value = GridState(rows={})
    return sheet

@pytest.fixture
def engine(mock_broker, mock_sheet, mock_config):
    return GridEngine(broker=mock_broker, sheet=mock_sheet, config=mock_config)


@pytest.mark.asyncio
async def test_startup_mismatch_halt(engine, mock_broker, mock_sheet):
    """
    Test A: Startup mismatch halt
    - Tracker row 7 says owned or working sell for 136 shares.
    - Broker position is 0.
    - Broker open orders are 0.
    """
    mock_sheet.fetch_grid.return_value = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:10", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0})

    await engine._tick()

    assert engine._halted_reconciliation is True
    assert mock_broker.place_limit_order.call_count == 0
    mock_sheet.append_error.assert_called_once()
    call_args = mock_sheet.append_error.call_args[1]
    assert call_args['code'] == "SELL_POSITION_MISMATCH_HALT"

@pytest.mark.asyncio
async def test_startup_aggregate_mismatch(engine, mock_broker, mock_sheet):
    """
    Test A2: Startup Aggregate Mismatch
    - Row 7 requires 100 shares
    - Row 8 requires 100 shares
    - Broker has 150 shares
    - Expected halt with SELL_POSITION_MISMATCH_HALT
    """
    mock_sheet.fetch_grid.return_value = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=100),
        8: GridRow(row_index=8, status="OWNED:0", has_y=True, sell_price=79.70, buy_price=79.00, shares=100)
    })
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 150})

    await engine._tick()

    assert engine._halted_reconciliation is True
    assert mock_broker.place_limit_order.call_count == 0
    mock_sheet.append_error.assert_called_once()
    call_args = mock_sheet.append_error.call_args[1]
    assert call_args['code'] == "SELL_POSITION_MISMATCH_HALT"
    assert call_args['row'] == "AGGREGATE"


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_field", ["side", "qty", "price"])
async def test_strict_external_order_mismatch(engine, mock_broker, mock_sheet, wrong_field):
    """
    Test strict external order matching.
    If order ID matches but side, qty, or price doesn't perfectly match intent, halt.
    """
    mock_sheet.fetch_grid.return_value = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 136})

    action = "SELL" if wrong_field != "side" else "BUY"
    qty = 136 if wrong_field != "qty" else 50
    price = 78.70 if wrong_field != "price" else 99.0

    mock_broker.get_open_orders.return_value = [
        {'order_id': '100', 'action': action, 'ticker': 'TQQQ', 'qty': qty, 'limit_price': price}
    ]

    await engine._tick()

    assert engine._halted_reconciliation is True
    assert mock_broker.place_limit_order.call_count == 0
    mock_sheet.append_error.assert_called_once()
    call_args = mock_sheet.append_error.call_args[1]
    assert call_args['code'] == "EXTERNAL_OPEN_ORDER_RECONCILE_REQUIRED"


@pytest.mark.asyncio
async def test_pre_sell_guard(engine, mock_broker, mock_sheet):
    """
    Test B: Pre-sell guard
    - Broker position is 0.
    - Engine attempts SELL 136.
    """
    # Start with matching so it doesn't fail the startup check
    mock_sheet.fetch_grid.return_value = GridState(rows={
        7: GridRow(row_index=7, status="OWNED:0", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })

    # We fake the check inside _tick to pretend the snapshot returns 0 when checking before place_limit_order
    # by letting the startup check pass with 136, then swapping broker_shares... actually, if it has 136 at startup
    # it's fine. Wait, if broker has 0 at startup it fails Test A. We can just bypass the startup check to test
    # the pre-sell guard specifically, or let startup check see 136, but the snapshot for pre-sell guard sees 0.
    # The pre-sell guard uses `broker_shares` which is fetched at the top of _tick.

    # The pre-sell guard in the grid loop won't be reached if the circuit breaker trips.
    # To test the pre-sell guard specifically, we need to let the circuit breaker pass
    # (meaning we set config.share_mismatch_mode to 'warn' instead of 'halt')
    # and bypass the startup check.
    engine.config.share_mismatch_mode = "warn"
    engine._halted_reconciliation = False

    with patch.object(engine, '_check_reconciliation_and_halt', new_callable=AsyncMock):
        mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0})
        await engine._tick()

        assert engine._halted_reconciliation is True
        assert mock_broker.place_limit_order.call_count == 0
        mock_sheet.append_error.assert_called_once()
        call_args = mock_sheet.append_error.call_args[1]
        assert call_args['code'] == "SELL_POSITION_MISMATCH_HALT"


@pytest.mark.asyncio
async def test_valid_sell(engine, mock_broker, mock_sheet):
    """
    Test C: Valid sell
    - Broker position is 136.
    - No working sell orders.
    - Engine attempts SELL 136.
    """
    mock_sheet.fetch_grid.return_value = GridState(rows={
        7: GridRow(row_index=7, status="OWNED:0", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 136})
    mock_broker.place_limit_order.return_value = OrderResult(order_id="100", status="submitted")

    await engine._tick()

    assert engine._halted_reconciliation is False
    mock_broker.place_limit_order.assert_called_once()
    args, kwargs = mock_broker.place_limit_order.call_args
    assert kwargs['action'] == 'SELL'
    assert kwargs['qty'] == 136


@pytest.mark.asyncio
async def test_over_sell_guard(engine, mock_broker, mock_sheet):
    """
    Test D: Over-sell guard
    - Broker position is 136.
    - Broker already has working SELL 100.
    - Engine attempts another SELL 136.
    """
    mock_sheet.fetch_grid.return_value = GridState(rows={
        7: GridRow(row_index=7, status="OWNED:0", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 136})
    # Untracked external working sell of 100
    mock_broker.get_open_orders.return_value = [{'order_id': '99', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 100, 'status': 'Submitted', 'remaining_qty': 100}]

    with patch.object(engine, '_check_reconciliation_and_halt', new_callable=AsyncMock):
        await engine._tick()

        assert engine._halted_reconciliation is True
        assert mock_broker.place_limit_order.call_count == 0
        mock_sheet.append_error.assert_called_once()


@pytest.mark.asyncio
async def test_immediate_sell_error_halt(engine, mock_broker, mock_sheet):
    """
    Test Immediate place_limit_order SELL error
    - broker returns OrderResult(status="error", error_code=201)
    """
    mock_sheet.fetch_grid.return_value = GridState(rows={
        7: GridRow(row_index=7, status="OWNED:0", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 136})
    mock_broker.place_limit_order.return_value = OrderResult(
        order_id="100", status="error", error_code=201, error_msg="Short stock positions can only be held in a margin account"
    )

    await engine._tick()

    assert engine._halted_reconciliation is True
    # Let tasks finish
    await asyncio.sleep(0.01)
    mock_sheet.append_error.assert_called_once()
    call_args = mock_sheet.append_error.call_args[1]
    assert call_args['code'] == "IBKR_SHORT_REJECTION_HALT"
    # The status gets synced immediately. Let's check grid state directly.
    assert engine.grid_state.rows[7].status == "ERROR_RECONCILE_REQUIRED:IBKR_SHORT_REJECTION_HALT"

@pytest.mark.asyncio
async def test_immediate_generic_sell_error_halt(engine, mock_broker, mock_sheet):
    """
    Test Immediate place_limit_order generic SELL error
    - broker returns OrderResult(status="error", error_msg="some broker error")
    """
    mock_sheet.fetch_grid.return_value = GridState(rows={
        7: GridRow(row_index=7, status="OWNED:0", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 136})
    mock_broker.place_limit_order.return_value = OrderResult(
        order_id="100", status="error", error_msg="some broker error"
    )

    await engine._tick()

    assert engine._halted_reconciliation is True
    await asyncio.sleep(0.01)
    mock_sheet.append_error.assert_called_once()
    call_args = mock_sheet.append_error.call_args[1]
    assert call_args['code'] == "SELL_ORDER_ERROR_RECONCILE_REQUIRED"
    assert engine.grid_state.rows[7].status == "ERROR_RECONCILE_REQUIRED:SELL_ORDER_ERROR_RECONCILE_REQUIRED"

@pytest.mark.asyncio
async def test_immediate_generic_trim_sell_error_halt(engine, mock_broker, mock_sheet):
    """
    Test Immediate place_limit_order generic TRIM_SELL error
    - expected hard halt, BRIDGE_HALTED, Errors row, Health halt
    """
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })

    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 150})
    # Set bridge state to trigger the trim order logic
    engine._bridge_state = 'ANCHOR_RECALC_PENDING'

    # Simulate a generic error on placement
    mock_broker.place_limit_order.return_value = OrderResult(
        order_id="101", status="error", error_msg="some trim broker error"
    )
    # Give a dummy bid/ask so trim logic runs
    mock_broker.get_bid_ask.return_value = (78.0, 78.1)

    # Track order manager intent to bypass pre-sell guard's local pending checks
    # The pre-sell guard relies on `broker_working_sell_qty` and `bot_pending_sell_qty`.
    # Wait, the pre-sell guard for TRIM_SELL checks:
    # available_to_sell = broker_shares(150) - 0 - 0 = 150.
    # excess is 150 - 136 = 14.
    # 150 >= 14, so it should PASS the pre-sell guard.

    with patch.object(engine, '_check_reconciliation_and_halt', new_callable=AsyncMock):
        # mock broker.get_open_orders to return empty so it doesn't fail pre-sell guard math for trim
        mock_broker.get_open_orders.return_value = [{'order_id': '100', 'action': 'SELL', 'ticker': 'TQQQ', 'status': 'Submitted', 'remaining_qty': 136, 'filled_qty': 0, 'qty': 136, 'limit_price': 78.70}]
        engine.config.bridge_max_auto_trim_shares = 20 # increase max trim otherwise it halts before place_limit_order

        # Since _tick() calls fetch_grid(), we need to mock it properly here again
        # The test previously set engine.grid_state before calling _tick(), but fetch_grid overrides it.
        mock_sheet.fetch_grid.return_value = GridState(rows={
            7: GridRow(row_index=7, status="WORKING_SELL:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
        })

        await engine._tick()

    assert engine._halted_reconciliation is True
    assert engine._bridge_state == 'BRIDGE_HALTED'
    await asyncio.sleep(0.01)
    mock_sheet.append_error.assert_called_once()
    call_args = mock_sheet.append_error.call_args[1]
    assert call_args['code'] == "TRIM_SELL_ORDER_ERROR_RECONCILE_REQUIRED"

@pytest.mark.asyncio
async def test_bot_initiated_sell_cancel(engine, mock_broker, mock_sheet):
    """
    Test bot-initiated SELL cancel
    - Mark order as bot-initiated cancel
    - Simulate cancelled/no-fill SELL
    - Expected: ownership preserved, no error halt
    """
    engine.order_manager.track(7, OrderResult(order_id="100", status="submitted"), 'SELL')
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })

    # Mark intent
    engine._bot_initiated_cancel_ids["100"] = {
        "reason": "maintenance",
        "row": 7,
        "action": "SELL",
        "timestamp": datetime.now()
    }

    result = OrderResult(order_id="100", status="cancelled", filled_qty=0)
    engine._handle_order_update(result)

    await asyncio.sleep(0.01)

    assert engine._halted_reconciliation is False
    assert engine.grid_state.rows[7].status == "OWNED:0"
    mock_sheet.append_error.assert_not_called()

@pytest.mark.asyncio
async def test_unexpected_sell_cancel_halt(engine, mock_broker, mock_sheet):
    """
    Test unexpected SELL cancel
    - No bot-initiated marker
    - Simulate cancelled/no-fill SELL
    - Expected: ERROR_RECONCILE_REQUIRED halt
    """
    engine.order_manager.track(7, OrderResult(order_id="100", status="submitted"), 'SELL')
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })

    # No intent marked
    result = OrderResult(order_id="100", status="cancelled", filled_qty=0)
    engine._handle_order_update(result)

    await asyncio.sleep(0.01)

    assert engine._halted_reconciliation is True
    assert engine.grid_state.rows[7].status == "ERROR_RECONCILE_REQUIRED:SELL_CANCELLED_NO_FILL_HALT"
    mock_sheet.append_error.assert_called_once()

@pytest.mark.asyncio
async def test_async_ibkr_201_rejection(engine, mock_broker, mock_sheet):
    """
    Test E: Async IBKR 201 rejection
    - SELL order receives error 201 / short-sale rejection.
    """
    engine.order_manager.track(7, OrderResult(order_id="100", status="submitted"), 'SELL')

    # To avoid KeyError: 7 when checking engine.pending_status_updates[7], we need to set grid state
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })

    # Simulate a rejection via _handle_order_update
    result = OrderResult(order_id="100", status="error", error_code=201, error_msg="Short stock positions can only be held in a margin account", reason="Rejected")
    engine._handle_order_update(result)

    # since it's queued in an async task from a sync context, we need to let the task run
    await asyncio.sleep(0.05)

    assert engine._halted_reconciliation is True
    # Let the background sync task run
    await asyncio.sleep(0)
    mock_sheet.append_error.assert_called_once()
    call_args = mock_sheet.append_error.call_args[1]
    assert call_args['code'] == "IBKR_SHORT_REJECTION_HALT"

    # Check grid state
    assert engine.grid_state.rows[7].status == "ERROR_RECONCILE_REQUIRED:IBKR_SHORT_REJECTION_HALT"


@pytest.mark.asyncio
async def test_bridge_guard(engine, mock_broker, mock_sheet):
    """
    Test F: Bridge guard
    - Tracker row 7 has bridge/anchor state with 136 shares.
    - Broker position is 0.
    """
    engine.config.enable_bridge_anchor = True
    # Set it up so it would normally place the bridge anchor:
    # 1. Row 7 is only owned row
    # 2. Row 7 has an active SELL
    # 3. No existing bridge anchor
    mock_sheet.fetch_grid.return_value = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })

    engine.order_manager.track(7, OrderResult(order_id="100", status="submitted"), 'SELL')

    # To test bridge guard, we need to let the circuit breaker pass
    engine.config.share_mismatch_mode = "warn"

    # To test the bridge guard specifically and explicitly, we call `_evaluate_bridge_anchor`
    # directly. In real operation, the startup `SELL_POSITION_MISMATCH_HALT` guard
    # catches it earlier. But we must verify the bridge guard itself works and emits
    # the specific error.

    # Needs to match all bridge anchor conditions to reach place_stop_limit_order
    # EXCEPT the broker shares. So we set shares to 0.
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0})
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })

    await engine._evaluate_bridge_anchor()

    assert engine._halted_reconciliation is True
    assert mock_broker.place_stop_limit_order.call_count == 0
    # Let task finish
    await asyncio.sleep(0.01)
    mock_sheet.append_error.assert_called_once()
    call_args = mock_sheet.append_error.call_args[1]
    assert call_args['code'] == "BRIDGE_POSITION_MISMATCH_HALT"
    assert engine.grid_state.rows[7].status == "ERROR_RECONCILE_REQUIRED:BRIDGE_POSITION_MISMATCH_HALT"

@pytest.mark.asyncio
async def test_live_false_halt_case_partial_fill(engine, mock_broker, mock_sheet):
    """
    Live false-halt case:
    raw required = 714 (348 owned + 101 + 94 + 88 + 83 working sells)
    broker position = 666
    order partially filled 48 of 83
    broker remaining_qty = 35
    adjusted required = 666
    expected: no halt
    """
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="OWNED:0", has_y=True, sell_price=10.0, buy_price=9.0, shares=348),
        8: GridRow(row_index=8, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=101),
        9: GridRow(row_index=9, status="WORKING_SELL:102", has_y=True, sell_price=10.0, buy_price=9.0, shares=94),
        10: GridRow(row_index=10, status="WORKING_SELL:103", has_y=True, sell_price=10.0, buy_price=9.0, shares=88),
        11: GridRow(row_index=11, status="WORKING_SELL:477", has_y=True, sell_price=10.0, buy_price=9.0, shares=83)
    })

    open_orders = [
        {'order_id': '101', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 101, 'limit_price': 10.0, 'remaining_qty': 101, 'filled_qty': 0},
        {'order_id': '102', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 94, 'limit_price': 10.0, 'remaining_qty': 94, 'filled_qty': 0},
        {'order_id': '103', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 88, 'limit_price': 10.0, 'remaining_qty': 88, 'filled_qty': 0},
        {'order_id': '477', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 83, 'limit_price': 10.0, 'remaining_qty': 35, 'filled_qty': 48}
    ]

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=666)
    assert engine._halted_reconciliation is False


@pytest.mark.asyncio
async def test_live_false_halt_case_broker_too_low(engine, mock_broker, mock_sheet):
    """
    Broker position too low:
    same setup but broker position = 665
    expected: halt/manual reconcile
    """
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="OWNED:0", has_y=True, sell_price=10.0, buy_price=9.0, shares=348),
        8: GridRow(row_index=8, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=101),
        9: GridRow(row_index=9, status="WORKING_SELL:102", has_y=True, sell_price=10.0, buy_price=9.0, shares=94),
        10: GridRow(row_index=10, status="WORKING_SELL:103", has_y=True, sell_price=10.0, buy_price=9.0, shares=88),
        11: GridRow(row_index=11, status="WORKING_SELL:477", has_y=True, sell_price=10.0, buy_price=9.0, shares=83)
    })

    open_orders = [
        {'order_id': '101', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 101, 'limit_price': 10.0, 'remaining_qty': 101, 'filled_qty': 0},
        {'order_id': '102', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 94, 'limit_price': 10.0, 'remaining_qty': 94, 'filled_qty': 0},
        {'order_id': '103', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 88, 'limit_price': 10.0, 'remaining_qty': 88, 'filled_qty': 0},
        {'order_id': '477', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 83, 'limit_price': 10.0, 'remaining_qty': 35, 'filled_qty': 48}
    ]

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=665)
    assert engine._halted_reconciliation is True
    call_args = engine._last_reconciliation_halt
    assert call_args['code'] == "SELL_POSITION_MISMATCH_HALT"


@pytest.mark.asyncio
async def test_missing_open_order_halts(engine, mock_broker, mock_sheet):
    """
    Missing open order:
    sheet has "WORKING_SELL:<order_id>"
    broker open orders do not include that order
    expected: halt/manual reconcile, no partial-fill pass
    """
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=101)
    })
    engine.order_manager.track(7, OrderResult(order_id="101", status="submitted"), "SELL")

    # Missing order 101
    open_orders = []

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=100)
    assert engine._halted_reconciliation is True
    call_args = engine._last_reconciliation_halt
    assert call_args['code'] == "SELL_POSITION_MISMATCH_HALT"


@pytest.mark.asyncio
async def test_invalid_remaining_quantity_halts(engine, mock_broker, mock_sheet):
    """
    Invalid remaining quantity:
    remaining_qty > row.shares
    expected: halt/manual reconcile
    """
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=101)
    })
    engine.order_manager.track(7, OrderResult(order_id="101", status="submitted"), "SELL")

    open_orders = [
        {'order_id': '101', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 101, 'limit_price': 10.0, 'remaining_qty': 102, 'filled_qty': 0}
    ]

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=100)
    assert engine._halted_reconciliation is True
    call_args = engine._last_reconciliation_halt
    assert call_args['code'] == "SELL_POSITION_MISMATCH_HALT"


@pytest.mark.asyncio
async def test_multiple_partially_filled_working_sells(engine, mock_broker, mock_sheet):
    """
    Multiple partially filled working sells:
    adjustments aggregate correctly
    """
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=100),
        8: GridRow(row_index=8, status="WORKING_SELL:102", has_y=True, sell_price=10.0, buy_price=9.0, shares=100)
    })

    open_orders = [
        {'order_id': '101', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 100, 'limit_price': 10.0, 'remaining_qty': 90, 'filled_qty': 10},
        {'order_id': '102', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 100, 'limit_price': 10.0, 'remaining_qty': 80, 'filled_qty': 20}
    ]

    # 200 raw - (10 + 20) = 170 adjusted required
    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=170)
    assert engine._halted_reconciliation is False

import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from app.engine.engine import GridEngine, _calculate_partial_fill_adjusted_required_shares
from app.engine.grid_state import GridState, GridRow
from app.config.schema import AppConfig
from app.brokers.base import OrderResult









@pytest.mark.asyncio
async def test_working_sell_missing_and_shares_match(engine, mock_broker, mock_sheet):
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=101)
    })


    open_orders = [] # missing

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=101)
    assert engine._halted_reconciliation is True

@pytest.mark.asyncio
async def test_remaining_qty_none_and_shares_match(engine, mock_broker, mock_sheet):
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=101)
    })


    open_orders = [
        {'order_id': '101', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 101, 'limit_price': 10.0, 'remaining_qty': None, 'filled_qty': 0}
    ]

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=101)
    assert engine._halted_reconciliation is True

@pytest.mark.asyncio
async def test_remaining_qty_greater_and_shares_match(engine, mock_broker, mock_sheet):
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=101)
    })


    open_orders = [
        {'order_id': '101', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 101, 'limit_price': 10.0, 'remaining_qty': 102, 'filled_qty': 0}
    ]

    await engine._check_reconciliation_and_halt(open_orders=open_orders, broker_shares=101)
    assert engine._halted_reconciliation is True

@pytest.mark.asyncio
async def test_runtime_missing_open_order_halts(engine, mock_broker, mock_sheet):
    """
    Runtime _tick missing open order:
    sheet has "WORKING_SELL:<order_id>"
    broker open orders do not include that order
    broker_shares differs by exactly that row's shares
    expected: halt/manual reconcile and MUST NOT update the row to IDLE (no auto-reconciliation)
    """
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:101", has_y=True, sell_price=10.0, buy_price=9.0, shares=101)
    })
    engine.order_manager.track(7, OrderResult(order_id="101", status="submitted"), "SELL")

    # Missing order 101
    mock_broker.get_open_orders.return_value = [{'order_id': '100', 'action': 'SELL', 'ticker': 'TQQQ', 'remaining_qty': 136, 'filled_qty': 0, 'qty': 136, 'limit_price': 78.70}]
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0})
    mock_sheet.fetch_grid.return_value = engine.grid_state

    # We call _tick instead of _check_reconciliation_and_halt
    # We need to make sure distal_y_row returns a valid row
    from unittest.mock import patch
    with patch('app.engine.grid_state.GridState.distal_y_row', return_value=7):
        await engine._tick()

    assert engine._halted_reconciliation is True
    # Verify no row status update happened to IDLE
    mock_sheet.update_row_status.assert_not_called()
