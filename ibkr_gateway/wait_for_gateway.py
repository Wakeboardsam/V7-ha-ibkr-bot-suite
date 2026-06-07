import socket
import time
import sys
import argparse

def wait_for_port(port, host='localhost', timeout=300):
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"Connection to {host}:{port} succeeded.")
                return True
        except (socket.timeout, ConnectionRefusedError):
            if time.time() - start_time > timeout:
                print(f"Timeout: {host}:{port} not available after {timeout} seconds.")
                return False
            print(f"Waiting for {host}:{port}...")
            time.sleep(5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Wait for IB Gateway to be ready.')
    parser.add_argument('--port', type=int, default=7497, help='Port to poll (default: 7497)')
    parser.add_argument('--timeout', type=int, default=300, help='Max timeout in seconds (default: 300)')
    args = parser.parse_args()

    if not wait_for_port(args.port, timeout=args.timeout):
        sys.exit(1)
    sys.exit(0)
