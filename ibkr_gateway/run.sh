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

# Extract the first non-localhost exact IPv4 trusted IP for GUI entry.
# Do not use CIDR here; the IBKR GUI trusted-IP field expects explicit IPs.
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
    # VNC is intended ONLY for temporary private-network troubleshooting and IB Gateway GUI access.
    echo "Starting x11vnc on port $VNC_PORT..."
    x11vnc -display :99 -forever -nopw -bg -rfbport "$VNC_PORT" &
fi

# ---------------------------------------------------------------------------
# GUI fallback automation
#
# Purpose:
#   IB Gateway 1019 is not persisting these GUI settings across add-on restarts:
#     - SSL reconnect prompt
#     - API → Settings → Allow connections from localhost only
#     - API → Settings → Trusted IPs
#
# This block uses the virtual display every boot, like the final V6-style
# workaround: change the GUI during startup rather than relying on persistence.
#
# Coordinates are tuned for Xvfb 1024x768. They are intentionally easy to tune.
# ---------------------------------------------------------------------------

SSL_BUTTON_X="${SSL_BUTTON_X:-455}"
SSL_BUTTON_Y="${SSL_BUTTON_Y:-452}"

CONFIGURE_MENU_X="${CONFIGURE_MENU_X:-105}"
CONFIGURE_MENU_Y="${CONFIGURE_MENU_Y:-14}"
CONFIGURE_SETTINGS_X="${CONFIGURE_SETTINGS_X:-105}"
CONFIGURE_SETTINGS_Y="${CONFIGURE_SETTINGS_Y:-42}"

API_TREE_X="${API_TREE_X:-70}"
API_TREE_Y="${API_TREE_Y:-165}"

RIGHT_PANE_X="${RIGHT_PANE_X:-760}"
RIGHT_PANE_Y="${RIGHT_PANE_Y:-250}"

LOCALHOST_ONLY_CHECK_X="${LOCALHOST_ONLY_CHECK_X:-80}"
LOCALHOST_ONLY_CHECK_Y="${LOCALHOST_ONLY_CHECK_Y:-535}"

TRUSTED_CREATE_X="${TRUSTED_CREATE_X:-820}"
TRUSTED_CREATE_Y="${TRUSTED_CREATE_Y:-560}"

APPLY_X="${APPLY_X:-225}"
APPLY_Y="${APPLY_Y:-585}"
OK_X="${OK_X:-70}"
OK_Y="${OK_Y:-585}"

have_xdotool() {
    command -v xdotool >/dev/null 2>&1
}

start_ssl_reconnect_watcher() {
    (
        set +e

        if ! have_xdotool; then
            echo "GUI fallback warning: xdotool not installed; cannot auto-click SSL prompt."
            exit 0
        fi

        echo "Starting SSL reconnect GUI watcher..."

        # The SSL prompt button is normally focused, so Enter often works.
        # The coordinate click is a fallback for the visible button.
        for i in $(seq 1 150); do
            xdotool key Return >/dev/null 2>&1 || true
            xdotool mousemove "$SSL_BUTTON_X" "$SSL_BUTTON_Y" click 1 >/dev/null 2>&1 || true
            sleep 2
        done

        echo "SSL reconnect GUI watcher finished."
    ) &
    SSL_WATCHER_PID=$!
}

find_window_by_name() {
    local pattern="$1"
    xdotool search --onlyvisible --name "$pattern" 2>/dev/null | tail -n 1 || true
}

click_window_rel() {
    local win="$1"
    local x="$2"
    local y="$3"
    xdotool mousemove --window "$win" "$x" "$y" click 1 >/dev/null 2>&1 || true
}

