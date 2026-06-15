import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import zoneinfo

from brokers.base import OrderResult, SymbolSnapshot
from engine.grid_state import GridState, GridRow
from engine.engine import GridEngine

TICKER = "TQQQ"

@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.get_verified_symbol_snapshot = AsyncMock()
    return broker

@pytest.fixture
def mock_sheet():
    sheet = MagicMock()
    sheet.write_row_data = AsyncMock()
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
