import pytest
from unittest.mock import AsyncMock
from app.engine.engine import GridEngine
from app.config.schema import AppConfig
from app.sheets.interface import GridRow, GridState

@pytest.mark.asyncio
async def test_latest_write_wins_sync():
    config = AppConfig(active_broker='ibkr', paper_trading=True, trading_mode='paper', ibkr_host='127.0.0.1', ibkr_port=7497, ibkr_account_id='TEST', ibkr_paper_account_id='TEST', ticker='TQQQ', active_bot=True, google_sheet_id='mock', google_credentials_json='{}', update_interval_seconds=5, run_in_maintenance_window=False, outside_trading_hours_cancel_window_seconds=300, notify_on_fills=True, notify_on_errors=True, notify_on_halts=True, notify_on_order_submit=False)
    mock_broker = AsyncMock()
    mock_sheet = AsyncMock()

    engine = GridEngine(mock_broker, mock_sheet, config)
    engine.grid_state = GridState(rows={10: GridRow(row_index=10, status="IDLE", has_y=False, sell_price=105.0, buy_price=100.0, shares=10)})

    async def slow_update_fail(row, status):
        raise Exception("simulated failure")

    mock_sheet.update_row_status.side_effect = slow_update_fail

    # First update
    engine._update_row_status_in_memory(10, "WORKING_BUY:111")

    # Sync fails, keeps it pending
    await engine._sync_to_sheet()

    assert 10 in engine.pending_status_updates
    assert engine.pending_status_updates[10] == "WORKING_BUY:111"

    # Newest update
    engine._update_row_status_in_memory(10, "WORKING_SELL:222")

    # Manually test the logic inside _sync_to_sheet to simulate concurrency
    updates = engine.pending_status_updates.copy()
    revisions_at_capture = {r: engine._status_revisions.get(r, 0) for r in updates}

    # Simulate a newer update coming in while writing
    engine._update_row_status_in_memory(10, "IDLE")

    for row, status in updates.items():
        try:
            await engine.sheet.update_row_status(row, status)
            if engine._status_revisions.get(row, 0) == revisions_at_capture[row]:
                engine.pending_status_updates.pop(row, None)
                engine._status_revisions.pop(row, None)
        except Exception:
            pass # Keep in pending_status_updates if it failed

    # Since IDLE is newer, it should still be in pending_status_updates and NOT WORKING_SELL
    assert 10 in engine.pending_status_updates
    assert engine.pending_status_updates[10] == "IDLE"

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

    # Track orders internally
    engine.order_manager._order_map["111"] = (10, "BUY")
    engine.order_manager._order_map["222"] = (11, "SELL")

    open_orders = [
        {'order_id': '111', 'action': 'BUY', 'ticker': 'TQQQ'},
        {'order_id': '222', 'action': 'SELL', 'ticker': 'TQQQ'}
    ]

    physical_statuses = {
        10: "IDLE", # Stale, missing BUY
        11: "WORKING_SELL:222" # Correct
    }

    engine._correct_stale_tracker_rows(open_orders, physical_statuses)

    assert 10 in engine.pending_status_updates
    assert engine.pending_status_updates[10] == "WORKING_BUY:111"

    assert 11 not in engine.pending_status_updates
