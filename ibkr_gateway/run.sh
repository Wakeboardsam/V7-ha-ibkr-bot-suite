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
    TRUSTED_IPS=$(jq -r '.trusted_ips // "127.0.0.1"' /data/options.json)
else
    echo "Warning: /data/options.json not found. Using defaults."
    IBKR_USERNAME=""
    IBKR_PASSWORD=""
    TRADING_MODE="paper"
    API_PORT=7497
    VNC_PORT=5900
    READONLY_API="false"
    ENABLE_VNC="false"
    TRUSTED_IPS="127.0.0.1"
fi

echo "Configuration:"
echo "Trading Mode: $TRADING_MODE"
echo "API Port: $API_PORT"
echo "Readonly API: $READONLY_API"
echo "VNC Enabled: $ENABLE_VNC"
echo "Trusted API IPs: $TRUSTED_IPS"

READONLY_VAL="no"
if [ "$READONLY_API" = "true" ]; then
    READONLY_VAL="yes"
fi

BOT_TRUSTED_IP="$(echo "$TRUSTED_IPS" \
    | tr ',' '\n' \
    | sed 's/^ *//;s/ *$//' \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
    | grep -v '^127\.' \
    | head -n 1 || true)"

if [ -z "$BOT_TRUSTED_IP" ]; then
    echo "Warning: no exact non-localhost trusted IPv4 found in trusted_ips."
    echo "For the bot, use something like: trusted_ips: 127.0.0.1,172.30.33.3"
else
    echo "Bot trusted IPv4 for GUI automation: $BOT_TRUSTED_IP"
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

echo "Injecting legacy API bypass settings directly into jts.ini..."
mkdir -p /root/Jts
touch /root/Jts/jts.ini
grep -q "BypassOrderPrecautions" /root/Jts/jts.ini || echo "BypassOrderPrecautions=true" >> /root/Jts/jts.ini
grep -q "BypassRedirectOrderWarning" /root/Jts/jts.ini || echo "BypassRedirectOrderWarning=true" >> /root/Jts/jts.ini

echo "Starting Xvfb..."
Xvfb :99 -ac -screen 0 1024x768x16 &
export DISPLAY=:99

if [ "$ENABLE_VNC" = "true" ]; then
    echo "Starting x11vnc on port $VNC_PORT..."
    x11vnc -display :99 -forever -nopw -bg -rfbport "$VNC_PORT" -noxdamage -cursor arrow &
fi

# ---------------------------------------------------------------------------
# GUI fallback automation
# ---------------------------------------------------------------------------

# SSL dialog.
SSL_BUTTON_X="${SSL_BUTTON_X:-455}"
SSL_BUTTON_Y="${SSL_BUTTON_Y:-452}"

# Main Gateway menu coordinates, relative to the Gateway window.
CONFIGURE_MENU_X="${CONFIGURE_MENU_X:-270}"
CONFIGURE_MENU_Y="${CONFIGURE_MENU_Y:-14}"
CONFIGURE_SETTINGS_X="${CONFIGURE_SETTINGS_X:-270}"
CONFIGURE_SETTINGS_Y="${CONFIGURE_SETTINGS_Y:-42}"

# Configuration window coordinates.
# Target API -> Settings, not API -> News Configuration.
API_SETTINGS_TREE_X="${API_SETTINGS_TREE_X:-86}"
API_SETTINGS_TREE_Y="${API_SETTINGS_TREE_Y:-108}"

# Right pane focus and scrollbar.
RIGHT_PANE_X="${RIGHT_PANE_X:-500}"
RIGHT_PANE_Y="${RIGHT_PANE_Y:-250}"

API_SCROLLBAR_X="${API_SCROLLBAR_X:-650}"
API_SCROLLBAR_TOP_Y="${API_SCROLLBAR_TOP_Y:-115}"
API_SCROLLBAR_BOTTOM_Y="${API_SCROLLBAR_BOTTOM_Y:-425}"

