import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import zoneinfo

from brokers.base import OrderResult, SymbolSnapshot, PositionSnapshot
from engine.grid_state import GridState, GridRow
from engine.engine import GridEngine

TICKER = "TQQQ"

@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.get_verified_symbol_snapshot = AsyncMock()
    broker.ensure_connected = AsyncMock()
    broker.get_position_snapshot = AsyncMock()
    broker.get_open_orders = AsyncMock()
    return broker

@pytest.fixture
def mock_sheet():
    sheet = MagicMock()
    sheet.write_row_data = AsyncMock()
    sheet.fetch_grid = AsyncMock()
    return sheet

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.trading_mode = "paper"
    config.paper_trading = True
    return config

@pytest.fixture
def engine(mock_broker, mock_sheet, mock_config):
    eng = GridEngine(broker=mock_broker, sheet=mock_sheet, config=mock_config)
    eng.order_manager = MagicMock()
    eng.grid_state = GridState(rows={
        1: GridRow(row_index=1, status="OWNED:123|WORKING_SELL:abc", has_y=True, sell_price=110.0, buy_price=100.0, shares=10),
        2: GridRow(row_index=2, status="WORKING_BUY:def", has_y=True, sell_price=100.0, buy_price=90.0, shares=10)
    })
    # prevent actual background loop logic if any
    eng._sync_to_sheet = AsyncMock()
    eng._safe_async_halt = AsyncMock()
    return eng

@pytest.mark.asyncio
async def test_boundary_sell_cancel_preserves_owned(engine):
    # Mock boundary time
    with patch("engine.engine.datetime") as mock_dt:
        tz = zoneinfo.ZoneInfo("America/New_York")
        # 03:50 ET
        mock_dt.now.return_value = datetime(2023, 10, 10, 3, 50, tzinfo=tz)

        # Order Manager mock
        engine.order_manager.mark_cancelled.return_value = (1, 'SELL')

        # Broker Snapshot mock (position > 0)
        snap = SymbolSnapshot(symbol=TICKER, position_qty=10, account_id_masked='test', market_price=10.0, market_value=100.0, avg_cost=10.0, net_liquidation=100.0, cash=100.0, open_orders_count=0, working_buy_qty=0, working_sell_qty=0, active_broker_orders=[], snapshot_status='OK', snapshot_error=None)
        engine.broker.get_verified_symbol_snapshot.return_value = snap

        # Callback trigger
        res = OrderResult(order_id="abc", status="cancelled", filled_qty=0)
        engine._handle_order_update(res)

        # Allow async task to run
        await asyncio.sleep(0)

        # Assertions
        # order_manager.mark_cancelled is called inside _async_order_callback/handle_order_update
        engine.order_manager.mark_cancelled.assert_called_with("abc")
        # Status should preserve OWNED:123 but remove WORKING_SELL
        assert engine.grid_state.rows[1].status == "OWNED:123"
        # No halt should be scheduled
        engine._safe_async_halt.assert_not_called()

@pytest.mark.asyncio
async def test_boundary_buy_cancel_clears_tracking(engine):
    with patch("engine.engine.datetime") as mock_dt:
        tz = zoneinfo.ZoneInfo("America/New_York")
        # 04:00 ET
        mock_dt.now.return_value = datetime(2023, 10, 10, 4, 0, tzinfo=tz)

        engine.order_manager.mark_cancelled.return_value = (2, 'BUY')

        res = OrderResult(order_id="def", status="cancelled", filled_qty=0)
        engine._handle_order_update(res)

        engine.order_manager.mark_cancelled.assert_called_with("def")
        # Status should go back to IDLE since it was only WORKING_BUY
        assert engine.grid_state.rows[2].status == "IDLE"
        engine._safe_async_halt.assert_not_called()

