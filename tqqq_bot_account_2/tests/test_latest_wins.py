import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from app.engine.engine import GridEngine
from app.config.schema import AppConfig
from app.sheets.interface import GridRow, GridState
from brokers.base import PositionSnapshot

@pytest.mark.asyncio
async def test_latest_write_wins_sync():
    config = AppConfig(active_broker='ibkr', paper_trading=True, trading_mode='paper', ibkr_host='127.0.0.1', ibkr_port=7497, ibkr_account_id='TEST', ibkr_paper_account_id='TEST', ticker='TQQQ', active_bot=True, google_sheet_id='mock', google_credentials_json='{}', update_interval_seconds=5, run_in_maintenance_window=False, outside_trading_hours_cancel_window_seconds=300, notify_on_fills=True, notify_on_errors=True, notify_on_halts=True, notify_on_order_submit=False)
    mock_broker = AsyncMock()
    mock_sheet = AsyncMock()

    engine = GridEngine(mock_broker, mock_sheet, config)
    engine.grid_state = GridState(rows={10: GridRow(row_index=10, status="IDLE", has_y=False, sell_price=105.0, buy_price=100.0, shares=10)})

    pause_event = asyncio.Event()

    async def slow_update_row_status(row, status):
        if status == "WORKING_BUY:111":
            await pause_event.wait()
            raise Exception("simulated failure")

    mock_sheet.update_row_status.side_effect = slow_update_row_status

    engine._update_row_status_in_memory(10, "WORKING_BUY:111")

    task = asyncio.create_task(engine._sync_to_sheet())
    await asyncio.sleep(0.01)

    engine._update_row_status_in_memory(10, "IDLE")

    pause_event.set()
    await task

    await engine._sync_to_sheet()

    assert len(engine.pending_status_updates) == 0
    mock_sheet.update_row_status.assert_called_with(10, "IDLE")


@pytest.mark.asyncio
async def test_reconciliation_generic_stale_row():
    config = AppConfig(active_broker='ibkr', paper_trading=True, trading_mode='paper', ibkr_host='127.0.0.1', ibkr_port=7497, ibkr_account_id='TEST', ibkr_paper_account_id='TEST', ticker='TQQQ', active_bot=True, google_sheet_id='mock', google_credentials_json='{}', update_interval_seconds=5, run_in_maintenance_window=False, outside_trading_hours_cancel_window_seconds=300, notify_on_fills=True, notify_on_errors=True, notify_on_halts=True, notify_on_order_submit=False)
    mock_broker = AsyncMock()
    mock_sheet = AsyncMock()

    engine = GridEngine(mock_broker, mock_sheet, config)
    engine.grid_state = GridState(rows={
        10: GridRow(row_index=10, status="IDLE", has_y=False, sell_price=105.0, buy_price=100.0, shares=10),
        11: GridRow(row_index=11, status="OWNED:555", has_y=True, sell_price=105.0, buy_price=100.0, shares=10)
    })

    # We must patch the order manager internally properly to be "tracked"
    engine.order_manager._order_map["111"] = (10, "BUY")
    engine.order_manager._order_map["222"] = (11, "SELL")

    mock_broker.get_open_orders.return_value = [
        {'order_id': '111', 'action': 'BUY', 'ticker': 'TQQQ', 'status': 'PreSubmitted'},
        {'order_id': '222', 'action': 'SELL', 'ticker': 'TQQQ', 'status': 'PreSubmitted'}
    ]

    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})
    mock_broker.get_wallet_balance.return_value = 100000.0
    mock_broker.get_bid_ask.return_value = (100.0, 101.0)

    mock_sheet.fetch_grid.return_value = engine.grid_state

    with patch.object(engine, '_check_reconciliation_and_halt', new_callable=AsyncMock, return_value=False):
        # We manually process the subset of what tick does up to _sync_to_sheet to bypass executing full grid mechanics that error out without other setup mocks
        open_orders = mock_broker.get_open_orders.return_value
        physical_statuses = {
            10: "IDLE", # Stale, missing BUY
            11: "WORKING_SELL:222" # Correct
        }
        has_corrections = engine._correct_stale_tracker_rows(open_orders, physical_statuses)
        if has_corrections:
            await engine._sync_to_sheet()


    mock_sheet.update_row_status.assert_called_with(10, "WORKING_BUY:111")

    mock_broker.place_limit_order.assert_not_called()
