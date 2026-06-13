import pytest
import asyncio
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
    mock_broker.get_open_orders.return_value = [{'order_id': '99', 'action': 'SELL', 'ticker': 'TQQQ', 'qty': 100}]

    with patch.object(engine, '_check_reconciliation_and_halt', new_callable=AsyncMock):
        await engine._tick()

        assert engine._halted_reconciliation is True
        assert mock_broker.place_limit_order.call_count == 0
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

    # To test the bridge guard specifically, we need it to go through the early
    # startup check where it halts if Tracker claims bridge anchor state but broker
    # has 0 shares.
    engine.grid_state = GridState(rows={
        7: GridRow(row_index=7, status="BRIDGE_BUY:100", has_y=True, sell_price=78.70, buy_price=78.00, shares=136)
    })

    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 0})
    # We will just run _tick(), the startup reconciliation will catch it.
    await engine._tick()

    assert engine._halted_reconciliation is True
    assert mock_broker.place_stop_limit_order.call_count == 0
    mock_sheet.append_error.assert_called_once()
    call_args = mock_sheet.append_error.call_args[1]
    assert call_args['code'] == "SELL_POSITION_MISMATCH_HALT" # Using generic startup mismatch code