@pytest.mark.asyncio
async def test_outside_boundary_sell_cancel_halts(engine):
    with patch("engine.engine.datetime") as mock_dt:
        tz = zoneinfo.ZoneInfo("America/New_York")
        # 04:15 ET (outside boundary)
        mock_dt.now.return_value = datetime(2023, 10, 10, 4, 15, tzinfo=tz)

        engine.order_manager.mark_cancelled.return_value = (1, 'SELL')

        res = OrderResult(order_id="abc", status="cancelled", filled_qty=0)
        engine._handle_order_update(res)

        # Allow async tasks to run
        await asyncio.sleep(0)

        # Halt should be scheduled
        engine._safe_async_halt.assert_called_once()
        args, kwargs = engine._safe_async_halt.call_args
        assert kwargs["code"] == "SELL_CANCELLED_NO_FILL_HALT"

@pytest.mark.asyncio
async def test_boundary_sell_cancel_ambiguous_snapshot_halts(engine):
    with patch("engine.engine.datetime") as mock_dt:
        tz = zoneinfo.ZoneInfo("America/New_York")
        # 03:50 ET
        mock_dt.now.return_value = datetime(2023, 10, 10, 3, 50, tzinfo=tz)

        engine.order_manager.mark_cancelled.return_value = (1, 'SELL')

        # Snapshot unavailable (None)
        engine.broker.get_verified_symbol_snapshot.return_value = None

        res = OrderResult(order_id="abc", status="cancelled", filled_qty=0)
        engine._handle_order_update(res)

        await asyncio.sleep(0)
        # Halt should be scheduled because snapshot couldn't be verified
        engine._safe_async_halt.assert_called_once()
        args, kwargs = engine._safe_async_halt.call_args
        assert kwargs["code"] == "SELL_CANCELLED_NO_FILL_HALT"

@pytest.mark.asyncio
async def test_boundary_sell_cancel_zero_position_halts(engine):
    with patch("engine.engine.datetime") as mock_dt:
        tz = zoneinfo.ZoneInfo("America/New_York")
        # 03:50 ET
        mock_dt.now.return_value = datetime(2023, 10, 10, 3, 50, tzinfo=tz)

        engine.order_manager.mark_cancelled.return_value = (1, 'SELL')

        # Snapshot is zero
        snap = SymbolSnapshot(symbol=TICKER, position_qty=0, account_id_masked='test', market_price=10.0, market_value=0.0, avg_cost=0.0, net_liquidation=100.0, cash=100.0, open_orders_count=0, working_buy_qty=0, working_sell_qty=0, active_broker_orders=[], snapshot_status='OK', snapshot_error=None)
        engine.broker.get_verified_symbol_snapshot.return_value = snap

        res = OrderResult(order_id="abc", status="cancelled", filled_qty=0)
        engine._handle_order_update(res)

        # Allow async tasks to run
        await asyncio.sleep(0)

        # Halt should be scheduled
        engine._safe_async_halt.assert_called_once()
        args, kwargs = engine._safe_async_halt.call_args
        assert kwargs["code"] == "SELL_CANCELLED_NO_FILL_HALT"


@pytest.mark.asyncio
async def test_boundary_sell_cancel_snapshot_raises(engine):
    with patch("engine.engine.datetime") as mock_dt:
        tz = zoneinfo.ZoneInfo("America/New_York")
        # 03:50 ET
        mock_dt.now.return_value = datetime(2023, 10, 10, 3, 50, tzinfo=tz)

        engine.order_manager.mark_cancelled.return_value = (1, 'SELL')

        # Snapshot raises
        engine.broker.get_verified_symbol_snapshot.side_effect = Exception("API Error")

        res = OrderResult(order_id="abc", status="cancelled", filled_qty=0)
        engine._handle_order_update(res)

        await asyncio.sleep(0)
        # Halt should be scheduled
        engine._safe_async_halt.assert_called_once()


