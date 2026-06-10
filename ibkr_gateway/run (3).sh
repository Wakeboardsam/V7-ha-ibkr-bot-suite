#!/bin/bash
set -e

echo "Parsing Home Assistant options..."

if [ -f /data/options.json ]; then
    IBKR_USERNAME=$(jq -r '.ibkr_username // empty' /data/options.json)
    IBKR_PASSWORD=$(jq -r '.ibkr_password // empty' /data/options.json)
    TRADING_MODE=$(jq -r '.trading_mode // "paper"' /data/options.json)
    API_PORT=$(jq -r '.api_port // 7497' /data/options.json)
    VNC_PORT=$(jq -r '.vnc_port // 5900' /data/options.json)
    READONLY_API=$(jq -r '.readonly_api // false' /data/options.json)
    ENABLE_VNC=$(jq -r '.enable_vnc // false' /data/options.json)
else
    echo "Warning: /data/options.json not found. Using defaults."
    TRADING_MODE="paper"
    API_PORT=7497
    VNC_PORT=5900
    READONLY_API="false"
    ENABLE_VNC="false"
fi

echo "Configuration:"
echo "Trading Mode: $TRADING_MODE"
echo "API Port: $API_PORT"
echo "Readonly API: $READONLY_API"
echo "VNC Enabled: $ENABLE_VNC"

READONLY_VAL="no"
if [ "$READONLY_API" = "true" ]; then
    READONLY_VAL="yes"
fi

echo "Generating IBC config..."
mkdir -p /root/ibc
cat <<EOF > /root/ibc/config.ini
IbLoginId=${IBKR_USERNAME}
IbPassword=${IBKR_PASSWORD}
TradingMode=${TRADING_MODE}
IbDir=/root/Jts
ReadOnlyApi=${READONLY_VAL}
OverrideTwsApiPort=${API_PORT}
AcceptIncomingConnectionAction=accept
AcceptNonBrokerageAccountWarning=yes
BypassOrderPrecautions=yes
BypassRedirectOrderWarning=yes
AllowBlindTrading=yes
EOF

echo "Injecting API bypass settings directly into jts.ini..."
mkdir -p /root/Jts
touch /root/Jts/jts.ini
grep -q "BypassOrderPrecautions" /root/Jts/jts.ini || echo "BypassOrderPrecautions=true" >> /root/Jts/jts.ini
grep -q "BypassRedirectOrderWarning" /root/Jts/jts.ini || echo "BypassRedirectOrderWarning=true" >> /root/Jts/jts.ini

echo "Starting Xvfb..."
Xvfb :99 -ac -screen 0 1024x768x16 &
export DISPLAY=:99

if [ "$ENABLE_VNC" = "true" ]; then
    # VNC is intended ONLY for temporary private-network troubleshooting and IB Gateway GUI access.
    echo "Starting x11vnc on port $VNC_PORT..."
    x11vnc -display :99 -forever -nopw -bg -rfbport "$VNC_PORT" &
fi

echo "Starting IB Gateway via IBC..."
export TWS_MAJOR_VRSN=1019
export TWS_PATH=/root/Jts
export IBC_PATH=/opt/ibc

# Run IBC in the background
/opt/ibc/gatewaystart.sh -inline < /dev/null &
IBC_PID=$!

echo "Waiting for Gateway to initialize on port $API_PORT..."
python3 /app/wait_for_gateway.py --port "$API_PORT" --timeout 300

echo "Gateway is ready! Tailing logs to keep container alive..."

# Instead of blindly tailing /dev/null, tail the logs. If the IBC process dies, the script should exit.
# We'll wait on the IBC process.
wait $IBC_PID
