#!/bin/bash
set -euo pipefail

echo "Starting V7_tqqq_bot runtime..."
echo "Parsing Home Assistant options..."

ACTIVE_JTS_DIR="/root/Jts"
ACTIVE_IBC_DIR="/root/ibc"
IBC_CONFIG_FILE="${ACTIVE_IBC_DIR}/config.ini"
IBC_TEMPLATE_FILE="/app/gateway/ibc_config.ini.template"

PERSIST_JTS_DIR="/data/ibgateway/persist/root_Jts"
PERSIST_JAVA_DIR="/data/ibgateway/persist/root_java"

# How often Gateway settings are copied back to /data. A fixed default, not an add-on option.
GATEWAY_SETTINGS_SYNC_INTERVAL_SECONDS=300

# We must export this so envsubst can use it in ibc_config.ini.template
export JTS_SETTINGS_DIR="${ACTIVE_JTS_DIR}"

echo "Matching v6 Gateway settings behavior: active settings path /root/Jts"

# Saved settings from before the sectioned Configuration page are moved into
# the new sections once; the add-on then restarts with them. It never starts the
# Gateway or the bot on settings it could not move.
if [ -f /data/options.json ]; then
    set +e
    python3 /app/config/migrate_options.py
    MIGRATION_STATUS=$?
    set -e
    if [ "$MIGRATION_STATUS" -eq 3 ]; then
        echo "Waiting for Home Assistant to restart the add-on with the moved settings..."
        sleep 120
        echo "The add-on did not restart. Start it again from Home Assistant."
        exit 1
    elif [ "$MIGRATION_STATUS" -ne 0 ]; then
        exit 1
    fi
fi

# opt PATH DEFAULT: the saved value, or DEFAULT when it is missing. A saved
# false stays false (jq's // operator would replace it with the default).
opt() {
    jq -r --argjson fallback "$2" "($1) as \$v | if \$v == null then \$fallback else \$v end" /data/options.json
}

if [ -f /data/options.json ]; then
    # Account and trading
    IBKR_ACCOUNT_ID=$(opt '.account.ibkr_account_id' '"DU1234567"')
    IBKR_USERNAME=$(opt '.account.ibkr_username' '""')
    IBKR_PASSWORD=$(opt '.account.ibkr_password' '""')
    TRADING_MODE=$(opt '.account.trading_mode' '"paper"')
    READONLY_API=$(opt '.account.readonly_api' 'true')

    # Schedule
    TIMEZONE=$(opt '.schedule.timezone' '"America/Denver"')
    GATEWAY_AUTO_RESTART_ENABLED=$(opt '.schedule.gateway_auto_restart_enabled' 'true')
    GATEWAY_AUTO_RESTART_TIME=$(opt '.schedule.gateway_auto_restart_time' '"23:48"')
    WEEKEND_PAUSE_ENABLED=$(opt '.schedule.weekend_pause_enabled' 'true')
    WEEKEND_PAUSE_START_FRIDAY=$(opt '.schedule.weekend_pause_start_friday' '"18:15"')
    WEEKEND_PAUSE_END_SUNDAY=$(opt '.schedule.weekend_pause_end_sunday' '"09:00"')

    # Advanced
    GATEWAY_PORT=$(opt '.advanced.ibkr_port' '7497')
    MASK_LOGS=$(opt '.advanced.mask_account_ids_in_logs' 'true')
    ENABLE_VNC=$(opt '.advanced.enable_vnc' 'false')
    VNC_PORT=$(opt '.advanced.vnc_port' '5900')
    GATEWAY_LIVE_WAIT_TIMEOUT_SECONDS=$(opt '.advanced.gateway_live_wait_timeout_seconds' '3600')
    GATEWAY_PAPER_WAIT_TIMEOUT_SECONDS=$(opt '.advanced.gateway_paper_wait_timeout_seconds' '300')

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
    GATEWAY_PORT=7497
    IBKR_USERNAME=""
    IBKR_PASSWORD=""
    TRADING_MODE="paper"
    READONLY_API="true"
    ENABLE_VNC="false"
    VNC_PORT=5900
    TIMEZONE="America/Denver"
    GATEWAY_AUTO_RESTART_ENABLED="true"
    GATEWAY_AUTO_RESTART_TIME="23:48"
    WEEKEND_PAUSE_ENABLED="true"
    WEEKEND_PAUSE_START_FRIDAY="18:15"
    WEEKEND_PAUSE_END_SUNDAY="09:00"
    GATEWAY_LIVE_WAIT_TIMEOUT_SECONDS=3600
    GATEWAY_PAPER_WAIT_TIMEOUT_SECONDS=300
