import pytest
import time
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from app.notifications.home_assistant import NotificationConfig, HomeAssistantNotifier
from app.engine.engine import GridEngine
from app.config.schema import AppConfig
from app.brokers.base import BrokerBase, OrderResult

@patch('app.notifications.home_assistant.urlopen')
def test_dedupe(mock_urlopen):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_urlopen.return_value.__enter__.return_value = mock_response

    config = NotificationConfig(enabled=True, webhook_url="http://test", dedupe_window_seconds=10)
    notifier = HomeAssistantNotifier(config)

    # First send
    notifier.send(title="T1", message="M1", event_type="E1", tag="TAG1")
    assert mock_urlopen.call_count == 1

    # Second send inside dedupe window
    notifier.send(title="T1", message="M1", event_type="E1", tag="TAG1")
    assert mock_urlopen.call_count == 1 # still 1

    # Send a different message
    notifier.send(title="T2", message="M2", event_type="E1", tag="TAG1")
    assert mock_urlopen.call_count == 2

@patch('app.notifications.home_assistant.urlopen')
def test_failure_does_not_raise(mock_urlopen):
    # Setup mock to raise URLError
    from urllib.error import URLError
    mock_urlopen.side_effect = URLError("Network unreach")

    config = NotificationConfig(enabled=True, webhook_url="http://test")
    notifier = HomeAssistantNotifier(config)

    # Should not raise
    notifier.send(title="T1", message="M1")

@patch('app.notifications.home_assistant.urlopen')
def test_disabled_does_not_call_webhook(mock_urlopen):
    config = NotificationConfig(enabled=False, webhook_url="http://test")
    notifier = HomeAssistantNotifier(config)
    notifier.send(title="T1", message="M1")
    assert mock_urlopen.call_count == 0

@pytest.mark.asyncio
async def test_engine_respects_notify_on_fills():
    # Setup mock config and objects
    config = AppConfig(google_sheet_id="test", google_credentials_json="test")
    config.notifications.enabled = True
    config.notifications.notify_on_fills = False

    broker = MagicMock(spec=BrokerBase)
    sheet = MagicMock()
    notifier = MagicMock(spec=HomeAssistantNotifier)

    engine = GridEngine(broker=broker, sheet=sheet, config=config, notifier=notifier)

    # Mock order manager to simulate an order
    engine.order_manager.mark_filled = MagicMock(return_value=(1, "BUY"))

    # Mock the internal coroutine that gets scheduled to avoid unawaited coroutine warning
    engine._sync_to_sheet = MagicMock(return_value=asyncio.Future())
    engine._sync_to_sheet.return_value.set_result(None)

    result = OrderResult(order_id="TEST_OID", status="filled", filled_qty=10, filled_price=5.0)

    with patch('app.engine.engine.asyncio.create_task') as mock_create_task:
        engine._handle_order_update(result)

    # Notifier send should not be called because notify_on_fills is False
    notifier.send.assert_not_called()

@pytest.mark.asyncio
async def test_engine_sends_notification_on_fill():
    # Setup mock config and objects
    config = AppConfig(google_sheet_id="test", google_credentials_json="test")
    config.notifications.enabled = True
    config.notifications.notify_on_fills = True

    broker = MagicMock(spec=BrokerBase)
    sheet = MagicMock()
    notifier = MagicMock(spec=HomeAssistantNotifier)

    engine = GridEngine(broker=broker, sheet=sheet, config=config, notifier=notifier)

    # Mock order manager to simulate an order
    engine.order_manager.mark_filled = MagicMock(return_value=(1, "BUY"))

    # Mock the internal coroutine that gets scheduled to avoid unawaited coroutine warning
    engine._sync_to_sheet = MagicMock(return_value=asyncio.Future())
    engine._sync_to_sheet.return_value.set_result(None)

    result = OrderResult(order_id="TEST_OID", status="filled", filled_qty=10, filled_price=5.0)

    with patch('app.engine.engine.asyncio.create_task') as mock_create_task, \
         patch('app.engine.engine.asyncio.to_thread') as mock_to_thread:
        engine._handle_order_update(result)

    # Check that to_thread was called to run notifier.send
    assert mock_to_thread.call_count == 1

    # Check arguments
    args, kwargs = mock_to_thread.call_args
    assert args[0] == notifier.send
    assert kwargs['tag'] == 'tqqq_fill_TEST_OID'
    assert kwargs['event_type'] == 'FILL_BUY'

    # Ensure second call with same order_id deduplicates locally in engine
    with patch('app.engine.engine.asyncio.create_task') as mock_create_task, \
         patch('app.engine.engine.asyncio.to_thread') as mock_to_thread:
        engine._handle_order_update(result)
    assert mock_to_thread.call_count == 0 # Deduplicated

