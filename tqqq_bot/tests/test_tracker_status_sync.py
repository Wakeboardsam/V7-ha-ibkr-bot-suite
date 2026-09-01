import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from app.engine.engine import GridEngine
from app.config.schema import AppConfig
from app.sheets.interface import GridRow, GridState
from app.engine.order_manager import OrderResult
from brokers.base import PositionSnapshot

@pytest.mark.asyncio
@pytest.mark.parametrize("old_status,new_status", [
    ("WORKING_BUY:111", "OWNED:111"),
    ("WORKING_SELL:222", "IDLE"),
])
async def test_latest_write_wins_race(old_status, new_status):
    config = AppConfig(active_broker='ibkr', paper_trading=True, trading_mode='paper', ibkr_host='127.0.0.1', ibkr_port=7497, ibkr_account_id='TEST', ibkr_paper_account_id='TEST', ticker='TQQQ', active_bot=True, google_sheet_id='mock', google_credentials_json='{}', update_interval_seconds=5, run_in_maintenance_window=False, outside_trading_hours_cancel_window_seconds=300, notify_on_fills=True, notify_on_errors=True, notify_on_halts=True, notify_on_order_submit=False)
    mock_broker = AsyncMock()
    mock_sheet = AsyncMock()
    engine = GridEngine(mock_broker, mock_sheet, config)

    first_write_started = asyncio.Event()
    release_first_write = asyncio.Event()
    recorded_writes = []

    async def mock_update_row_status(row_index, status):
        recorded_writes.append(status)
        first_write_started.set()
        await release_first_write.wait()

    mock_sheet.update_row_status.side_effect = mock_update_row_status

    row_index = 42
    engine.grid_state = GridState(rows={row_index: GridRow(row_index=row_index, status="IDLE", has_y=False, sell_price=105.0, buy_price=100.0, shares=10)})

    engine._update_row_status_in_memory(row_index, old_status)
    sync_task = asyncio.create_task(engine._sync_to_sheet())

    await asyncio.wait_for(first_write_started.wait(), timeout=1.0)

    engine._update_row_status_in_memory(row_index, new_status)
    release_first_write.set()

    await asyncio.wait_for(sync_task, timeout=1.0)

    assert recorded_writes == [old_status, new_status]
    assert len(engine.pending_status_updates) == 0
    assert len(engine._status_revisions) == 0

@pytest.mark.asyncio
@pytest.mark.parametrize("action, stale_status", [
    ("BUY", "IDLE"),
    ("SELL", "OWNED:0"),
])
async def test_repair_path_no_duplicate_placement(action, stale_status):
    config = AppConfig(active_broker='ibkr', paper_trading=True, trading_mode='paper', ibkr_host='127.0.0.1', ibkr_port=7497, ibkr_account_id='TEST', ibkr_paper_account_id='TEST', ticker='TQQQ', active_bot=True, google_sheet_id='mock', google_credentials_json='{}', update_interval_seconds=5, run_in_maintenance_window=False, outside_trading_hours_cancel_window_seconds=300, notify_on_fills=True, notify_on_errors=True, notify_on_halts=True, notify_on_order_submit=False)
    mock_broker = AsyncMock()
    mock_sheet = AsyncMock()
    engine = GridEngine(mock_broker, mock_sheet, config)
    engine._is_in_maintenance_window = lambda: False

    row_index = 42
    order_id = "999"
    engine.order_manager.track(row_index, OrderResult(order_id=order_id, status="submitted"), action)

    mock_broker.ensure_connected = AsyncMock()
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})
    mock_broker.get_open_orders.return_value = [
        {'order_id': order_id, 'action': action, 'ticker': 'TQQQ'}
    ]

    engine.grid_state = GridState(rows={row_index: GridRow(row_index=row_index, status=stale_status, has_y=False, sell_price=105.0, buy_price=100.0, shares=10)})
    mock_sheet.fetch_grid.return_value = engine.grid_state
    mock_sheet.update_row_status = AsyncMock()

    async def assert_no_reconcile(*args, **kwargs):
        raise AssertionError("Reconciliation should not have been called")

    with patch.object(engine, '_check_reconciliation_and_halt', new_callable=AsyncMock, side_effect=assert_no_reconcile) as mock_reconcile:
        await engine._tick()

    expected_status = f"WORKING_{action}:{order_id}"
    mock_sheet.update_row_status.assert_called_with(row_index, expected_status)
    assert len(engine.pending_status_updates) == 0
    assert len(engine._status_revisions) == 0
    mock_broker.place_limit_order.assert_not_called()
    mock_reconcile.assert_not_called()
