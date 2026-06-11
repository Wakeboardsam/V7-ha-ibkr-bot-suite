#!/bin/bash
set -e

echo "Starting V7_tqqq_bot runtime..."
echo "Parsing Home Assistant options..."

if [ -f /data/options.json ]; then
    # Bot / Account Config
    IBKR_ACCOUNT_ID=$(jq -r '.ibkr_account_id // "DU1234567"' /data/options.json)
    MASK_LOGS=$(jq -r '.mask_account_ids_in_logs // true' /data/options.json)
    GATEWAY_HOST=$(jq -r '.ibkr_host // "127.0.0.1"' /data/options.json)
    GATEWAY_PORT=$(jq -r '.ibkr_port // 7497' /data/options.json)

    # Gateway Config
    IBKR_USERNAME=$(jq -r '.ibkr_username // empty' /data/options.json)
    IBKR_PASSWORD=$(jq -r '.ibkr_password // empty' /data/options.json)
    TRADING_MODE=$(jq -r '.trading_mode // "paper"' /data/options.json)
    READONLY_API=$(jq -r '.readonly_api // false' /data/options.json)
    ENABLE_VNC=$(jq -r '.enable_vnc // false' /data/options.json)
    VNC_PORT=$(jq -r '.vnc_port // 5900' /data/options.json)

    if [ "$MASK_LOGS" = "true" ]; then
        if [[ ${#IBKR_ACCOUNT_ID} -gt 6 ]]; then
            PREFIX="${IBKR_ACCOUNT_ID:0:3}"
            SUFFIX="${IBKR_ACCOUNT_ID: -3}"
            MASKED_ACCOUNT_ID="${PREFIX}****${SUFFIX}"
        else
            MASKED_ACCOUNT_ID="****"
        fi
        echo "Configured IBKR account: ${MASKED_ACCOUNT_ID}"
    else
        echo "Warning: mask_account_ids_in_logs is false. Not masking."
        echo "Configured IBKR account: [redacted]"
    fi
    echo "Bot configured to connect to Gateway at: ${GATEWAY_HOST}:${GATEWAY_PORT}"
else
    echo "Warning: /data/options.json not found. Using local test defaults."
    TRADING_MODE="paper"
    GATEWAY_PORT=7497
    VNC_PORT=5900
    READONLY_API="false"
    ENABLE_VNC="false"
fi

echo "Configuration:"
echo "Trading Mode: $TRADING_MODE"
echo "API Port: $GATEWAY_PORT"
echo "Readonly API: $READONLY_API"
echo "VNC Enabled: $ENABLE_VNC"

READONLY_VAL="no"
if [ "$READONLY_API" = "true" ]; then
    READONLY_VAL="yes"
fi

echo "Generating IBC config..."
mkdir -p /root/ibc
cat <<IBC_EOF > /root/ibc/config.ini
IbLoginId=${IBKR_USERNAME}
IbPassword=${IBKR_PASSWORD}
TradingMode=${TRADING_MODE}
IbDir=/root/Jts
ReadOnlyApi=${READONLY_VAL}
OverrideTwsApiPort=${GATEWAY_PORT}
AcceptIncomingConnectionAction=accept
AcceptNonBrokerageAccountWarning=yes
BypassOrderPrecautions=yes
BypassRedirectOrderWarning=yes
AllowBlindTrading=yes
IBC_EOF

chmod 600 /root/ibc/config.ini

echo "Injecting API bypass settings directly into jts.ini..."
mkdir -p /root/Jts
touch /root/Jts/jts.ini
grep -q "BypassOrderPrecautions" /root/Jts/jts.ini || echo "BypassOrderPrecautions=true" >> /root/Jts/jts.ini
grep -q "BypassRedirectOrderWarning" /root/Jts/jts.ini || echo "BypassRedirectOrderWarning=true" >> /root/Jts/jts.ini

echo "Starting Xvfb..."
Xvfb :99 -ac -screen 0 1024x768x16 &
export DISPLAY=:99

if [ "$ENABLE_VNC" = "true" ]; then
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

echo "Waiting for Gateway to initialize on port $GATEWAY_PORT..."
python3 /app/wait_for_gateway.py --port "$GATEWAY_PORT" --timeout 300

echo "Gateway is ready! Starting the Python bot runtime..."

# Wait for the python bot instead of the IBC so we properly exit if bot crashes.
# The bot relies on Gateway. If we exec python, we replace the bash process,
# which correctly manages the Docker container's primary process.
exec python -m main
