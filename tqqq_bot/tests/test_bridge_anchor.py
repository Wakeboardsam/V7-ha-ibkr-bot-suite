import pytest
from unittest.mock import AsyncMock, patch, call
from engine.engine import GridEngine
from engine.order_manager import OrderManager
from brokers.base import OrderResult, PositionSnapshot
from config.schema import AppConfig
from engine.grid_state import GridRow, GridState
from datetime import datetime
import asyncio

@pytest.fixture
def config():
    return AppConfig(
        active_broker="ibkr",
        paper_trading=True,
        ibkr_host="127.0.0.1",
        ibkr_port=7497,
        ibkr_client_id=1,
        google_sheet_id="fake_id",
        google_credentials_json="{}",
        anchor_buy_offset=1.5,
        enable_bridge_anchor=True,
        bridge_max_auto_trim_shares=5
    )

@pytest.fixture
def mock_broker():
    broker = AsyncMock()
    broker.get_next_order_id.return_value = "ORD-BRIDGE"
    broker.get_open_orders.return_value = []
    broker.place_limit_order.return_value = OrderResult(order_id="ORD-TRIM", status="submitted")
    broker.place_stop_limit_order.return_value = OrderResult(order_id="ORD-BRIDGE", status="submitted")
    return broker

@pytest.fixture
def mock_sheet():
    sheet = AsyncMock()
    return sheet

def setup_grid_state(rows_data):
    """Helper to setup basic grid state"""
    rows = {}
    for data in rows_data:
        has_y = data.get('status', 'IDLE').startswith("OWNED:") or data.get('status', 'IDLE').startswith("WORKING_SELL:")
        r = GridRow(
            row_index=data.get('row_index'),
            status=data.get('status', 'IDLE'),
            shares=data.get('shares', 10),
            buy_price=data.get('buy_price', 100.0),
            sell_price=data.get('sell_price', 105.0),
            has_y=has_y
        )
        rows[r.row_index] = r

    return GridState(rows=rows)

# 1. Bridge Anchor arms when row 7 is the only owned row and has WORKING_SELL.
@pytest.mark.asyncio
@patch('brokers.ibkr.order_builder.get_dynamic_exchange', return_value='SMART')
async def test_bridge_anchor_arms_correctly(mock_exchange, mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'WORKING_SELL:ORD-SELL-7', 'shares': 50, 'sell_price': 105.0},
        {'row_index': 8, 'status': 'IDLE'}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})

    # We must explicitly track the SELL order to satisfy condition 4
    engine.order_manager.track(7, OrderResult(order_id="ORD-SELL-7", status="submitted"), 'SELL')

    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})
    mock_broker.get_open_orders.return_value = [{'order_id': 'ORD-SELL-7', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 50, 'limit_price': 105.0, 'remaining_qty': 50, 'filled_qty': 0}]
    await engine._tick()

    # Check stop limit order was placed
    mock_broker.place_stop_limit_order.assert_called_once_with(
        ticker="TQQQ", action="BUY", qty=50,
        stop_price=105.0, limit_price=106.5, # 105.0 + 1.5 offset
        on_update=engine._handle_order_update, order_id="ORD-BRIDGE"
    )

    assert "BRIDGE_BUY:ORD-BRIDGE" in engine.grid_state.rows[7].status

# 2. Bridge Anchor does not arm when more than row 7 is owned.
@pytest.mark.asyncio
async def test_bridge_anchor_no_arm_multiple_owned(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'WORKING_SELL:ORD-SELL-7'},
        {'row_index': 8, 'status': 'WORKING_SELL:ORD-SELL-8'}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 20})
    engine.order_manager.track(7, OrderResult(order_id="ORD-SELL-7", status="submitted"), 'SELL')

    await engine._tick()
    mock_broker.place_stop_limit_order.assert_not_called()

# 3. Bridge Anchor does not arm when row 7 is not owned.
@pytest.mark.asyncio
async def test_bridge_anchor_no_arm_row7_not_owned(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'IDLE'},
        {'row_index': 8, 'status': 'WORKING_SELL:ORD-SELL-8'}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})

    await engine._tick()
    mock_broker.place_stop_limit_order.assert_not_called()

