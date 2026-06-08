from brokers.base import PositionSnapshot
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from engine.engine import GridEngine
from engine.grid_state import GridState, GridRow
from brokers.base import OrderResult
from config.schema import AppConfig

@pytest.fixture
def mock_broker():
    broker = AsyncMock()
    broker.connect = AsyncMock(return_value=True)
    broker.disconnect = AsyncMock()
    broker.ensure_connected = AsyncMock()
    broker.get_bid_ask = AsyncMock(return_value=(99.95, 100.05))
    broker.place_limit_order = AsyncMock(return_value=OrderResult(order_id="ORD-123", status="submitted"))
    broker.get_open_orders = AsyncMock(return_value=[])
    from brokers.base import PositionSnapshot
    broker.get_position_snapshot = AsyncMock(return_value=PositionSnapshot(is_ready=True, positions={"TQQQ": 0}))
    broker.subscribe_to_updates = MagicMock()
    broker.cancel_order = AsyncMock(return_value=True)
    broker.get_next_order_id = AsyncMock(return_value="ORD-123")
    return broker

@pytest.fixture
def mock_sheet():
    sheet = AsyncMock()
    sheet.log_fill = AsyncMock(return_value=True)
    sheet.log_error = AsyncMock(return_value=True)
    sheet.log_health = AsyncMock(return_value=True)
    sheet.update_row_status = AsyncMock(return_value=True)
    sheet.write_cash_value = AsyncMock(return_value=True)
    return sheet

@pytest.fixture
def config():
    return AppConfig(
        google_sheet_id="test_sheet",
        google_credentials_json='{"test": "json"}',
        poll_interval_seconds=1,
        max_spread_pct=0.5
    )

@pytest.mark.asyncio
async def test_transition_idle_to_working_buy(mock_broker, mock_sheet, config):
    grid_state = GridState(rows={
        10: GridRow(row_index=10, status="IDLE", has_y=False, sell_price=110.0, buy_price=105.0, shares=10)
    })
    mock_sheet.fetch_grid.return_value = grid_state
    mock_broker.place_limit_order.return_value = OrderResult(order_id="BUY-123", status="submitted")

    engine = GridEngine(mock_broker, mock_sheet, config)
    # Mock distal_y = 7, so row 10 is in window [7, 10]
    with patch.object(GridState, 'distal_y_row', 7):
        await engine._tick()

    mock_sheet.update_row_status.assert_called_with(10, "WORKING_BUY:BUY-123")

@pytest.mark.asyncio
async def test_transition_working_buy_to_owned(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    # Manually track an order
    engine.order_manager.track(10, OrderResult(order_id="BUY-123", status="submitted"), 'BUY')

    # Simulate fill
    result = OrderResult(order_id='BUY-123', status='filled', filled_price=105.0, filled_qty=10)
    engine._handle_order_update(result)

    # Wait for the async task in _handle_order_update
    await asyncio.sleep(0.1)

    mock_sheet.update_row_status.assert_called_with(10, "OWNED:BUY-123")

@pytest.mark.asyncio
async def test_transition_owned_to_working_sell(mock_broker, mock_sheet, config):
    grid_state = GridState(rows={
        10: GridRow(row_index=10, status="OWNED:BUY-123", has_y=True, sell_price=110.0, buy_price=105.0, shares=10)
    })
    mock_sheet.fetch_grid.return_value = grid_state
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})
    mock_broker.place_limit_order.return_value = OrderResult(order_id="SELL-456", status="submitted")

    engine = GridEngine(mock_broker, mock_sheet, config)
    # Row 10 is in window
    with patch.object(GridState, 'distal_y_row', 10):
        # We need to make sure get_next_order_id returns something consistent if we check it
        mock_broker.get_next_order_id.return_value = "SELL-456"
        await engine._tick()

    mock_sheet.update_row_status.assert_called_with(10, "WORKING_SELL:SELL-456")