@pytest.mark.asyncio
async def test_startup_ok_notification_sent_on_successful_reconciliation():
    config = AppConfig(google_sheet_id="test", google_credentials_json="test")
    config.notifications.enabled = True
    config.notifications.notify_on_startup_ok = True

    broker = MagicMock(spec=BrokerBase)
    snapshot = MagicMock()
    snapshot.is_ready = True
    snapshot.positions = {"TQQQ": 0}
    broker.get_position_snapshot = AsyncMock(return_value=snapshot)
    broker.get_open_orders = AsyncMock(return_value=[])
    broker.ensure_connected = AsyncMock()
    broker.get_wallet_balance = AsyncMock(return_value=1000.0)
    broker.get_price = AsyncMock(return_value=100.0)

    sheet = MagicMock()
    grid_state = MagicMock()
    grid_state.rows = {}
    grid_state.distal_y_row = 7
    sheet.fetch_grid = AsyncMock(return_value=grid_state)
    sheet.write_cash_value = AsyncMock()

    notifier = MagicMock(spec=HomeAssistantNotifier)

    engine = GridEngine(broker=broker, sheet=sheet, config=config, notifier=notifier)
    engine._sync_to_sheet = AsyncMock()

    with patch('app.engine.engine.asyncio.create_task') as mock_create_task, \
         patch('app.engine.engine.asyncio.to_thread') as mock_to_thread:
        await engine._tick()

    assert engine._startup_ok_notification_sent is True
    assert mock_to_thread.call_count == 1
    args, kwargs = mock_to_thread.call_args
    assert args[0] == notifier.send
    assert kwargs['title'] == "TQQQ Bot Started"
    assert kwargs['message'] == "Startup reconciliation passed. Bot is monitoring."
    assert kwargs['severity'] == "info"
    assert kwargs['event_type'] == "BOT_STARTED"
    assert kwargs['tag'] == "tqqq_bot_startup"
    assert kwargs['group'] == "trading_bot_status"
    assert kwargs['extra'] == {
        "symbol": "TQQQ",
        "broker_shares": 0,
        "open_orders_count": 0,
        "dry_run": config.dry_run,
        "paper_trading": config.paper_trading,
    }

    # Second tick should not send startup OK again
    with patch('app.engine.engine.asyncio.create_task') as mock_create_task, \
         patch('app.engine.engine.asyncio.to_thread') as mock_to_thread:
        await engine._tick()

    assert mock_to_thread.call_count == 0


@pytest.mark.asyncio
async def test_startup_ok_notification_not_sent_when_halted():
    config = AppConfig(google_sheet_id="test", google_credentials_json="test")
    config.notifications.enabled = True
    config.notifications.notify_on_startup_ok = True

    broker = MagicMock(spec=BrokerBase)
    snapshot = MagicMock()
    snapshot.is_ready = True
    snapshot.positions = {"TQQQ": 0}
    broker.get_position_snapshot = AsyncMock(return_value=snapshot)
    broker.get_open_orders = AsyncMock(return_value=[])
    broker.ensure_connected = AsyncMock()

    sheet = MagicMock()
    grid_state = MagicMock()
    grid_state.rows = {}
    sheet.fetch_grid = AsyncMock(return_value=grid_state)

    notifier = MagicMock(spec=HomeAssistantNotifier)

    engine = GridEngine(broker=broker, sheet=sheet, config=config, notifier=notifier)
    engine._sync_to_sheet = AsyncMock()
    engine._check_reconciliation_and_halt = AsyncMock(return_value=False)
    engine._halted_reconciliation = True

    with patch('app.engine.engine.asyncio.to_thread') as mock_to_thread:
        await engine._tick()

    assert engine._startup_ok_notification_sent is False
    assert mock_to_thread.call_count == 0