# 4. Bridge Anchor does not arm if no row 7 working sell exists.
@pytest.mark.asyncio
async def test_bridge_anchor_no_arm_no_working_sell(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:1234'},
        {'row_index': 8, 'status': 'IDLE'}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})

    await engine._tick()
    mock_broker.place_stop_limit_order.assert_not_called()

# 5. Bridge Anchor fill writes G7 using actual fill price.
@pytest.mark.asyncio
async def test_bridge_anchor_fill_writes_g7(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    # Set up active bridge order
    engine.order_manager.track(7, OrderResult(order_id="ORD-BRIDGE", status="submitted"), 'BRIDGE_BUY')

    # Simulate fill event
    fill_result = OrderResult(order_id="ORD-BRIDGE", status="filled", filled_price=106.1, filled_qty=50)
    engine._handle_order_update(fill_result)

    # Should write to G7
    # Note: the write is wrapped in asyncio.create_task so we need to yield to event loop
    await asyncio.sleep(0.01)
    mock_sheet.write_anchor_ask.assert_called_once_with(106.1)

    # Check bridge state
    assert engine._bridge_state == 'ANCHOR_RECALC_PENDING'

@pytest.mark.asyncio
async def test_bridge_mismatch_allowed_circuit_breaker(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine._bridge_state = 'ANCHOR_RECALC_PENDING'

    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:ORD-BRIDGE', 'shares': 50}
    ])

    # Broker has 50 shares, but sheet says 40 (hasn't recalced yet)
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})
    mock_sheet.fetch_grid.return_value.rows[7].shares = 40
    mock_broker.get_open_orders.return_value = []

    # Tick should not log halt
    await engine._tick()

    for call_args in mock_sheet.log_error.call_args_list:
        if isinstance(call_args[0], tuple) and call_args[0]:
            assert "CIRCUIT BREAKER" not in call_args[0][0]
        else:
            assert "CIRCUIT BREAKER" not in call_args.args[0]

# 10. Bridge Anchor cleanup.
@pytest.mark.asyncio
async def test_bridge_anchor_cleanup(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine.order_manager.track(7, OrderResult(order_id="ORD-BRIDGE", status="submitted"), 'BRIDGE_BUY')

    # Scenario: Row 7 is no longer ONLY owned row (row 8 was acquired)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'WORKING_SELL:ORD-SELL-7', 'shares': 10, 'sell_price': 105.0},
        {'row_index': 8, 'status': 'OWNED:123', 'shares': 10, 'buy_price': 100.0}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 20})
    mock_broker.get_open_orders.return_value = [{'order_id': 'ORD-SELL-7', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 10, 'limit_price': 105.0, 'remaining_qty': 10, 'filled_qty': 0}]

    await engine._tick()

    mock_broker.cancel_order.assert_called_with("ORD-BRIDGE")

# 11. Testing session behavior dynamic inherited
# Assuming it inherits adapter defaults since we pass True for outsideRth, etc implicitly based on order builder
# We verify the adapter call itself is correct, which we did in test 1.

@pytest.mark.asyncio
async def test_bridge_trim_fill_preserves_owned(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine.grid_state = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:OLD-ID|TRIM_SELL:ORD-TRIM', 'shares': 50}
    ])

    engine.order_manager.track(7, OrderResult(order_id="ORD-TRIM", status="submitted"), 'TRIM_SELL')

    fill_result = OrderResult(order_id="ORD-TRIM", status="filled", filled_price=105.0, filled_qty=2)
    engine._handle_order_update(fill_result)

    # Check that status wasn't blown away to IDLE, but is OWNED:OLD-ID
    await asyncio.sleep(0.01)

    # We don't have direct access to memory assert simply here without accessing internal calls
    # but we can look at what would be passed to sync_to_sheet if we mocked the update
    # In engine, memory is updated directly: self.grid_state.rows[7].status
    assert engine.grid_state.rows[7].status == "OWNED:OLD-ID"