open_gateway_configuration_window() {
    local main_win=""
    local cfg_win=""

    main_win="$(find_window_by_name "IBKR GATEWAY")"

    if [ -z "$main_win" ]; then
        main_win="$(find_window_by_name "Gateway")"
    fi

    if [ -z "$main_win" ]; then
        echo "GUI fallback warning: could not find IBKR Gateway main window."
        return 1
    fi

    echo "GUI fallback: activating Gateway window $main_win"
    xdotool windowactivate "$main_win" >/dev/null 2>&1 || true
    sleep 1

    # First try keyboard menu navigation.
    xdotool key --window "$main_win" alt+c >/dev/null 2>&1 || true
    sleep 0.4
    xdotool key Return >/dev/null 2>&1 || true
    sleep 2

    cfg_win="$(find_window_by_name "Configuration")"
    if [ -n "$cfg_win" ]; then
        echo "GUI fallback: opened Configuration window $cfg_win by keyboard."
        echo "$cfg_win"
        return 0
    fi

    # Fallback: click Configure menu, then first menu item.
    echo "GUI fallback: keyboard open failed; trying menu coordinates."
    click_window_rel "$main_win" "$CONFIGURE_MENU_X" "$CONFIGURE_MENU_Y"
    sleep 0.4
    click_window_rel "$main_win" "$CONFIGURE_SETTINGS_X" "$CONFIGURE_SETTINGS_Y"
    sleep 2

    cfg_win="$(find_window_by_name "Configuration")"
    if [ -n "$cfg_win" ]; then
        echo "GUI fallback: opened Configuration window $cfg_win by mouse."
        echo "$cfg_win"
        return 0
    fi

    echo "GUI fallback warning: could not open Configuration window."
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
    cfg_win="$(open_gateway_configuration_window)"

    if [ -z "$cfg_win" ]; then
        echo "GUI fallback warning: no Configuration window available."
        return 0
    fi

    xdotool windowactivate "$cfg_win" >/dev/null 2>&1 || true
    sleep 1

    # Click API in the left tree.
    echo "GUI fallback: selecting API section."
    click_window_rel "$cfg_win" "$API_TREE_X" "$API_TREE_Y"
    sleep 1

    # Click right pane, then scroll/page to bottom where localhost-only lives.
    click_window_rel "$cfg_win" "$RIGHT_PANE_X" "$RIGHT_PANE_Y"
    sleep 0.2
    xdotool key --window "$cfg_win" End >/dev/null 2>&1 || true
    sleep 1

    # Important: Gateway is currently defaulting this checked every boot.
    # Click once to uncheck.
    echo "GUI fallback: clicking 'Allow connections from localhost only' checkbox once."
    click_window_rel "$cfg_win" "$LOCALHOST_ONLY_CHECK_X" "$LOCALHOST_ONLY_CHECK_Y"
    sleep 0.5

    if [ -n "$BOT_TRUSTED_IP" ]; then
        echo "GUI fallback: adding trusted IP $BOT_TRUSTED_IP through GUI."

        click_window_rel "$cfg_win" "$TRUSTED_CREATE_X" "$TRUSTED_CREATE_Y"
        sleep 1

        # The Create dialog should focus its text field.
        xdotool type --delay 25 "$BOT_TRUSTED_IP" >/dev/null 2>&1 || true
        sleep 0.3
        xdotool key Return >/dev/null 2>&1 || true
        sleep 1
    else
        echo "GUI fallback: skipping Trusted IP GUI add because BOT_TRUSTED_IP is empty."
    fi

    echo "GUI fallback: applying API settings."
    click_window_rel "$cfg_win" "$APPLY_X" "$APPLY_Y"
    sleep 1
    click_window_rel "$cfg_win" "$OK_X" "$OK_Y"
    sleep 2

    echo "GUI fallback: API settings automation complete."
    return 0
}

echo "Starting IB Gateway via IBC..."
export TWS_MAJOR_VRSN=1019
export TWS_PATH=/root/Jts
export IBC_PATH=/opt/ibc

# Run IBC in the background.
/opt/ibc/gatewaystart.sh -inline < /dev/null &
IBC_PID=$!

# Start SSL prompt handler immediately because the SSL dialog can block API readiness.
start_ssl_reconnect_watcher

echo "Waiting for Gateway to initialize on port $API_PORT..."
python3 /app/wait_for_gateway.py --port "$API_PORT" --timeout 300

# Stop SSL watcher after the port is open.
if [ -n "${SSL_WATCHER_PID:-}" ]; then
    kill "$SSL_WATCHER_PID" >/dev/null 2>&1 || true
fi

echo "Gateway port is open. Running GUI API settings fallback..."

# Give Gateway UI a moment to settle before opening configuration.
sleep 5
apply_gateway_api_gui_settings

echo "Final /root/Jts/jts.ini API-related lines:"
grep -nE "ApiOnly|TrustedIPs|ReadOnlyApi|OverrideTwsApiPort|Bypass" /root/Jts/jts.ini 2>/dev/null || true

echo "Gateway is ready after GUI fallback! Waiting on IBC process to keep container alive..."

# If the IBC process dies, the add-on should exit instead of silently tailing forever.
wait $IBC_PID