import pytest
from unittest.mock import patch, MagicMock, AsyncMock

@pytest.mark.asyncio
async def test_startup_guard_refuses_live_mode_without_account_id():
    from app.main import main
    with patch('app.main.load_config') as mock_load_config:
        mock_config = MagicMock()
        mock_config.active_broker = "ibkr"
        mock_config.dry_run = False
        mock_config.ibkr_account_id = None
        mock_load_config.return_value = mock_config

        # We need to catch the SystemExit before it propagates if mock doesn't stop it perfectly,
        # but mocking sys.exit typically just records the call. Wait, if sys.exit is called,
        # the function stops execution there. But because main catches `Exception` and not BaseException,
        # sys.exit (which is BaseException) will bubble out of main() if not caught, unless mocked.
        # Let's mock sys.exit to raise a specific custom exception so it stops execution cleanly
        # and doesn't hit the JSON decode error downstream.
        class MockExit(Exception): pass

        with patch('sys.exit', side_effect=MockExit) as mock_sys_exit:
            with pytest.raises(MockExit):
                await main()
            mock_sys_exit.assert_called_once_with(1)

@pytest.mark.asyncio
async def test_startup_guard_allows_dry_run_without_account_id():
    from app.main import main
    with patch('app.main.load_config') as mock_load_config:
        mock_config = MagicMock()
        mock_config.active_broker = "ibkr"
        mock_config.dry_run = True
        mock_config.ibkr_account_id = None
        mock_load_config.return_value = mock_config

        # Mock everything below the config load to prevent actually running the bot
        with patch('app.main.IBKRAdapter'):
            with patch('app.main.SheetInterface'):
                with patch('app.main.GridEngine') as mock_engine:
                    # We expect it to reach engine.run() successfully without sys.exit(1) due to missing account_id
                    mock_engine_instance = MagicMock()
                    mock_engine.return_value = mock_engine_instance

                    # Make run() an AsyncMock to avoid TypeError in await
                    mock_engine_instance.run = AsyncMock()

                    with patch('sys.exit') as mock_sys_exit:
                        # Also need to patch json.loads so SheetInterface init doesn't blow up on the MagicMock
                        with patch('json.loads', return_value={}):
                            await main()
                        mock_sys_exit.assert_not_called()
                        mock_engine_instance.run.assert_called_once()
