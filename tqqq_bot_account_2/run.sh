#!/bin/bash
set -euo pipefail

echo "Starting V7_tqqq_bot_account_2 (Account 2) runtime..."
echo "Parsing Home Assistant options..."

ACTIVE_JTS_DIR="/root/Jts"
ACTIVE_IBC_DIR="/root/ibc"
IBC_CONFIG_FILE="${ACTIVE_IBC_DIR}/config.ini"
IBC_TEMPLATE_FILE="/app/gateway/ibc_config.ini.template"

PERSIST_JTS_DIR="/data/ibgateway/persist/root_Jts"
PERSIST_JAVA_DIR="/data/ibgateway/persist/root_java"

# We must export this so envsubst can use it in ibc_config.ini.template
export JTS_SETTINGS_DIR="${ACTIVE_JTS_DIR}"

echo "Matching v6 Gateway settings behavior: active settings path /root/Jts"

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
    GATEWAY_SETTINGS_SYNC_INTERVAL_SECONDS=$(jq -r '.gateway_settings_sync_interval_seconds // 300' /data/options.json)

    TIMEZONE=$(jq -r '.timezone // "America/Denver"' /data/options.json)
    GATEWAY_AUTO_RESTART_ENABLED=$(jq -r '.gateway_auto_restart_enabled // true' /data/options.json)
    GATEWAY_AUTO_RESTART_TIME=$(jq -r '.gateway_auto_restart_time // "11:48 PM"' /data/options.json)
    GATEWAY_COLD_RESTART_ENABLED=$(jq -r '.gateway_cold_restart_enabled // true' /data/options.json)
    GATEWAY_COLD_RESTART_TIME=$(jq -r '.gateway_cold_restart_time // "06:00 PM"' /data/options.json)
    GATEWAY_LIVE_WAIT_TIMEOUT_SECONDS=$(jq -r '.gateway_live_wait_timeout_seconds // 3600' /data/options.json)
    GATEWAY_PAPER_WAIT_TIMEOUT_SECONDS=$(jq -r '.gateway_paper_wait_timeout_seconds // 300' /data/options.json)

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
    GATEWAY_SETTINGS_SYNC_INTERVAL_SECONDS=300
    TIMEZONE="America/Denver"
    GATEWAY_AUTO_RESTART_ENABLED="true"
    GATEWAY_AUTO_RESTART_TIME="11:48 PM"
    GATEWAY_COLD_RESTART_ENABLED="true"
    GATEWAY_COLD_RESTART_TIME="06:00 PM"
    GATEWAY_LIVE_WAIT_TIMEOUT_SECONDS=3600
    GATEWAY_PAPER_WAIT_TIMEOUT_SECONDS=300
fi

if [ "$GATEWAY_HOST" != "127.0.0.1" ] && [ "$GATEWAY_HOST" != "localhost" ]; then
    echo "Warning: bundled tqqq_bot_account_2 only supports local Gateway access. Forcing ibkr_host to 127.0.0.1."
    GATEWAY_HOST="127.0.0.1"
fi

export GATEWAY_HOST
export GATEWAY_PORT
export IBKR_USERNAME
export IBKR_PASSWORD
export TRADING_MODE
export JTS_SETTINGS_DIR

# Key V6 / JTS environment variables
export TWS_PATH="${ACTIVE_JTS_DIR}"
export TWS_SETTINGS_PATH="${ACTIVE_JTS_DIR}"
export IBC_INI="${IBC_CONFIG_FILE}"
export TZ="${TIMEZONE}"

if [ "$GATEWAY_AUTO_RESTART_ENABLED" = "true" ]; then
    export AUTO_RESTART_TIME="${GATEWAY_AUTO_RESTART_TIME}"
else
    export AUTO_RESTART_TIME=""
fi

if [ "$GATEWAY_COLD_RESTART_ENABLED" = "true" ]; then
    # Sanitize prefix if it exists
    if [[ "$GATEWAY_COLD_RESTART_TIME" =~ ^[A-Za-z]+day\ (.*) ]]; then
        SANITIZED_TIME="${BASH_REMATCH[1]}"
        echo "[Gateway] Warning: gateway_cold_restart_time should be a time only. Stripping weekday prefix."
        export COLD_RESTART_TIME="${SANITIZED_TIME}"
    else
        export COLD_RESTART_TIME="${GATEWAY_COLD_RESTART_TIME}"
    fi
else
    export COLD_RESTART_TIME=""
fi