@pytest.mark.asyncio
async def test_startup_ok_notification_not_sent_when_reconciliation_changed():
    config = AppConfig(google_sheet_id="test", google_credentials_json="test")
    config.notifications.enabled = True
    config.notifications.notify_on_startup_ok = True

    broker = MagicMock(spec=BrokerBase)
    snapshot = MagicMock()
    snapshot.is_ready = True
    snapshot.positions = {"TQQQ": 0}
    broker.get_position_snapshot = AsyncMock(return_value=snapshot)
    broker.get_open_orders = AsyncMock(return_value=[])
    broker.ensure_connected = AsyncMock()

    sheet = MagicMock()
    grid_state = MagicMock()
    grid_state.rows = {}
    sheet.fetch_grid = AsyncMock(return_value=grid_state)

    notifier = MagicMock(spec=HomeAssistantNotifier)

    engine = GridEngine(broker=broker, sheet=sheet, config=config, notifier=notifier)
    engine._sync_to_sheet = AsyncMock()
    engine._check_reconciliation_and_halt = AsyncMock(return_value=True)

    with patch('app.engine.engine.asyncio.to_thread') as mock_to_thread:
        await engine._tick()

    assert engine._startup_ok_notification_sent is False
    assert mock_to_thread.call_count == 0


@pytest.mark.asyncio
async def test_startup_ok_notification_not_sent_when_disabled():
    config = AppConfig(google_sheet_id="test", google_credentials_json="test")
    config.notifications.enabled = False
    config.notifications.notify_on_startup_ok = True

    broker = MagicMock(spec=BrokerBase)
    snapshot = MagicMock()
    snapshot.is_ready = True
    snapshot.positions = {"TQQQ": 0}
    broker.get_position_snapshot = AsyncMock(return_value=snapshot)
    broker.get_open_orders = AsyncMock(return_value=[])
    broker.ensure_connected = AsyncMock()
    broker.get_wallet_balance = AsyncMock(return_value=1000.0)
    broker.get_price = AsyncMock(return_value=100.0)

    sheet = MagicMock()
    grid_state = MagicMock()
    grid_state.rows = {}
    grid_state.distal_y_row = 7
    sheet.fetch_grid = AsyncMock(return_value=grid_state)
    sheet.write_cash_value = AsyncMock()

    notifier = MagicMock(spec=HomeAssistantNotifier)

    engine = GridEngine(broker=broker, sheet=sheet, config=config, notifier=notifier)
    engine._sync_to_sheet = AsyncMock()

    with patch('app.engine.engine.asyncio.to_thread') as mock_to_thread:
        await engine._tick()

    assert engine._startup_ok_notification_sent is False
    assert mock_to_thread.call_count == 0


@pytest.mark.asyncio
async def test_startup_ok_notification_not_sent_when_notify_option_false():
    config = AppConfig(google_sheet_id="test", google_credentials_json="test")
    config.notifications.enabled = True
    config.notifications.notify_on_startup_ok = False

    broker = MagicMock(spec=BrokerBase)
    snapshot = MagicMock()
    snapshot.is_ready = True
    snapshot.positions = {"TQQQ": 0}
    broker.get_position_snapshot = AsyncMock(return_value=snapshot)
    broker.get_open_orders = AsyncMock(return_value=[])
    broker.ensure_connected = AsyncMock()
    broker.get_wallet_balance = AsyncMock(return_value=1000.0)
    broker.get_price = AsyncMock(return_value=100.0)

    sheet = MagicMock()
    grid_state = MagicMock()
    grid_state.rows = {}
    grid_state.distal_y_row = 7
    sheet.fetch_grid = AsyncMock(return_value=grid_state)
    sheet.write_cash_value = AsyncMock()

    notifier = MagicMock(spec=HomeAssistantNotifier)

    engine = GridEngine(broker=broker, sheet=sheet, config=config, notifier=notifier)
    engine._sync_to_sheet = AsyncMock()

    with patch('app.engine.engine.asyncio.to_thread') as mock_to_thread:
        await engine._tick()

    assert engine._startup_ok_notification_sent is False
    assert mock_to_thread.call_count == 0