# Bottom API settings area in the RIGHT pane after scrolling to bottom.
LOCALHOST_ONLY_CHECK_X="${LOCALHOST_ONLY_CHECK_X:-335}"
LOCALHOST_ONLY_CHECK_Y="${LOCALHOST_ONLY_CHECK_Y:-425}"

TRUSTED_CREATE_X="${TRUSTED_CREATE_X:-620}"
TRUSTED_CREATE_Y="${TRUSTED_CREATE_Y:-455}"

APPLY_X="${APPLY_X:-430}"
APPLY_Y="${APPLY_Y:-520}"

OK_X="${OK_X:-365}"
OK_Y="${OK_Y:-520}"

have_xdotool() {
    command -v xdotool >/dev/null 2>&1
}

gui_log() {
    echo "$@" >&2
}

find_window_by_name() {
    local pattern="$1"
    xdotool search --onlyvisible --name "$pattern" 2>/dev/null | tail -n 1 || true
}

find_gateway_window() {
    local win=""

    win="$(find_window_by_name "IBKR GATEWAY")"
    if [ -n "$win" ]; then
        echo "$win"
        return 0
    fi

    win="$(find_window_by_name "Gateway")"
    if [ -n "$win" ]; then
        echo "$win"
        return 0
    fi

    return 1
}

find_configuration_window() {
    local win=""

    win="$(find_window_by_name "Configuration")"
    if [ -n "$win" ]; then
        echo "$win"
        return 0
    fi

    win="$(find_window_by_name "Trader Workstation Configuration")"
    if [ -n "$win" ]; then
        echo "$win"
        return 0
    fi

    return 1
}

find_ssl_window() {
    local win=""

    win="$(find_window_by_name "USE SSL")"
    if [ -n "$win" ]; then
        echo "$win"
        return 0
    fi

    win="$(find_window_by_name "SSL")"
    if [ -n "$win" ]; then
        echo "$win"
        return 0
    fi

    return 1
}

click_window_rel() {
    local win="$1"
    local x="$2"
    local y="$3"

    if [ -z "$win" ]; then
        gui_log "GUI fallback warning: click_window_rel called with empty window id."
        return 0
    fi

    xdotool mousemove --window "$win" "$x" "$y" >/dev/null 2>&1 || true
    sleep 0.15
    xdotool click 1 >/dev/null 2>&1 || true
}

drag_window_rel() {
    local win="$1"
    local x1="$2"
    local y1="$3"
    local x2="$4"
    local y2="$5"

    if [ -z "$win" ]; then
        gui_log "GUI fallback warning: drag_window_rel called with empty window id."
        return 0
    fi

    xdotool mousemove --window "$win" "$x1" "$y1" >/dev/null 2>&1 || true
    sleep 0.2
    xdotool mousedown 1 >/dev/null 2>&1 || true
    sleep 0.2
    xdotool mousemove --sync --window "$win" "$x2" "$y2" >/dev/null 2>&1 || true
    sleep 0.2
    xdotool mouseup 1 >/dev/null 2>&1 || true
    sleep 0.5
}

key_to_window() {
    local win="$1"
    shift

    if [ -n "$win" ]; then
        xdotool key --window "$win" --clearmodifiers "$@" >/dev/null 2>&1 || true
    else
        xdotool key --clearmodifiers "$@" >/dev/null 2>&1 || true
    fi
}

scroll_down_window() {
    local win="$1"
    local x="$2"
    local y="$3"

    xdotool mousemove --window "$win" "$x" "$y" >/dev/null 2>&1 || true
    sleep 0.2

    for i in $(seq 1 40); do
        xdotool click 5 >/dev/null 2>&1 || true
        sleep 0.05
    done
}