if [ "$TRADING_MODE" = "live" ]; then
    WAIT_TIMEOUT="${GATEWAY_LIVE_WAIT_TIMEOUT_SECONDS}"
else
    WAIT_TIMEOUT="${GATEWAY_PAPER_WAIT_TIMEOUT_SECONDS}"
fi

READONLY_VAL="no"
if [ "$READONLY_API" = "true" ]; then
    READONLY_VAL="yes"
fi
export READONLY_VAL

echo "Configuring bundled Gateway API for local port ${GATEWAY_PORT}"
echo "readonly_api=${READONLY_API}"
echo "enable_vnc=${ENABLE_VNC}"
echo "Gateway/JTS settings directory: ${JTS_SETTINGS_DIR}"
echo "Gateway API access intended for localhost/127.0.0.1 only"
echo "Bot configured to connect to Gateway at: ${GATEWAY_HOST}:${GATEWAY_PORT}"

echo "[Gateway] Timezone: ${TIMEZONE}"
if [ "$GATEWAY_AUTO_RESTART_ENABLED" = "true" ]; then
    echo "[Gateway] IBC AutoRestartTime: ${GATEWAY_AUTO_RESTART_TIME}"
else
    echo "[Gateway] IBC AutoRestartTime: (Disabled)"
fi
if [ "$GATEWAY_COLD_RESTART_ENABLED" = "true" ]; then
    echo "[Gateway] IBC ColdRestartTime: ${COLD_RESTART_TIME}"
else
    echo "[Gateway] IBC ColdRestartTime: (Disabled)"
fi
echo "[Gateway] Gateway wait timeout: ${WAIT_TIMEOUT} seconds"
echo "[Gateway] VNC is manual only; enable_vnc controls whether VNC starts"

echo "Creating persistent Gateway settings directories..."
mkdir -p "${PERSIST_JTS_DIR}"
mkdir -p "${PERSIST_JAVA_DIR}"
chmod 700 /data/ibgateway/persist "${PERSIST_JTS_DIR}" "${PERSIST_JAVA_DIR}"

mkdir -p "${ACTIVE_JTS_DIR}"
mkdir -p "${ACTIVE_IBC_DIR}"
mkdir -p /root/.java

echo "Restoring persisted Gateway settings from ${PERSIST_JTS_DIR}"
rsync -a "${PERSIST_JTS_DIR}/" "${ACTIVE_JTS_DIR}/" || true
echo "Restoring persisted Java preferences from ${PERSIST_JAVA_DIR}"
rsync -a "${PERSIST_JAVA_DIR}/" /root/.java/ || true

if [ ! -f "$IBC_TEMPLATE_FILE" ]; then
    echo "ERROR: IBC template not found at ${IBC_TEMPLATE_FILE}"
    exit 1
fi

echo "Rendering active IBC config..."
envsubst < "$IBC_TEMPLATE_FILE" > "$IBC_CONFIG_FILE"
chmod 600 "$IBC_CONFIG_FILE"
echo "Active IBC config written to ${IBC_CONFIG_FILE}"

echo "Patching active runtime jts.ini..."
touch "${ACTIVE_JTS_DIR}/jts.ini"
grep -q "^BypassOrderPrecautions=" "${ACTIVE_JTS_DIR}/jts.ini" || echo "BypassOrderPrecautions=true" >> "${ACTIVE_JTS_DIR}/jts.ini"
grep -q "^BypassRedirectOrderWarning=" "${ACTIVE_JTS_DIR}/jts.ini" || echo "BypassRedirectOrderWarning=true" >> "${ACTIVE_JTS_DIR}/jts.ini"

sync_gateway_settings() {
    # Conservative exclusions so we do not copy the installed Gateway application
    rsync -a \
      --exclude='ibgateway/' \
      --exclude='1019' \
      --exclude='*.jar' \
      --exclude='*.log' \
      --exclude='*.zip' \
      --exclude='*.sh' \
      --exclude='logs/' \
      --exclude='cache/' \
      --exclude='tmp/' \
      "${ACTIVE_JTS_DIR}/" "${PERSIST_JTS_DIR}/" || true

    rsync -a \
      --exclude='*.log' \
      --exclude='cache/' \
      --exclude='tmp/' \
      /root/.java/ "${PERSIST_JAVA_DIR}/" || true
}

start_persistence_loop() {
    echo "Persistent Gateway settings sync loop started; interval=${GATEWAY_SETTINGS_SYNC_INTERVAL_SECONDS}s."
    while true; do
        sleep "$GATEWAY_SETTINGS_SYNC_INTERVAL_SECONDS"
        sync_gateway_settings
    done
}

