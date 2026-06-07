import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from config.schema import AppConfig
from engine.engine import GridEngine
from engine.grid_state import GridState, GridRow
from brokers.base import PositionSnapshot

@pytest.fixture
def config():
    return AppConfig(
        active_broker="ibkr",
        paper_trading=True,
        ibkr_host="127.0.0.1",
        ibkr_port=7497,
        ibkr_client_id=1,
        ibkr_user="user",
        ibkr_password="password",
        share_mismatch_mode="halt",
        max_spread_pct=0.5,
        google_sheet_id="test_sheet",
        google_credentials_json='{"test": "json"}',
        enable_vnc=False
    )

@pytest.fixture
def mock_broker():
    broker = AsyncMock()
    broker.get_open_orders.return_value = []
    return broker

@pytest.fixture
def mock_sheet():
    return AsyncMock()

@pytest.mark.asyncio
async def test_reconcile_exact_missed_buy(mock_broker, mock_sheet, config):
    # Sheet has 152 shares (sum of has_y=True). Broker has 237 shares. Delta = +85.
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 237})

    rows = {
        # Active owned rows giving 152 shares
        # GridRow signature: row_index, status, has_y, sell_price, buy_price, shares
        1: GridRow(1, "OWNED:999", True, 11.0, 10.0, 100),
        2: GridRow(2, "OWNED:998", True, 10.0, 9.0, 52),
        # Working buy candidates: row 3 (44) + row 4 (41) = 85
        3: GridRow(3, "WORKING_BUY:12345", False, 9.0, 8.0, 44),
        4: GridRow(4, "WORKING_BUY:12346", False, 8.0, 7.0, 41),
        5: GridRow(5, "WORKING_BUY:12347", False, 7.0, 6.0, 50),
    }
    mock_sheet.fetch_grid.return_value = GridState(rows)
    mock_broker.get_open_orders.return_value = [] # No open orders

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # Should reconcile rows 3 and 4
    # Check that sheet sync was called (pending_status_updates will be cleared because _sync_to_sheet is awaited)
    mock_sheet.update_row_status.assert_any_call(3, "OWNED:12345")
    mock_sheet.update_row_status.assert_any_call(4, "OWNED:12346")

    # Check that early return prevented error log and halt message (no CIRCUIT BREAKER log)
    # The message sent to log_error should start with RECONCILIATION SUCCESSFUL
    error_calls = [call[0][0] for call in mock_sheet.log_error.call_args_list]
    assert any("RECONCILIATION SUCCESSFUL" in call for call in error_calls)

@pytest.mark.asyncio
async def test_reconcile_exact_missed_sell(mock_broker, mock_sheet, config):
    # Sheet has 200 shares. Broker has 100 shares. Delta = -100.
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 100})

    rows = {
        1: GridRow(1, "OWNED:999", True, 11.0, 10.0, 100),
        2: GridRow(2, "WORKING_SELL:5555", True, 10.0, 9.0, 60),
        3: GridRow(3, "WORKING_SELL:6666", True, 9.0, 8.0, 40),
    }
    mock_sheet.fetch_grid.return_value = GridState(rows)
    mock_broker.get_open_orders.return_value = [] # No open orders

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # Should reconcile rows 2 and 3
    mock_sheet.update_row_status.assert_any_call(2, "IDLE")
    mock_sheet.update_row_status.assert_any_call(3, "IDLE")

@pytest.mark.asyncio
async def test_reconciliation_fails_no_match(mock_broker, mock_sheet, config):
    # Sheet 100 shares. Broker 150 shares. Delta = +50.
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 150})

    rows = {
        1: GridRow(1, "OWNED:999", True, 11.0, 10.0, 100),
        # Candidates sum to 60, no match for 50
        2: GridRow(2, "WORKING_BUY:111", False, 10.0, 9.0, 40),
        3: GridRow(3, "WORKING_BUY:222", False, 9.0, 8.0, 20),
    }
    mock_sheet.fetch_grid.return_value = GridState(rows)
    mock_broker.get_open_orders.return_value = []

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # Should hit circuit breaker and halt
    error_calls = [call[0][0] for call in mock_sheet.log_error.call_args_list]
    assert any("CIRCUIT BREAKER" in call for call in error_calls)
    assert not engine.pending_status_updates

@pytest.mark.asyncio
async def test_reconciliation_fails_multiple_matches(mock_broker, mock_sheet, config):
    # Delta = +85
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 85})

    rows = {
        # Two possible combinations: [2, 3] and [4]
        2: GridRow(2, "WORKING_BUY:111", False, 10.0, 9.0, 44),
        3: GridRow(3, "WORKING_BUY:222", False, 9.0, 8.0, 41),
        4: GridRow(4, "WORKING_BUY:333", False, 8.0, 7.0, 85),
    }
    mock_sheet.fetch_grid.return_value = GridState(rows)
    mock_broker.get_open_orders.return_value = []

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # Should hit circuit breaker and halt
    error_calls = [call[0][0] for call in mock_sheet.log_error.call_args_list]
    assert any("CIRCUIT BREAKER" in call for call in error_calls)
    assert not engine.pending_status_updates

@pytest.mark.asyncio
async def test_reconciliation_fails_active_broker_order(mock_broker, mock_sheet, config):
    # Delta = +85
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 85})

    rows = {
        2: GridRow(2, "WORKING_BUY:111", False, 10.0, 9.0, 44),
        3: GridRow(3, "WORKING_BUY:222", False, 9.0, 8.0, 41),
    }
    mock_sheet.fetch_grid.return_value = GridState(rows)
    # Order 111 is still pending at the broker
    mock_broker.get_open_orders.return_value = [{'order_id': '111', 'qty': 44}]

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # Should hit circuit breaker and halt due to unsafe condition
    error_calls = [call[0][0] for call in mock_sheet.log_error.call_args_list]
    assert any("CIRCUIT BREAKER" in call for call in error_calls)
    assert not engine.pending_status_updates

@pytest.mark.asyncio
async def test_reconciliation_delta_zero(mock_broker, mock_sheet, config):
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 100})
    rows = {
        1: GridRow(1, "OWNED:999", True, 11.0, 10.0, 100),
        2: GridRow(2, "IDLE", False, 10.0, 9.0, 50),
    }
    mock_sheet.fetch_grid.return_value = GridState(rows)
    mock_broker.get_open_orders.return_value = []

    engine = GridEngine(mock_broker, mock_sheet, config)
    await engine._tick()

    # Normal behavior (no mismatch)
    error_calls = [call[0][0] for call in mock_sheet.log_error.call_args_list]
    assert not any("CIRCUIT BREAKER" in call for call in error_calls)