@pytest.mark.asyncio
async def test_bridge_retrack_orders(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'WORKING_SELL:ORD-SELL-7|BRIDGE_BUY:ORD-BRIDGE', 'shares': 50, 'sell_price': 105.0}
    ])

    mock_broker.get_open_orders.return_value = [{'order_id': 'ORD-BRIDGE'}, {'order_id': 'ORD-SELL-7', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 50, 'limit_price': 105.0, 'remaining_qty': 50, 'filled_qty': 0}]
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})

    await engine._tick()

    # Verify both got re-tracked
    assert engine.order_manager.has_open_sell(7)
    assert engine.order_manager.has_open_action(7, 'BRIDGE_BUY')


@pytest.mark.asyncio
async def test_bridge_trim_invalid_bid_halts(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine._bridge_state = 'ANCHOR_RECALC_PENDING'
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:ORD-BRIDGE', 'shares': 52}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 54})
    mock_broker.get_bid_ask.return_value = (0.0, 100.1) # Invalid bid
    mock_broker.get_open_orders.return_value = []

    await engine._tick()

    # This specific test was to check that invalid bids halt the bridge logic instead
    # of canceling the existing order immediately without halting.
    # Because invalid bids just mark bridge state to BRIDGE_HALTED without canceling
    # any orders, we check that BRIDGE_HALTED is correctly set.
    assert engine._bridge_state == 'BRIDGE_HALTED'
    mock_sheet.log_error.assert_called()
    mock_broker.place_limit_order.assert_not_called()

@pytest.mark.asyncio
async def test_bridge_trim_invalid_limit_halts(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine._bridge_state = 'ANCHOR_RECALC_PENDING'
    engine.config.anchor_buy_offset = 1.5
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:ORD-BRIDGE', 'shares': 52}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 54})
    mock_broker.get_bid_ask.return_value = (1.0, 2.1) # current bid - offset <= 0
    mock_broker.get_open_orders.return_value = []

    await engine._tick()

    assert engine._bridge_state == 'BRIDGE_HALTED'
    mock_sheet.log_error.assert_called()
    mock_broker.place_limit_order.assert_not_called()

@pytest.mark.asyncio
async def test_bridge_trim_placement_error_halts(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine._bridge_state = 'ANCHOR_RECALC_PENDING'
    engine.config.anchor_buy_offset = 1.5
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:ORD-BRIDGE', 'shares': 52}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 54})
    mock_broker.get_bid_ask.return_value = (100.0, 100.1)
    mock_broker.get_open_orders.return_value = []
    mock_broker.place_limit_order.return_value = OrderResult(order_id="ORD-TRIM", status="error", error_msg="Mock error")

    await engine._tick()

    assert engine._bridge_state == 'BRIDGE_HALTED'
    assert not engine.order_manager.has_open_action(7, 'TRIM_SELL')

@pytest.mark.asyncio
async def test_bridge_trim_status_written(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine._bridge_state = 'ANCHOR_RECALC_PENDING'
    engine.config.anchor_buy_offset = 1.5
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:ORD-BRIDGE', 'shares': 52}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 54})
    mock_broker.get_bid_ask.return_value = (100.0, 100.1)
    mock_broker.get_open_orders.return_value = []
    mock_broker.place_limit_order.return_value = OrderResult(order_id="ORD-TRIM", status="submitted")
    mock_broker.get_next_order_id.return_value = "ORD-TRIM"

    await engine._tick()

    assert engine._bridge_state == 'TRIM_PENDING'
    assert engine.grid_state.rows[7].status == "OWNED:ORD-BRIDGE|TRIM_SELL:ORD-TRIM"


@pytest.mark.asyncio
async def test_bridge_anchor_failed_cancel_halts(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine.order_manager.track(7, OrderResult(order_id="ORD-BRIDGE", status="submitted"), 'BRIDGE_BUY')

    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'WORKING_SELL:ORD-SELL-7|BRIDGE_BUY:ORD-BRIDGE', 'shares': 10, 'sell_price': 105.0},
        {'row_index': 8, 'status': 'OWNED:123', 'shares': 10, 'sell_price': 110.0}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 20})

    engine.order_manager.track(7, OrderResult(order_id="ORD-SELL-7", status="submitted"), 'SELL')
    mock_broker.cancel_order.return_value = False

    # We must ensure get_open_orders returns correctly so it passes startup checks
    # but still shows the order is open during the failed-cancel fallback check.
    # To pass the new strict matcher, intent must map exactly.
    mock_broker.get_open_orders.return_value = [
        {'order_id': 'ORD-BRIDGE', 'ticker': 'TQQQ', 'action': 'BUY', 'order_type': 'STP LMT', 'qty': 10, 'limit_price': 105.0, 'aux_price': 105.0},
        {'order_id': 'ORD-SELL-7', 'ticker': 'TQQQ', 'action': 'SELL', 'qty': 10, 'limit_price': 105.0, 'remaining_qty': 10, 'filled_qty': 0}
    ] # Order still active!

    await engine._tick()

    assert engine._halted_reconciliation is True
    assert engine._bridge_state == 'BRIDGE_HALTED'
    assert "ORD-BRIDGE" in engine._bot_initiated_cancel_ids

    # Check it actually logged the error
    # We must await the sleep slightly to let the halt task fire
    import asyncio
    await asyncio.sleep(0.05)
    mock_sheet.append_error.assert_called_once()
    assert mock_sheet.append_error.call_args[1]['code'] == "BRIDGE_CANCEL_FAILED_HALT"

    # Local tracker state remains
    assert engine.order_manager.has_open_action(7, 'BRIDGE_BUY')

@pytest.mark.asyncio
async def test_bridge_anchor_retrack_trim_pending(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:OLD-ID|TRIM_SELL:ORD-TRIM', 'shares': 50}
    ])

    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 52})
    mock_broker.get_open_orders.return_value = [{'order_id': 'ORD-TRIM', 'qty': 2}]

    await engine._tick()

    assert engine.order_manager.has_open_action(7, 'TRIM_SELL')
    assert engine._bridge_state == 'TRIM_PENDING'
    assert engine._pending_trim_qty == 2

