import pytest
from unittest.mock import patch, mock_open, MagicMock
import time
import socket
import sys

# Insert app path so notifications module can be found if needed
sys.path.insert(0, '/app')

# Import our script directly since it's an executable python script
# We can import it by manipulating sys.path or using importlib, but since it's
# in the tqqq_bot directory, we can import it like a normal module.
from tqqq_bot import wait_for_gateway

@pytest.fixture
def mock_time():
    with patch('tqqq_bot.wait_for_gateway.time.time') as mock:
        yield mock

@pytest.fixture
def mock_sleep():
    with patch('tqqq_bot.wait_for_gateway.time.sleep') as mock:
        yield mock

@pytest.fixture
def mock_socket():
    with patch('tqqq_bot.wait_for_gateway.socket.create_connection') as mock:
        yield mock

@pytest.fixture
def mock_glob():
    with patch('tqqq_bot.wait_for_gateway.glob.glob') as mock:
        yield mock

@pytest.fixture
def mock_getctime():
    with patch('tqqq_bot.wait_for_gateway.os.path.getctime') as mock:
        yield mock

@pytest.fixture
def mock_open_file():
    with patch('builtins.open', mock_open()) as mock:
        yield mock

@pytest.fixture
def mock_send_notification():
    with patch('tqqq_bot.wait_for_gateway.send_auth_notification') as mock:
        yield mock

def test_wait_for_port_success(mock_time, mock_socket, mock_sleep, capsys):
    """1. The Gateway port opens normally and no login warning or notification is produced."""
    mock_socket.return_value.__enter__.return_value = MagicMock()
    mock_time.side_effect = [100.0, 100.1]

    result = wait_for_gateway.wait_for_port(7497, timeout=300)

    assert result is True
    out, _ = capsys.readouterr()
    assert "Connection to localhost:7497 succeeded." in out
    assert "IBKR GATEWAY LOGIN MAY BE REQUIRED" not in out

@patch('tqqq_bot.wait_for_gateway.is_gateway_logged_out')
def test_transient_logged_out(mock_is_logged_out, mock_time, mock_socket, mock_sleep, capsys, mock_send_notification):
    """2. A temporary "LOGGED_OUT" entry lasting less than five minutes does not trigger the warning."""
    # First it's logged out, then it's not, then connection succeeds
    mock_is_logged_out.side_effect = [True, True, False]

    # 3 iterations.
    # start: 100
    # iter 1: 105 (logged out duration 0)
    # iter 2: 200 (logged out duration 95 < 300)
    # iter 3: 250 (logged out becomes False)
    # iter 4: 260 (connection succeeds)

    mock_time.side_effect = [
        100.0, # start time
        105.0, # first check
        200.0, # second check
        250.0, # third check
        260.0, # success
    ]

    # Socket raises ConnectionRefusedError 3 times, then succeeds
    mock_socket.side_effect = [
        ConnectionRefusedError,
        ConnectionRefusedError,
        ConnectionRefusedError,
        MagicMock() # success
    ]

    result = wait_for_gateway.wait_for_port(7497, timeout=300)

    assert result is True
    out, _ = capsys.readouterr()
    assert "IBKR GATEWAY LOGIN MAY BE REQUIRED" not in out
    mock_send_notification.assert_not_called()

@patch('tqqq_bot.wait_for_gateway.is_gateway_logged_out')
def test_persistent_logged_out(mock_is_logged_out, mock_time, mock_socket, mock_sleep, capsys, mock_send_notification):
    """3. The port remains closed with "LOGGED_OUT" for five minutes: loud warning + notification."""
    mock_is_logged_out.return_value = True

    # Need to simulate exceeding 300 seconds of logged out time, but NOT exceeding the total timeout (which is default 300)
    # Actually wait_for_port takes timeout=300. But wait, if elapsed > timeout it exits!
    # The requirement: "Continue the existing port-wait behavior after displaying the warning... Preserve the existing timeout"
    # To hit the threshold (300) before timeout(300), let's set timeout to 600

    mock_time.side_effect = [
        100.0, # start
        101.0, # first check (logged_out_start = 101.0)
        401.0, # 300s later (logged_out_duration = 300, triggers warning!). elapsed = 301. Returns false right after!
    ]

    mock_socket.side_effect = [
        ConnectionRefusedError,
        ConnectionRefusedError,
    ]

    result = wait_for_gateway.wait_for_port(7497, timeout=300)

    assert result is False
    out, _ = capsys.readouterr()
    assert "IBKR GATEWAY LOGIN MAY BE REQUIRED" in out
    assert "Timeout: localhost:7497 not available after 300 seconds." in out
    mock_send_notification.assert_called_once_with(7497)

@patch('tqqq_bot.wait_for_gateway.HomeAssistantNotifier')
def test_notification_conditions(mock_notifier_class):
    """4. Notifications disabled or "notify_on_halts" false."""
    mock_notifier_instance = MagicMock()
    mock_notifier_class.return_value = mock_notifier_instance

    with patch('tqqq_bot.wait_for_gateway.load_notification_config') as mock_load:
        # enabled=False
        mock_load.return_value = (False, True, "http://localhost", 3.0, 300)
        wait_for_gateway.send_auth_notification(7497)
        mock_notifier_instance.send.assert_not_called()

        # notify_on_halts=False
        mock_load.return_value = (True, False, "http://localhost", 3.0, 300)
        wait_for_gateway.send_auth_notification(7497)
        mock_notifier_instance.send.assert_not_called()

        # no webhook url
        mock_load.return_value = (True, True, "", 3.0, 300)
        wait_for_gateway.send_auth_notification(7497)
        mock_notifier_instance.send.assert_not_called()

        # Success condition
        mock_load.return_value = (True, True, "http://localhost", 3.0, 300)
        wait_for_gateway.send_auth_notification(7497)
        mock_notifier_instance.send.assert_called_once()

@patch('tqqq_bot.wait_for_gateway.HomeAssistantNotifier')
def test_notification_delivery_fails(mock_notifier_class):
    """5. Notification delivery fails: continue safely."""
    mock_notifier_instance = MagicMock()
    # It just logs exception inside the notifier, but let's say the send method raises something unexpected
    mock_notifier_instance.send.side_effect = Exception("Network Error")
    mock_notifier_class.return_value = mock_notifier_instance

    with patch('tqqq_bot.wait_for_gateway.load_notification_config') as mock_load:
        mock_load.return_value = (True, True, "http://localhost", 3.0, 300)

        try:
            wait_for_gateway.send_auth_notification(7497)
            # if it raises, the test will fail
        except Exception:
            pytest.fail("send_auth_notification raised an exception!")

def test_wait_for_port_timeout(mock_time, mock_socket, mock_sleep, capsys):
    """6. The existing Gateway timeout behavior still returns failure."""
    mock_time.side_effect = [
        100.0, # start
        105.0, # check 1
        405.0  # check 2, elapsed = 305 > 300
    ]
    mock_socket.side_effect = [
        ConnectionRefusedError,
        ConnectionRefusedError
    ]

    result = wait_for_gateway.wait_for_port(7497, timeout=300)

    assert result is False
    out, _ = capsys.readouterr()
    assert "Timeout: localhost:7497 not available after 300 seconds." in out
