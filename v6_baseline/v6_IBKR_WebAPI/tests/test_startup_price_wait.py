import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from engine.engine import GridEngine
from config.schema import AppConfig

@pytest.fixture
def mock_broker():
    broker = AsyncMock()
    broker.connect = AsyncMock(return_value=True)
    broker.get_price = AsyncMock()
    return broker

@pytest.fixture
def mock_sheet():
    sheet = AsyncMock()
    return sheet

@pytest.fixture
def config():
    return AppConfig(
        google_sheet_id="test_sheet",
        google_credentials_json='{"test": "json"}',
        poll_interval_seconds=1,
        max_spread_pct=0.5
    )

@pytest.mark.asyncio
async def test_wait_for_initial_price_retries(mock_broker, mock_sheet, config):
    # Mock get_price to return 0 twice, then 100.0
    mock_broker.get_price.side_effect = [0.0, 0.0, 100.0]
    engine = GridEngine(mock_broker, mock_sheet, config)

    # Patch wait_for to simulate timeout for the interval sleep
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        await engine._wait_for_initial_price()

    assert mock_broker.get_price.call_count == 3
    assert engine.last_price == 100.0

@pytest.mark.asyncio
async def test_run_calls_wait_for_initial_price(mock_broker, mock_sheet, config):
    mock_broker.get_price.return_value = 100.0
    engine = GridEngine(mock_broker, mock_sheet, config)

    # Mock _wait_for_initial_price to avoid actual wait logic
    engine._wait_for_initial_price = AsyncMock()

    # Stop engine immediately in first tick
    mock_sheet.fetch_grid.side_effect = Exception("Stop engine")
    # Actually just set shutdown event
    engine._shutdown_event.set()

    await engine.run()

    engine._wait_for_initial_price.assert_called_once()
