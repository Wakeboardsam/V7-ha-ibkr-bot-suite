import socket
import time
import sys
import argparse
import os
import glob
import json
import logging

sys.path.insert(0, '/app')
try:
    from app.notifications.home_assistant import HomeAssistantNotifier, NotificationConfig
except ImportError:
    # Fallback for testing environment outside the container
    try:
        from tqqq_bot.app.notifications.home_assistant import HomeAssistantNotifier, NotificationConfig
    except ImportError:
        HomeAssistantNotifier = None
        NotificationConfig = None

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

IBC_LOGS_DIR = "/root/ibc/logs"
LOGGED_OUT_MSG = "Login dialog WINDOW_OPENED: LoginState is LOGGED_OUT"
AUTH_WAIT_THRESHOLD = 300  # 5 minutes
PRINT_STATUS_INTERVAL = 60

LOUD_WARNING = """!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
IBKR GATEWAY LOGIN MAY BE REQUIRED

Gateway API port {port} is still closed and IBC reports that
IB Gateway is logged out.

Open the primary tqqq_bot VNC interface and inspect the
Gateway login/error window. The Gateway session may have
expired and manual password entry may be required.

The Python trading bot has not started.
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"""

def get_latest_ibc_log(logs_dir=IBC_LOGS_DIR):
    try:
        list_of_files = glob.glob(f"{logs_dir}/*.txt")
        if not list_of_files:
            return None
        return max(list_of_files, key=os.path.getctime)
    except Exception:
        return None

def is_gateway_logged_out(logs_dir=IBC_LOGS_DIR):
    latest_log = get_latest_ibc_log(logs_dir)
    if not latest_log:
        return False
    try:
        with open(latest_log, 'r') as f:
            lines = f.readlines()
            # check the last 50 lines to see if LOGGED_OUT is still the recent state
            for line in reversed(lines[-50:]):
                if LOGGED_OUT_MSG in line:
                    return True
                # If we see a login success after a logged out message, it's no longer logged out.
                # But for simplicity, we just look for the logged out message.
                # (Ideally we'd track state strictly, but checking recent lines is a good proxy).
    except Exception:
        pass
    return False

def load_notification_config(options_path="/data/options.json"):
    try:
        with open(options_path, 'r') as f:
            options = json.load(f)
            notif_opts = options.get("notifications", {})
            enabled = notif_opts.get("enabled", False)
            notify_on_halts = notif_opts.get("notify_on_halts", False)
            webhook_url = notif_opts.get("webhook_url", "")
            return enabled, notify_on_halts, webhook_url
    except Exception:
        return False, False, ""

def send_auth_notification(port):
    if not HomeAssistantNotifier or not NotificationConfig:
        return False

    enabled, notify_on_halts, webhook_url = load_notification_config()

    if not enabled or not notify_on_halts or not webhook_url:
        return True # Not an error, just shouldn't send

    config = NotificationConfig(
        enabled=True,
        webhook_url=webhook_url,
        dedupe_window_seconds=300
    )
    notifier = HomeAssistantNotifier(config)

    message = (f"The primary tqqq_bot Gateway remains logged out and API port "
               f"{port} is still closed. Open the add-on VNC interface and inspect "
               f"the IB Gateway login/error window. Manual password entry may "
               f"be required.\n\nThe trading bot has not started.")

    try:
        notifier.send(
            title="IBKR Gateway login may be required",
            message=message,
            severity="critical",
            event_type="GATEWAY_AUTH_REQUIRED",
            tag="tqqq_bot_gateway_auth_required",
            group="trading_bot"
        )
    except Exception as e:
        log.warning(f"Failed to send GATEWAY_AUTH_REQUIRED notification: {e}")


def wait_for_port(port, host='localhost', timeout=300):
    start_time = time.time()
    last_print_time = 0
    logged_out_start = None
    notification_sent = False

    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"Connection to {host}:{port} succeeded.")
                return True
        except (socket.timeout, ConnectionRefusedError):
            current_time = time.time()
            elapsed = current_time - start_time

            if elapsed > timeout:
                print(f"Timeout: {host}:{port} not available after {timeout} seconds.")
                return False

            is_logged_out = is_gateway_logged_out()

            if is_logged_out:
                if logged_out_start is None:
                    logged_out_start = current_time

                logged_out_duration = current_time - logged_out_start
                if logged_out_duration >= AUTH_WAIT_THRESHOLD:
                    print(LOUD_WARNING.format(port=port))

                    if not notification_sent:
                        success = send_auth_notification(port)
                        if success:
                            notification_sent = True

                    # Reset timer so it warns again after 5 mins if still stuck
                    logged_out_start = current_time
            else:
                logged_out_start = None
                notification_sent = False

            if current_time - last_print_time >= PRINT_STATUS_INTERVAL:
                print(f"Waiting for {host}:{port}...")
                last_print_time = current_time

            time.sleep(5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Wait for IB Gateway to be ready.')
    parser.add_argument('--port', type=int, default=7497, help='Port to poll (default: 7497)')
    parser.add_argument('--timeout', type=int, default=300, help='Max timeout in seconds (default: 300)')
    args = parser.parse_args()

    if not wait_for_port(args.port, timeout=args.timeout):
        sys.exit(1)
    sys.exit(0)