@pytest.mark.asyncio
async def test_boundary_sell_cancel_snapshot_partial(engine):
    with patch("engine.engine.datetime") as mock_dt:
        tz = zoneinfo.ZoneInfo("America/New_York")
        # 03:50 ET
        mock_dt.now.return_value = datetime(2023, 10, 10, 3, 50, tzinfo=tz)

        engine.order_manager.mark_cancelled.return_value = (1, 'SELL')

        # Snapshot is PARTIAL but > 0
        snap = SymbolSnapshot(symbol=TICKER, position_qty=10, account_id_masked='test', market_price=10.0, market_value=100.0, avg_cost=10.0, net_liquidation=100.0, cash=100.0, open_orders_count=0, working_buy_qty=0, working_sell_qty=0, active_broker_orders=[], snapshot_status='PARTIAL', snapshot_error=None)
        engine.broker.get_verified_symbol_snapshot.return_value = snap

        res = OrderResult(order_id="abc", status="cancelled", filled_qty=0)
        engine._handle_order_update(res)

        await asyncio.sleep(0)
        # Halt should be scheduled
        engine._safe_async_halt.assert_called_once()

@pytest.mark.asyncio
async def test_settlement_gate_blocks_tick_while_inflight(engine):
    # Ensure grid_state exists so it doesn't return early due to missing grid_state
    if not engine.grid_state:
        engine.grid_state = GridState(rows={})

    # Set the counter to simulate an in-flight async verification
    engine._inflight_session_cancels = 1
    engine._check_reconciliation_and_halt = AsyncMock()

    # The tick should return early before reconciliation
    await engine._tick()

    engine._check_reconciliation_and_halt.assert_not_called()

@pytest.mark.asyncio
async def test_settlement_gate_consumes_one_tick_after_verification(engine, mock_broker, mock_sheet):
    if not engine.grid_state:
        engine.grid_state = GridState(rows={})
    mock_sheet.fetch_grid.return_value = engine.grid_state

    # Set inflight to 0 but require settlement
    engine._inflight_session_cancels = 0
    engine._session_cancel_settlement_required = True
    engine._check_reconciliation_and_halt = AsyncMock()

    # 1. First tick should skip and reset the flag
    await engine._tick()
    engine._check_reconciliation_and_halt.assert_not_called()
    assert engine._session_cancel_settlement_required is False

    # 2. Second tick should proceed normally
    await engine._tick()
    engine._check_reconciliation_and_halt.assert_called_once()

@pytest.mark.asyncio
async def test_boundary_sell_cancel_integration_gate_lifecycle(engine, mock_sheet):
    if not engine.grid_state:
        engine.grid_state = GridState(rows={})
    mock_sheet.fetch_grid.return_value = engine.grid_state

    with patch("engine.engine.datetime") as mock_dt:
        tz = zoneinfo.ZoneInfo("America/New_York")
        mock_dt.now.return_value = datetime(2023, 10, 10, 3, 50, tzinfo=tz)

        # Ensure order is tracked
        engine.order_manager.is_tracked = MagicMock(return_value=True)
        # Mock mark_cancelled to return dummy row and action
        engine.order_manager.mark_cancelled = MagicMock(return_value=(1, 'SELL'))

        # Simulate unexpected SELL drop via order update
        res = OrderResult(order_id="abc", status="cancelled", filled_qty=0)

        # Assert clean initial state
        assert engine._inflight_session_cancels == 0
        assert engine._session_cancel_settlement_required is False

        # Fire update
        with patch('engine.engine.asyncio.create_task') as mock_create_task:
            engine._handle_order_update(res)

            # Assert state changes BEFORE async task executes
            assert engine._inflight_session_cancels == 1
            assert engine._session_cancel_settlement_required is True

            # Extract the coroutine that was scheduled
            coro = mock_create_task.call_args[0][0]

        # Tick while inflight blocks
        engine._check_reconciliation_and_halt = AsyncMock()
        await engine._tick()
        engine._check_reconciliation_and_halt.assert_not_called()

        # Execute the coroutine to simulate async completion
        snap = SymbolSnapshot(symbol=TICKER, position_qty=10, account_id_masked='test', market_price=10.0, market_value=100.0, avg_cost=10.0, net_liquidation=100.0, cash=100.0, open_orders_count=0, working_buy_qty=0, working_sell_qty=0, active_broker_orders=[], snapshot_status='OK', snapshot_error=None)
        engine.broker.get_verified_symbol_snapshot.return_value = snap
        await coro

        # Assert counter decremented
        assert engine._inflight_session_cancels == 0
        assert engine._session_cancel_settlement_required is True

        # Tick consumes settlement
        await engine._tick()
        engine._check_reconciliation_and_halt.assert_not_called()
        assert engine._session_cancel_settlement_required is False

        # Subsequent tick resumes
        await engine._tick()
        engine._check_reconciliation_and_halt.assert_called_once()

