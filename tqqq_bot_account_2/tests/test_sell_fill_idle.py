from unittest.mock import AsyncMock, patch
from engine.engine import GridEngine
from brokers.base import OrderResult
from config.schema import AppConfig
from engine.grid_state import GridState, GridRow
import asyncio
import pytest

@pytest.mark.asyncio
async def test_normal_sell_fill():
    mock_broker = AsyncMock()
    mock_sheet = AsyncMock()
    config = AppConfig(enable_bridge_anchor=True, google_sheet_id="t", google_credentials_json="{}")
    engine = GridEngine(mock_broker, mock_sheet, config)

    engine.grid_state = GridState(rows={7: GridRow(row_index=7, status="WORKING_SELL:294", has_y=True, sell_price=105, buy_price=100, shares=50)})
    engine.order_manager.track(7, OrderResult(order_id="294", status="submitted"), "SELL")

    engine._bridge_state = None

    engine._handle_order_update(OrderResult(order_id="294", status="filled"))

    assert engine.grid_state.rows[7].status == "IDLE"