@pytest.mark.asyncio
async def test_transition_working_sell_to_idle(mock_broker, mock_sheet, config):
    engine = GridEngine(mock_broker, mock_sheet, config)
    # Manually track an order
    engine.order_manager.track(10, OrderResult(order_id="SELL-456", status="submitted"), 'SELL')

    # Simulate fill
    result = OrderResult(order_id='SELL-456', status='filled', filled_price=110.0, filled_qty=10)
    engine._handle_order_update(result)

    # Wait for the async task in _handle_order_update
    await asyncio.sleep(0.1)

    mock_sheet.update_row_status.assert_called_with(10, "IDLE")

@pytest.mark.asyncio
async def test_cancel_outside_window_working_buy(mock_broker, mock_sheet, config):
    grid_state = GridState(rows={
        15: GridRow(row_index=15, status="WORKING_BUY:BUY-123", has_y=False, sell_price=150.0, buy_price=145.0, shares=10)
    })
    mock_sheet.fetch_grid.return_value = grid_state
    mock_broker.get_open_orders.return_value = [{'order_id': 'BUY-123', 'action': 'BUY'}]

    engine = GridEngine(mock_broker, mock_sheet, config)
    # distal_y = 7, window [7, 10]. Row 15 is outside.
    with patch.object(GridState, 'distal_y_row', 7):
        await engine._tick()

    # Should cancel and update to IDLE
    mock_broker.cancel_order.assert_called_with("BUY-123")
    mock_sheet.update_row_status.assert_called_with(15, "IDLE")

@pytest.mark.asyncio
async def test_cancel_outside_window_working_sell(mock_broker, mock_sheet, config):
    grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:SELL-456|OWNED:BUY-123", has_y=True, sell_price=105.0, buy_price=100.0, shares=10)
    })
    mock_sheet.fetch_grid.return_value = grid_state
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})
    mock_broker.get_open_orders.return_value = [{'order_id': 'SELL-456', 'action': 'SELL'}]

    engine = GridEngine(mock_broker, mock_sheet, config)
    # distal_y = 15, window [12, 18]. Row 7 is outside.
    with patch.object(GridState, 'distal_y_row', 15):
        await engine._tick()

    # Should cancel and update to OWNED:BUY-123
    mock_broker.cancel_order.assert_called_with("SELL-456")
    mock_sheet.update_row_status.assert_called_with(7, "OWNED:BUY-123")

@pytest.mark.asyncio
async def test_owned_fallback_enforcement(mock_broker, mock_sheet, config):
    # Testing the case where we have WORKING_SELL but NO OWNED info, and it goes outside window
    grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:SELL-456", has_y=True, sell_price=105.0, buy_price=100.0, shares=10)
    })
    mock_sheet.fetch_grid.return_value = grid_state
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})
    mock_broker.get_open_orders.return_value = [{'order_id': 'SELL-456', 'action': 'SELL'}]

    engine = GridEngine(mock_broker, mock_sheet, config)
    # distal_y = 15, window [12, 18]. Row 7 is outside.
    with patch.object(GridState, 'distal_y_row', 15):
        await engine._tick()

    # Current behavior might be "OWNED", but we want to enforce "OWNED:0" or similar if ID is missing.
    # The requirement says "Confirm the bot only writes these status patterns to C7:C100: WORKING_BUY:12345, WORKING_SELL:12345, OWNED:12345, IDLE"
    # So "OWNED" without ID might be forbidden if we are being strict.
    mock_sheet.update_row_status.assert_called_with(7, "OWNED:0")

@pytest.mark.asyncio
async def test_retrack_parsing(mock_broker, mock_sheet, config):
    # Verify that we correctly parse the complex status string and re-track orders
    grid_state = GridState(rows={
        7: GridRow(row_index=7, status="WORKING_SELL:SELL-123|OWNED:BUY-789", has_y=True, sell_price=105.0, buy_price=100.0, shares=10)
    })
    mock_sheet.fetch_grid.return_value = grid_state
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})
    mock_broker.get_open_orders.return_value = [{'order_id': 'SELL-123', 'action': 'SELL'}]

    engine = GridEngine(mock_broker, mock_sheet, config)
    with patch.object(GridState, 'distal_y_row', 7):
        await engine._tick()

    assert engine.order_manager.is_tracked("SELL-123")
    assert engine.order_manager.has_open_sell(7)
    # It should NOT update status since it's already correct
    mock_sheet.update_row_status.assert_not_called()
