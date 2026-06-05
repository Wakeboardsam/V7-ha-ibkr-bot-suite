#!/bin/bash
set -e

echo "ibkr_gateway scaffold installed; v6 runtime port pending."
echo "Parsing Home Assistant options..."

# Options available but safe boot validation does not use the secrets.
if [ -f /data/options.json ]; then
    TRADING_MODE=$(jq -r '.trading_mode // "paper"' /data/options.json)
    API_PORT=$(jq -r '.api_port // 7497' /data/options.json)
    ENABLE_VNC=$(jq -r '.enable_vnc // false' /data/options.json)

    echo "Placeholder options parsed."
    echo "Trading Mode: $TRADING_MODE"
    echo "API Port: $API_PORT"
    echo "VNC Enabled: $ENABLE_VNC"
else
    echo "Warning: /data/options.json not found. This is normal during local testing outside HA."
fi

echo "Boot validation complete. Gateway is NOT starting yet."
echo "Sleeping indefinitely to keep HA add-on running safely..."

# Sleep forever so HA keeps the add-on running
tail -f /dev/null