@pytest.mark.asyncio
async def test_bridge_anchor_retrack_trim_pending_no_qty_in_order(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:OLD-ID|TRIM_SELL:ORD-TRIM', 'shares': 50}
    ])

    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 54})
    mock_broker.get_open_orders.return_value = [{'order_id': 'ORD-TRIM'}] # no qty key in some brokers maybe

    await engine._tick()

    assert engine.order_manager.has_open_action(7, 'TRIM_SELL')
    assert engine._bridge_state == 'TRIM_PENDING'
    assert engine._pending_trim_qty == 4

@pytest.mark.asyncio
async def test_bridge_anchor_delayed_sell_fill_ignored(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)

    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'WORKING_SELL:ORD-SELL-7|BRIDGE_BUY:ORD-BRIDGE'}
    ])
    engine.order_manager.track(7, OrderResult(order_id="ORD-SELL-7", status="submitted"), 'SELL')
    engine.order_manager.track(7, OrderResult(order_id="ORD-BRIDGE", status="submitted"), 'BRIDGE_BUY')

    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0})
    mock_broker.get_open_orders.return_value = [{'order_id': 'ORD-BRIDGE'}, {'order_id': 'ORD-SELL-7', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 50, 'limit_price': 105.0, 'remaining_qty': 50, 'filled_qty': 0}]

    await engine._tick()

    # 2. BRIDGE_BUY fill arrives FIRST
    engine._handle_order_update(OrderResult(order_id="ORD-BRIDGE", status="filled", filled_price=105.0, filled_qty=10))

    assert engine._bridge_state == 'ANCHOR_RECALC_PENDING'
    assert engine.grid_state.rows[7].status == 'OWNED:ORD-BRIDGE'

    # 4. Delayed SELL fill arrives SECOND
    engine._handle_order_update(OrderResult(order_id="ORD-SELL-7", status="filled"))

    # 5. Row 7 must remain OWNED:<bridge_id>, not IDLE
    assert engine.grid_state.rows[7].status == 'OWNED:ORD-BRIDGE'
    assert engine._bridge_state == 'ANCHOR_RECALC_PENDING'