scroll_api_settings_to_bottom() {
    local win="$1"

    echo "GUI fallback: force-scrolling API settings pane to bottom."

    # Click safely in right pane first.
    click_window_rel "$win" "$RIGHT_PANE_X" "$RIGHT_PANE_Y"
    sleep 0.3

    # Keyboard attempts.
    key_to_window "$win" End
    sleep 0.3
    for i in $(seq 1 8); do
        key_to_window "$win" Page_Down
        sleep 0.08
    done

    # Wheel attempts over right pane.
    scroll_down_window "$win" "$RIGHT_PANE_X" "$RIGHT_PANE_Y"
    sleep 0.3

    # Drag scrollbar thumb/track downward. This is the important part.
    drag_window_rel "$win" "$API_SCROLLBAR_X" "$API_SCROLLBAR_TOP_Y" "$API_SCROLLBAR_X" "$API_SCROLLBAR_BOTTOM_Y"
    sleep 0.5

    # One more wheel-down after drag.
    scroll_down_window "$win" "$RIGHT_PANE_X" "$RIGHT_PANE_Y"
    sleep 0.5
}

start_ssl_reconnect_watcher() {
    (
        set +e

        if ! have_xdotool; then
            echo "GUI fallback warning: xdotool not installed; cannot auto-click SSL prompt."
            exit 0
        fi

        echo "Starting SSL reconnect GUI watcher..."

        for i in $(seq 1 150); do
            ssl_win="$(find_ssl_window || true)"

            if [ -n "$ssl_win" ]; then
                echo "GUI fallback: SSL dialog found; accepting SSL reconnect."
                xdotool windowactivate --sync "$ssl_win" >/dev/null 2>&1 || true
                sleep 0.2
                key_to_window "$ssl_win" Return
                sleep 0.5

                # Fallback click inside the SSL dialog if Return did not work.
                xdotool mousemove "$SSL_BUTTON_X" "$SSL_BUTTON_Y" >/dev/null 2>&1 || true
                sleep 0.1
                xdotool click 1 >/dev/null 2>&1 || true
            fi

            sleep 2
        done

        echo "SSL reconnect GUI watcher finished."
    ) &
    SSL_WATCHER_PID=$!
}

open_gateway_configuration_window() {
    local main_win=""
    local cfg_win=""

    cfg_win="$(find_configuration_window || true)"
    if [ -n "$cfg_win" ]; then
        gui_log "GUI fallback: Configuration window already open: $cfg_win"
        printf '%s\n' "$cfg_win"
        return 0
    fi

    main_win="$(find_gateway_window || true)"

    if [ -z "$main_win" ]; then
        gui_log "GUI fallback warning: could not find IBKR Gateway main window."
        return 1
    fi

    gui_log "GUI fallback: activating Gateway window $main_win"
    xdotool windowactivate --sync "$main_win" >/dev/null 2>&1 || true
    sleep 1

    xdotool key Escape >/dev/null 2>&1 || true
    sleep 0.3

    # Preferred path: direct mouse menu open.
    gui_log "GUI fallback: opening Configure -> Settings using mouse menu path."
    click_window_rel "$main_win" "$CONFIGURE_MENU_X" "$CONFIGURE_MENU_Y"
    sleep 0.6
    click_window_rel "$main_win" "$CONFIGURE_SETTINGS_X" "$CONFIGURE_SETTINGS_Y"
    sleep 2

    cfg_win="$(find_configuration_window || true)"
    if [ -n "$cfg_win" ]; then
        gui_log "GUI fallback: opened Configuration window $cfg_win by mouse."
        printf '%s\n' "$cfg_win"
        return 0
    fi

    # Fallback 1: Alt+C then Return.
    gui_log "GUI fallback: mouse menu failed; trying Alt+C then Return."
    xdotool windowactivate --sync "$main_win" >/dev/null 2>&1 || true
    sleep 0.5
    key_to_window "$main_win" alt+c
    sleep 0.6
    key_to_window "" Return
    sleep 2

    cfg_win="$(find_configuration_window || true)"
    if [ -n "$cfg_win" ]; then
        gui_log "GUI fallback: opened Configuration window $cfg_win by keyboard Return."
        printf '%s\n' "$cfg_win"
        return 0
    fi

    # Fallback 2: Alt+C then S.
    gui_log "GUI fallback: Return failed; trying Alt+C then S."
    xdotool windowactivate --sync "$main_win" >/dev/null 2>&1 || true
    sleep 0.5
    key_to_window "$main_win" alt+c
    sleep 0.6
    key_to_window "" s
    sleep 2

    cfg_win="$(find_configuration_window || true)"
    if [ -n "$cfg_win" ]; then
        gui_log "GUI fallback: opened Configuration window $cfg_win by keyboard S."
        printf '%s\n' "$cfg_win"
        return 0
    fi

    gui_log "GUI fallback warning: could not open Configuration window."
    return 1
}

