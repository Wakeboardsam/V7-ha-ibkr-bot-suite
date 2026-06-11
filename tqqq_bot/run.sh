#!/bin/bash
set -euo pipefail

echo "Starting V7_tqqq_bot runtime..."
echo "[PR09] Parsing Home Assistant options..."

JTS_SETTINGS_DIR="/data/ibgateway/Jts"
IBC_CONFIG_DIR="/data/ibgateway"
IBC_CONFIG_FILE="${IBC_CONFIG_DIR}/config.ini"
IBC_TEMPLATE_FILE="/app/gateway/ibc_config.ini.template"

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
        echo "Warning: mask_account_ids_in_logs is false. Account ID will still be redacted by startup logging."
        echo "Configured IBKR account: [redacted]"
    fi
else
    echo "Warning: /data/options.json not found. Using local test defaults."
    IBKR_ACCOUNT_ID="DU1234567"
    MASK_LOGS="true"
    GATEWAY_HOST="127.0.0.1"
    GATEWAY_PORT=7497
    IBKR_USERNAME=""
    IBKR_PASSWORD=""
    TRADING_MODE="paper"
    READONLY_API="false"
    ENABLE_VNC="false"
    VNC_PORT=5900
fi

if [ "$GATEWAY_HOST" != "127.0.0.1" ] && [ "$GATEWAY_HOST" != "localhost" ]; then
    echo "[PR09] Warning: bundled tqqq_bot only supports local Gateway access. Forcing ibkr_host to 127.0.0.1."
    GATEWAY_HOST="127.0.0.1"
fi

export GATEWAY_HOST
export GATEWAY_PORT
export IBKR_USERNAME
export IBKR_PASSWORD
export TRADING_MODE
export JTS_SETTINGS_DIR

READONLY_VAL="no"
if [ "$READONLY_API" = "true" ]; then
    READONLY_VAL="yes"
fi
export READONLY_VAL

echo "[PR09] Configuring bundled Gateway API for local port ${GATEWAY_PORT}"
echo "[PR09] readonly_api=${READONLY_API}"
echo "[PR09] enable_vnc=${ENABLE_VNC}"
echo "[PR09] Gateway/JTS settings directory: ${JTS_SETTINGS_DIR}"
echo "[PR09] Gateway API access intended for localhost/127.0.0.1 only"
echo "Bot configured to connect to Gateway at: ${GATEWAY_HOST}:${GATEWAY_PORT}"

echo "[PR09] Creating persistent Gateway settings directories..."
mkdir -p "${JTS_SETTINGS_DIR}"
mkdir -p "${IBC_CONFIG_DIR}"

if [ ! -f "$IBC_TEMPLATE_FILE" ]; then
    echo "[PR09] ERROR: IBC template not found at ${IBC_TEMPLATE_FILE}"
    exit 1
fi

echo "[PR09] Rendering IBC config to persistent add-on data directory..."
envsubst < "$IBC_TEMPLATE_FILE" > "$IBC_CONFIG_FILE"
chmod 600 "$IBC_CONFIG_FILE"

echo "[PR09] Patching persistent jts.ini with verified runtime settings..."
touch "${JTS_SETTINGS_DIR}/jts.ini"
grep -q "^BypassOrderPrecautions=" "${JTS_SETTINGS_DIR}/jts.ini" || echo "BypassOrderPrecautions=true" >> "${JTS_SETTINGS_DIR}/jts.ini"
grep -q "^BypassRedirectOrderWarning=" "${JTS_SETTINGS_DIR}/jts.ini" || echo "BypassRedirectOrderWarning=true" >> "${JTS_SETTINGS_DIR}/jts.ini"

echo "Starting Xvfb..."
Xvfb :99 -ac -screen 0 1024x768x16 &
export DISPLAY=:99

if [ "$ENABLE_VNC" = "true" ]; then
    echo "[PR09] Starting x11vnc on port ${VNC_PORT} because enable_vnc=true..."
    x11vnc -display :99 -forever -nopw -bg -rfbport "$VNC_PORT" &
else
    echo "[PR09] VNC disabled."
fi

echo "Starting IB Gateway via IBC..."
export TWS_MAJOR_VRSN=1019
export TWS_PATH=/root/Jts
export IBC_PATH=/opt/ibc
export IBC_INI="${IBC_CONFIG_FILE}"

# Keep a copy at IBC's historical default path in case this IBC build ignores IBC_INI.
mkdir -p /root/ibc
cp "${IBC_CONFIG_FILE}" /root/ibc/config.ini
chmod 600 /root/ibc/config.ini

/opt/ibc/gatewaystart.sh -inline < /dev/null &
IBC_PID=$!

echo "Waiting for Gateway to initialize on port ${GATEWAY_PORT}..."
python3 /app/wait_for_gateway.py --port "$GATEWAY_PORT" --timeout 300

echo "Gateway is ready! Starting the Python bot runtime..."

exec python -m main