@pytest.mark.asyncio
async def test_boundary_sell_cancel_snapshot_exception_decrements_counter(engine):
    with patch("engine.engine.datetime") as mock_dt:
        tz = zoneinfo.ZoneInfo("America/New_York")
        mock_dt.now.return_value = datetime(2023, 10, 10, 3, 50, tzinfo=tz)

        # Mock mark_cancelled
        engine.order_manager.mark_cancelled = MagicMock(return_value=(1, 'SELL'))

        # Fire update
        res = OrderResult(order_id="abc", status="cancelled", filled_qty=0)
        with patch('engine.engine.asyncio.create_task') as mock_create_task:
            engine._handle_order_update(res)
            coro = mock_create_task.call_args[0][0]

        assert engine._inflight_session_cancels == 1

        # Simulate exception in API call
        engine.broker.get_verified_symbol_snapshot.side_effect = Exception("API Error")

        await coro

        # Counter still decremented despite failure path
        assert engine._inflight_session_cancels == 0

        # Original fail-closed behavior asserts halt
        engine._safe_async_halt.assert_called_once()

@pytest.mark.asyncio
async def test_boundary_sell_cancel_unrelated_missing_sell_halts(engine, mock_broker, mock_sheet):
    if not engine.grid_state:
        engine.grid_state = GridState(rows={})

    # Unrelated missing WORKING_SELL row
    engine.grid_state.rows[8] = GridRow(row_index=8, status="WORKING_SELL:unrelated123", has_y=True, sell_price=105.0, buy_price=100.0, shares=10)
    mock_sheet.fetch_grid.return_value = engine.grid_state

    # The session boundary cancels should be empty, but we must enforce normal pre-SELL guards
    engine._inflight_session_cancels = 0
    engine._session_cancel_settlement_required = False

    # Empty open orders -> the unrelated123 order is missing
    from brokers.base import PositionSnapshot
    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 10})
    mock_broker.get_open_orders.return_value = []

    await engine._tick()

    # Halt should be triggered for missing unrelated SELL order
    assert engine._halted_reconciliation is True
    # engine._safe_async_halt is not called directly in tick for reconciliation, _halt_for_reconciliation_error is.
    # The assert _halted_reconciliation is True proves it halted.

@pytest.mark.asyncio
async def test_boundary_sell_cancel_insufficient_shares_halts(engine, mock_broker, mock_sheet):
    if not engine.grid_state:
        engine.grid_state = GridState(rows={})

    # Valid owned state row, requires 100 shares
    engine.grid_state.rows[8] = GridRow(row_index=8, status="OWNED:0", has_y=True, sell_price=105.0, buy_price=100.0, shares=100)
    mock_sheet.fetch_grid.return_value = engine.grid_state

    # Initial state requires settlement tick
    engine._inflight_session_cancels = 0
    engine._session_cancel_settlement_required = True

    mock_broker.get_position_snapshot.return_value = PositionSnapshot(is_ready=True, positions={"TQQQ": 50})
    mock_broker.get_open_orders.return_value = []

    # First tick consumes settlement tick
    await engine._tick()
    assert engine._session_cancel_settlement_required is False
    assert engine._halted_reconciliation is False

    # Second tick runs normal logic and should halt due to insufficient shares (100 required, 50 available)
    await engine._tick()
    assert engine._halted_reconciliation is True