apply_gateway_api_gui_settings() {
    set +e

    if ! have_xdotool; then
        echo "GUI fallback warning: xdotool not installed; cannot automate Gateway API GUI."
        echo "Install it in the Gateway image, e.g. apt-get install -y xdotool."
        return 0
    fi

    echo "GUI fallback: attempting API settings automation..."

    local cfg_win=""
    cfg_win="$(open_gateway_configuration_window | tail -n 1)"

    if ! echo "$cfg_win" | grep -Eq '^[0-9]+$'; then
        echo "GUI fallback warning: invalid Configuration window id: [$cfg_win]"
        return 0
    fi

    echo "GUI fallback: using Configuration window id $cfg_win"

    xdotool windowactivate --sync "$cfg_win" >/dev/null 2>&1 || true
    sleep 1

    echo "GUI fallback: selecting API -> Settings section."
    click_window_rel "$cfg_win" "$API_SETTINGS_TREE_X" "$API_SETTINGS_TREE_Y"
    sleep 1

    scroll_api_settings_to_bottom "$cfg_win"

    echo "GUI fallback: clicking 'Allow connections from localhost only' checkbox once."
    click_window_rel "$cfg_win" "$LOCALHOST_ONLY_CHECK_X" "$LOCALHOST_ONLY_CHECK_Y"
    sleep 0.8

    if [ -n "$BOT_TRUSTED_IP" ]; then
        echo "GUI fallback: adding trusted IP $BOT_TRUSTED_IP through GUI."

        click_window_rel "$cfg_win" "$TRUSTED_CREATE_X" "$TRUSTED_CREATE_Y"
        sleep 1

        xdotool type --delay 25 "$BOT_TRUSTED_IP" >/dev/null 2>&1 || true
        sleep 0.3
        key_to_window "" Return
        sleep 1
    else
        echo "GUI fallback: skipping Trusted IP GUI add because BOT_TRUSTED_IP is empty."
    fi

    echo "GUI fallback: applying API settings."
    click_window_rel "$cfg_win" "$APPLY_X" "$APPLY_Y"
    sleep 1
    click_window_rel "$cfg_win" "$OK_X" "$OK_Y"
    sleep 5

    echo "GUI fallback: API settings automation complete."
    return 0
}

echo "Starting IB Gateway via IBC..."
export TWS_MAJOR_VRSN=1019
export TWS_PATH=/root/Jts
export IBC_PATH=/opt/ibc

/opt/ibc/gatewaystart.sh -inline < /dev/null &
IBC_PID=$!

start_ssl_reconnect_watcher

echo "Waiting for Gateway to initialize on port $API_PORT..."
python3 /app/wait_for_gateway.py --port "$API_PORT" --timeout 300

if [ -n "${SSL_WATCHER_PID:-}" ]; then
    kill "$SSL_WATCHER_PID" >/dev/null 2>&1 || true
fi

echo "Gateway port is open. Running GUI API settings fallback..."

sleep 5
apply_gateway_api_gui_settings

echo "Final /root/Jts/jts.ini API-related lines:"
grep -nE "ApiOnly|TrustedIPs|ReadOnlyApi|OverrideTwsApiPort|Bypass" /root/Jts/jts.ini 2>/dev/null || true

echo "Gateway is ready after GUI fallback! Waiting on IBC process to keep container alive..."

wait "$IBC_PID"