@pytest.mark.asyncio
async def test_bridge_anchor_wait_for_recalc(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine._bridge_state = 'ANCHOR_RECALC_PENDING'
    engine._bridge_fill_price = 105.0

    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:ORD-BRIDGE', 'buy_price': 100.0, 'shares': 50}
    ])

    # mock broker to perfectly match shares
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})
    mock_broker.get_open_orders.return_value = []

    await engine._tick()

    # because row 7 sell price (100.0) != 105.0, it should return early
    # it shouldn't log "Shares match perfectly" or clear the state
    assert engine._bridge_state == 'ANCHOR_RECALC_PENDING'
    # Since PR14, get_open_orders is called at the very beginning of _tick for reconciliation
    # mock_broker.get_open_orders.assert_not_called() is no longer valid.
    # But we can assert place_limit_order is not called
    mock_broker.place_limit_order.assert_not_called()

@pytest.mark.asyncio
async def test_bridge_anchor_recalc_complete(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine._bridge_state = 'ANCHOR_RECALC_PENDING'
    engine._bridge_fill_price = 105.0

    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'OWNED:ORD-BRIDGE', 'buy_price': 105.0, 'shares': 50}
    ])

    # mock broker to perfectly match shares
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})
    mock_broker.get_open_orders.return_value = []

    await engine._tick()

    # because row 7 sell price (105.0) == 105.0, it proceeds. Broker matches sheet perfectly.
    # Should clear the state.
    assert engine._bridge_state is None

@pytest.mark.asyncio
@patch('brokers.ibkr.order_builder.get_dynamic_exchange', return_value='OVERNIGHT')
async def test_bridge_anchor_skipped_during_overnight(mock_exchange, mock_broker, mock_sheet, config):
    mock_broker.get_next_order_id.side_effect = ["ORD-ID-1", "ORD-ID-2", "ORD-ID-3"]
    engine = GridEngine(mock_broker, mock_sheet, config)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'WORKING_SELL:ORD-SELL-7', 'shares': 50, 'sell_price': 105.0},
        {'row_index': 8, 'status': 'IDLE'}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})

    # Explicitly track the SELL order to satisfy condition 4
    engine.order_manager.track(7, OrderResult(order_id="ORD-SELL-7", status="submitted"), 'SELL')

    mock_broker.get_open_orders.return_value = [{'order_id': 'ORD-SELL-7', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 50, 'limit_price': 105.0, 'remaining_qty': 50, 'filled_qty': 0}]

    # Explicitly mock so condition 3 in engine.py passes
    # (there are multiple checks, one in early tick, one in bridge eval)
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})

    await engine._tick()

    # Bridge Anchor should not be placed during OVERNIGHT
    mock_broker.place_stop_limit_order.assert_not_called()
    assert not engine.order_manager.has_open_action(7, 'BRIDGE_BUY')
    assert "BRIDGE_BUY" not in engine.grid_state.rows[7].status
    assert "BRIDGE_BUY" not in engine.pending_status_updates.get(7, "")

@pytest.mark.asyncio
@patch('brokers.ibkr.order_builder.get_dynamic_exchange', return_value='SMART')
async def test_bridge_anchor_arms_during_smart(mock_exchange, mock_broker, mock_sheet, config):
    mock_broker.get_next_order_id.side_effect = ["ORD-BRIDGE", "ORD-ID-1", "ORD-ID-2"]
    engine = GridEngine(mock_broker, mock_sheet, config)
    mock_sheet.fetch_grid.return_value = setup_grid_state([
        {'row_index': 7, 'status': 'WORKING_SELL:ORD-SELL-7', 'shares': 50, 'sell_price': 105.0},
        {'row_index': 8, 'status': 'IDLE'}
    ])
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})

    # Explicitly track the SELL order to satisfy condition 4
    engine.order_manager.track(7, OrderResult(order_id="ORD-SELL-7", status="submitted"), 'SELL')

    mock_broker.get_open_orders.return_value = [{'order_id': 'ORD-SELL-7', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 50, 'limit_price': 105.0, 'remaining_qty': 50, 'filled_qty': 0}]

    # Explicitly mock so condition 3 in engine.py passes
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})