fi

# The bot always connects to its own Gateway inside this add-on.
GATEWAY_HOST="127.0.0.1"

export GATEWAY_HOST
export GATEWAY_PORT
export IBKR_USERNAME
export IBKR_PASSWORD
export TRADING_MODE
export JTS_SETTINGS_DIR
export TZ="${TIMEZONE}"

# The page uses 24-hour HH:MM. IBC wants "hh:mm AM/PM" for the daily restart.
to_ibc_12_hour() {
    local hour minute suffix
    hour=$((10#${1%%:*}))
    minute=${1##*:}
    suffix="AM"
    if [ "$hour" -ge 12 ]; then suffix="PM"; fi
    hour=$((hour % 12))
    if [ "$hour" -eq 0 ]; then hour=12; fi
    printf "%02d:%s %s" "$hour" "$minute" "$suffix"
}

if [ "$GATEWAY_AUTO_RESTART_ENABLED" = "true" ]; then
    export AUTO_RESTART_TIME="$(to_ibc_12_hour "$GATEWAY_AUTO_RESTART_TIME")"
else
    export AUTO_RESTART_TIME=""
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
    echo "[Gateway] IBC AutoRestartTime: ${AUTO_RESTART_TIME}"
else
    echo "[Gateway] IBC AutoRestartTime: (Disabled)"
fi
if [ "$WEEKEND_PAUSE_ENABLED" = "true" ]; then
    echo "[Weekend shutdown] Off Friday ${WEEKEND_PAUSE_START_FRIDAY}, back on Sunday ${WEEKEND_PAUSE_END_SUNDAY} (${TIMEZONE})"
else
    echo "[Weekend shutdown] (Disabled)"
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

# ibg.tmp.xml is the Gateway's half-written settings save. A saved copy left
# over from a Gateway that was stopped mid-save is not restored or saved again,
# so each start sees only the finished ibg.xml. Copies already in /data are
# left in place, just not used.
echo "Restoring persisted Gateway settings from ${PERSIST_JTS_DIR}"
rsync -a --exclude='ibg.tmp.xml' "${PERSIST_JTS_DIR}/" "${ACTIVE_JTS_DIR}/" || true
echo "Restoring persisted Java preferences from ${PERSIST_JAVA_DIR}"
rsync -a "${PERSIST_JAVA_DIR}/" /root/.java/ || true

# One line per start, so the log shows whether the Gateway's own settings file
# (ibg.xml) came back and how much the saved settings take up. The folder name
# is left out because the Gateway derives it from the login.
report_saved_gateway_settings() {
    local saved_files total_size
    saved_files=$(find "${PERSIST_JTS_DIR}" -mindepth 2 -maxdepth 2 -name ibg.xml 2>/dev/null | wc -l)
    total_size=$(du -sh /data/ibgateway/persist 2>/dev/null | cut -f1)
    if [ "$saved_files" -gt 0 ]; then
        echo "[Gateway settings] Saved ibg.xml found in persistent storage and copied back; the Gateway decides whether it loads. Saved settings size: ${total_size:-0}."
    else
        echo "[Gateway settings] No saved ibg.xml in persistent storage yet; the Gateway may offer to recover from a backup. Saved settings size: ${total_size:-0}."
    fi
}
report_saved_gateway_settings

if [ ! -f "$IBC_TEMPLATE_FILE" ]; then
    echo "ERROR: IBC template not found at ${IBC_TEMPLATE_FILE}"
    exit 1
fi

echo "Rendering active IBC config..."
envsubst < "$IBC_TEMPLATE_FILE" > "$IBC_CONFIG_FILE"
chmod 600 "$IBC_CONFIG_FILE"
echo "Active IBC config written to ${IBC_CONFIG_FILE}"

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
      --exclude='ibg.tmp.xml' \
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

    # The Gateway may write its settings as it closes, after the last periodic
    # copy, so copy them once more now that it has stopped.
    if [ -n "${IBC_PID:-}" ]; then
        echo "Saving Gateway settings to /data before stopping."
        sync_gateway_settings
    fi

    echo "Graceful shutdown complete."
}

STOP_REQUESTED=false
trap 'STOP_REQUESTED=true; shutdown_handler' SIGTERM SIGINT

# Exit code the bot uses when the weekend shutdown begins.
WEEKEND_PAUSE_EXIT_CODE=10

# During the weekend shutdown nothing starts: no Gateway, no login, no bot. The
# add-on keeps running so Home Assistant does not restart or stop it, and
# starts normally when the shutdown ends.
weekend_pause_seconds_left() {
    if [ "$WEEKEND_PAUSE_ENABLED" != "true" ]; then
        echo 0
        return
    fi
    python3 /app/utils/weekend_pause.py --timezone "$TIMEZONE" \
        --start "$WEEKEND_PAUSE_START_FRIDAY" --end "$WEEKEND_PAUSE_END_SUNDAY" || echo 0
}

PAUSE_SECONDS=$(weekend_pause_seconds_left)
if [ "$PAUSE_SECONDS" -gt 0 ]; then
    echo "[Weekend shutdown] Bot and Gateway are off until Sunday ${WEEKEND_PAUSE_END_SUNDAY} (${TIMEZONE}), ${PAUSE_SECONDS} seconds from now."
    sleep "$PAUSE_SECONDS" &
    SLEEP_PID=$!
    wait "$SLEEP_PID" || true
    if [ "$STOP_REQUESTED" = "true" ]; then
        kill -TERM "$SLEEP_PID" 2>/dev/null || true
        exit 0
    fi
    echo "[Weekend shutdown] Turning back on: starting the Gateway and bot."
fi

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

echo "[Gateway] Pre-flight check: verifying preserved IB Gateway JRE..."
JAVA_BIN="/opt/ibgateway_jre/bin/java"
if [ ! -x "$JAVA_BIN" ]; then
    echo "ERROR: Preserved Java runtime binary not found or not executable at $JAVA_BIN."
    exit 1
fi
echo "[Gateway] Java runtime version:"
"$JAVA_BIN" -version

echo "Starting IB Gateway via IBC..."

# Earlier versions copied the rendered IBC config, password included, to /data,
# where Home Assistant backups pick it up. Nothing reads it, so remove it.
rm -f /data/ibgateway/config.ini

# IBC's own launcher: it logs to ${LOG_PATH}/ibc-<version>_GATEWAY-1019_<Weekday>.txt
# and runs ibcstart.sh, which restarts the Gateway when IBC asks for it. These
# are the values IBC's gatewaystart.sh used to set. TRADING_MODE and
# TWS_SETTINGS_PATH stay empty so IBC takes the trading mode from the config
# file and keeps the settings in TWS_PATH. A 2FA timeout ends IBC; the add-on
# then waits out the Gateway timeout and exits.
APP=GATEWAY TWS_MAJOR_VRSN=1019 IBC_PATH=/opt/ibc IBC_INI="${IBC_CONFIG_FILE}" \
    TWS_PATH="${ACTIVE_JTS_DIR}" TWS_SETTINGS_PATH="" LOG_PATH="${ACTIVE_IBC_DIR}/logs" \
    JAVA_PATH=/opt/ibgateway_jre/bin TRADING_MODE="" TWOFA_TIMEOUT_ACTION=exit \
    TWSUSERID="" TWSPASSWORD="" FIXUSERID="" FIXPASSWORD="" \
    /opt/ibc/scripts/displaybannerandlaunch.sh < /dev/null &
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

if [ "$BOT_EXIT_CODE" -eq "$WEEKEND_PAUSE_EXIT_CODE" ] && [ "$STOP_REQUESTED" != "true" ]; then
    # Gateway and bot are stopped. Start this script again, which waits out
    # the weekend shutdown before starting them.
    echo "[Weekend shutdown] Bot and Gateway turned off for the weekend."
    exec /app/run.sh
fi
exit "$BOT_EXIT_CODE"
