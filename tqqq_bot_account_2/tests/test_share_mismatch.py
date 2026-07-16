from brokers.base import PositionSnapshot
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
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
    broker.get_price = AsyncMock(return_value=100.0)
    broker.get_wallet_balance = AsyncMock(return_value=50000.0)
    broker.get_bid_ask = AsyncMock(return_value=(99.95, 100.05))
    broker.place_limit_order = AsyncMock(return_value=OrderResult(order_id="ORD-NEW", status="submitted"))
    broker.get_open_orders = AsyncMock(return_value=[])
    from brokers.base import PositionSnapshot
    broker.get_position_snapshot = AsyncMock(return_value=PositionSnapshot(is_ready=True, positions={"TQQQ": 0}))
    broker.subscribe_to_updates = MagicMock()
    broker.get_next_order_id = AsyncMock(return_value="ORD-NEW")
    return broker

@pytest.fixture
def mock_sheet():
    sheet = AsyncMock()
    # Row 7 is owned, Row 8 is empty.
    grid_state = GridState(
        rows={
            7: GridRow(row_index=7, status="OWNED", has_y=True, sell_price=105.0, buy_price=100.0, shares=10),
            8: GridRow(row_index=8, status="IDLE", has_y=False, sell_price=110.0, buy_price=105.0, shares=10)
        }
    )
    sheet.fetch_grid = AsyncMock(return_value=grid_state)
    sheet.log_error = AsyncMock(return_value=True)
    sheet.update_row_status = AsyncMock(return_value=True)
    return sheet

@pytest.fixture
def config():
    return AppConfig(
        google_sheet_id="test_sheet",
        google_credentials_json='{"test": "json"}',
        poll_interval_seconds=1,
        max_spread_pct=0.5,
        share_mismatch_mode="halt"
    )

@pytest.mark.asyncio
async def test_share_mismatch_halt(mock_broker, mock_sheet, config):
    config.share_mismatch_mode = "halt"
    # Sheet says 10 shares (row 7), Broker says 0.
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0})

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # Should log error and return early
    mock_sheet.log_error.assert_called()
    assert mock_broker.place_limit_order.call_count == 0

@pytest.mark.asyncio
async def test_share_mismatch_warn(mock_broker, mock_sheet, config):
    config.share_mismatch_mode = "warn"
    # Sheet says 10 shares (row 7), Broker says 0. Mismatch!
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0})

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # 1. Should log error to sheet
    mock_sheet.log_error.assert_called()

    # 2. Should STILL perform reconciliation (get_open_orders is called)
    mock_broker.get_open_orders.assert_called()

    # 3. Should HALT because of hard pre-sell guard (available_to_sell=0, requested=10)
    assert engine._halted_reconciliation is True

    # 4. Should NOT place SELL order for row 7
    assert mock_broker.place_limit_order.call_count == 0

@pytest.mark.asyncio
async def test_share_mismatch_warn_retracking(mock_broker, mock_sheet, config):
    config.share_mismatch_mode = "warn"
    # To test re-tracking we need to provide enough shares to bypass the hard halt guard
    # Grid claims 10 shares, we will provide 10 so it doesn't halt early
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})

    # Existing order in status
    grid_state = GridState(
        rows={
            7: GridRow(row_index=7, status="WORKING_SELL:ORD-EXISTING", has_y=True, sell_price=105.0, buy_price=100.0, shares=10),
        }
    )
    mock_sheet.fetch_grid.return_value = grid_state
    mock_broker.get_open_orders.return_value = [{'order_id': 'ORD-EXISTING', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 10, 'limit_price': 105.0, 'remaining_qty': 10, 'filled_qty': 0}]

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # Should re-track existing order
    assert engine.order_manager.is_tracked("ORD-EXISTING")
    # Should not place new order because it's already working
    assert mock_broker.place_limit_order.call_count == 0

@pytest.mark.asyncio
async def test_share_mismatch_warn_outside_window(mock_broker, mock_sheet, config):
    config.share_mismatch_mode = "warn"
    # Provide enough shares to bypass early halt guard
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})

    # distal_y is 7. Window is [7, 10].
    # Let's put a row outside the window.
    grid_state = GridState(
        rows={
            7: GridRow(row_index=7, status="OWNED", has_y=True, sell_price=105.0, buy_price=100.0, shares=10),
            15: GridRow(row_index=15, status="WORKING_BUY:ORD-OUTSIDE", has_y=False, sell_price=150.0, buy_price=145.0, shares=10)
        }
    )
    mock_sheet.fetch_grid.return_value = grid_state
    # Track the order so engine knows it should cancel it

    engine = GridEngine(mock_broker, mock_sheet, config)
    from brokers.base import OrderResult
    engine.order_manager.track(15, OrderResult(order_id="ORD-OUTSIDE", status="submitted"), "BUY")

    await engine._tick()

    # Should cancel order outside window
    mock_broker.cancel_order.assert_called_with("ORD-OUTSIDE")

@pytest.mark.asyncio
async def test_share_mismatch_warn_log_error_fails(mock_broker, mock_sheet, config):
    config.share_mismatch_mode = "warn"
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0}) # Mismatch
    # Simulate log_error raising an exception
    mock_sheet.log_error.side_effect = Exception("API Failure")

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # Bot should NOT crash, but since we added the hard pre-sell guard it will HALT because broker has 0 shares while row wants 10 shares.
    # We should assert that it halted instead of placed the order.
    assert engine._halted_reconciliation is True
