import pytest
from unittest.mock import patch, MagicMock
import asyncio

@pytest.mark.asyncio
async def test_main_forces_local_host(caplog):
    import logging
    from config.schema import AppConfig
    import main as main_module

    # Create a config with a non-local host
    mock_config = AppConfig(
        active_broker="ibkr",
        ibkr_host="192.168.1.100", # Non-local
        ibkr_port=7497,
        ibkr_client_id=1,
        ibkr_account_id="DU123",
        google_sheet_id="abc",
        google_credentials_json="{}",
        paper_trading=True
    )

    with patch("main.load_config", return_value=mock_config), \
         patch("main.validate_ibkr_settings", return_value=[]), \
         patch("main.IBKRAdapter") as mock_ibkr_adapter, \
         patch("main.SheetInterface") as mock_sheet, \
         patch("main.GridEngine") as mock_engine:

        # Make the engine run return immediately
        mock_engine_instance = mock_engine.return_value
        async def dummy_run(): pass
        mock_engine_instance.run = dummy_run

        with caplog.at_level(logging.WARNING):
            await main_module.main()

        # Verify warning was logged
        assert any("Bundled tqqq_bot only supports local Gateway access" in record.message for record in caplog.records)

        # Verify the config was mutated to 127.0.0.1
        assert mock_config.ibkr_host == "127.0.0.1"

        # Verify the adapter was instantiated with the local host
        mock_ibkr_adapter.assert_called_once()
        _, kwargs = mock_ibkr_adapter.call_args
        assert kwargs["host"] == "127.0.0.1"
