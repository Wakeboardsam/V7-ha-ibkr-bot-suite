import pytest
from unittest.mock import AsyncMock, patch
from datetime import time

from engine.engine import GridEngine
from config.schema import AppConfig

@pytest.fixture
def mock_broker():
    broker = AsyncMock()
    broker.connect = AsyncMock(return_value=True)
    broker.disconnect = AsyncMock()
    broker.ensure_connected = AsyncMock()
    return broker

@pytest.fixture
def mock_sheet():
    sheet = AsyncMock()
    return sheet

@pytest.fixture
def config():
    return AppConfig(
        google_sheet_id="id",
        google_credentials_json="{}"
    )

def test_maintenance_window_normal(mock_broker, mock_sheet, config):
    config.maintenance_enabled = True
    config.maintenance_start_local = "10:00"
    config.maintenance_end_local = "10:30"
    engine = GridEngine(mock_broker, mock_sheet, config)

    # Before
    with patch('engine.engine.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(9, 59)
        assert engine._is_in_maintenance_window() == False

    # During
    with patch('engine.engine.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(10, 15)
        assert engine._is_in_maintenance_window() == True

    # After
    with patch('engine.engine.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(10, 30)
        assert engine._is_in_maintenance_window() == False

def test_maintenance_window_crossing_midnight(mock_broker, mock_sheet, config):
    config.maintenance_enabled = True
    config.maintenance_start_local = "23:44"
    config.maintenance_end_local = "00:00"
    engine = GridEngine(mock_broker, mock_sheet, config)

    # Before
    with patch('engine.engine.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(23, 43)
        assert engine._is_in_maintenance_window() == False

    # During (before midnight)
    with patch('engine.engine.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(23, 45)
        assert engine._is_in_maintenance_window() == True

    # During (after midnight, though this exact window ends exactly at 00:00 so 00:00 is outside)
    with patch('engine.engine.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(0, 0)
        assert engine._is_in_maintenance_window() == False

def test_maintenance_window_disabled(mock_broker, mock_sheet, config):
    config.maintenance_enabled = False
    config.maintenance_start_local = "10:00"
    config.maintenance_end_local = "10:30"
    engine = GridEngine(mock_broker, mock_sheet, config)

    with patch('engine.engine.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(10, 15)
        assert engine._is_in_maintenance_window() == False

@pytest.mark.asyncio
async def test_tick_halts_during_maintenance(mock_broker, mock_sheet, config):
    config.maintenance_enabled = True
    config.maintenance_start_local = "23:44"
    config.maintenance_end_local = "00:00"
    config.maintenance_cancel_open_orders = True

    engine = GridEngine(mock_broker, mock_sheet, config)
    engine._cancel_all_orders = AsyncMock()
    engine._check_daily_grid_regeneration = AsyncMock()

    with patch('engine.engine.datetime') as mock_dt:
        # Tick 1: inside maintenance window
        mock_dt.now.return_value.time.return_value = time(23, 45)
        await engine._tick()

        # Verify canceled open orders
        engine._cancel_all_orders.assert_awaited_once()
        assert engine._maintenance_cancel_done == True
        # Verify early exit (daily check not called)
        engine._check_daily_grid_regeneration.assert_not_awaited()

        # Tick 2: still inside maintenance window
        engine._cancel_all_orders.reset_mock()
        await engine._tick()

        # Verify NOT canceled again
        engine._cancel_all_orders.assert_not_awaited()
        assert engine._maintenance_cancel_done == True
        # Verify early exit still
        engine._check_daily_grid_regeneration.assert_not_awaited()

        # Tick 3: outside maintenance window
        # We need to mock some extra things because normal execution proceeds
        from engine.grid_state import GridState
        mock_sheet.fetch_grid = AsyncMock(return_value=GridState(rows={}))
        engine.broker.get_wallet_balance = AsyncMock(return_value=1000)
        engine.broker.get_price = AsyncMock(return_value=100)

        from brokers.base import PositionSnapshot
        engine.broker.get_position_snapshot = AsyncMock(return_value=PositionSnapshot(is_ready=False, positions={}))

        mock_dt.now.return_value.time.return_value = time(0, 1)
        await engine._tick()

        # Verify status reset and normal execution continued
        assert engine._maintenance_cancel_done == False