SHUTTING_DOWN=false

shutdown_handler() {
    if [ "$SHUTTING_DOWN" = "true" ]; then
        return
    fi
    SHUTTING_DOWN=true

    echo "Shutdown signal received; stopping bot and Gateway processes."

    if [ -n "${PERSISTENCE_PID:-}" ] && kill -0 "$PERSISTENCE_PID" 2>/dev/null; then
        kill -TERM "$PERSISTENCE_PID"
    fi

    if [ -n "${BOT_PID:-}" ] && kill -0 "$BOT_PID" 2>/dev/null; then
        kill -TERM "$BOT_PID"
    fi

    if [ -n "${IBC_PID:-}" ] && kill -0 "$IBC_PID" 2>/dev/null; then
        kill -TERM "$IBC_PID"
    fi

    if [ -n "${XVFB_PID:-}" ] && kill -0 "$XVFB_PID" 2>/dev/null; then
        kill -TERM "$XVFB_PID"
    fi

    if [ "$ENABLE_VNC" = "true" ]; then
        if [ -n "${X11VNC_PID:-}" ] && kill -0 "$X11VNC_PID" 2>/dev/null; then
            kill -TERM "$X11VNC_PID"
        else
            pkill -TERM x11vnc || true
        fi
    fi

    # Wait briefly for all child processes to stop
    sleep 2

    if [ -n "${BOT_PID:-}" ]; then wait "$BOT_PID" 2>/dev/null || true; fi
    if [ -n "${IBC_PID:-}" ]; then wait "$IBC_PID" 2>/dev/null || true; fi
    if [ -n "${XVFB_PID:-}" ]; then wait "$XVFB_PID" 2>/dev/null || true; fi
    if [ -n "${PERSISTENCE_PID:-}" ]; then wait "$PERSISTENCE_PID" 2>/dev/null || true; fi

    echo "Graceful shutdown complete."
}

trap 'shutdown_handler' SIGTERM SIGINT

echo "Starting Xvfb..."
Xvfb :99 -ac -screen 0 1024x768x16 &
XVFB_PID=$!
export DISPLAY=:99

X11VNC_PID=""
if [ "$ENABLE_VNC" = "true" ]; then
    echo "Starting x11vnc on port ${VNC_PORT} because enable_vnc=true..."
    x11vnc -display :99 -forever -nopw -rfbport "$VNC_PORT" &
    X11VNC_PID=$!
else
    echo "VNC disabled."
fi

echo "Starting IB Gateway via IBC..."
export TWS_MAJOR_VRSN=1019
export IBC_PATH=/opt/ibc

# Copy the generated config to the persistent /data dir as a diagnostic backup
mkdir -p /data/ibgateway
cp "${IBC_CONFIG_FILE}" /data/ibgateway/config.ini
chmod 600 /data/ibgateway/config.ini

/opt/ibc/gatewaystart.sh -inline < /dev/null &
IBC_PID=$!

tail_recent_ibc_logs_sanitized() {
    echo "--- Recent IBC Logs ---"
    # Find the most recent log file
    local recent_log
    recent_log=$(ls -t /root/ibc/logs/*.txt 2>/dev/null | head -n 1)
    if [ -n "$recent_log" ]; then
        # Tail the last 50 lines and sanitize
        tail -n 50 "$recent_log" | \
            sed -E 's/password=[^ ]+/password=****/' | \
            sed -E 's/username=[^ ]+/username=****/' | \
            sed -E 's/[DU][0-9]{5,}/****/'
    else
        echo "No IBC logs found in /root/ibc/logs/"
    fi
    echo "-----------------------"
}

echo "Waiting for Gateway to initialize on port ${GATEWAY_PORT}..."
if ! python3 /app/wait_for_gateway.py --port "$GATEWAY_PORT" --timeout "$WAIT_TIMEOUT"; then
    echo "[Gateway] Gateway API did not become ready before timeout. Recent IBC diagnostics:"
    tail_recent_ibc_logs_sanitized
    exit 1
fi

echo "Gateway port is ready; running initial persistent settings sync."
sync_gateway_settings
echo "Initial Gateway settings sync complete."

# Start the background sync loop AFTER gateway is ready
start_persistence_loop &
PERSISTENCE_PID=$!

echo "Gateway is ready! Starting the Python bot runtime..."
python -m main &
BOT_PID=$!

set +e
wait "$BOT_PID"
BOT_EXIT_CODE=$?
set -e

shutdown_handler
exit "$BOT_EXIT_CODE"
