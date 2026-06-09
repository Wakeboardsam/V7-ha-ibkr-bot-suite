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

# Build a newline-separated list of all non-localhost IPs to add
EXTRA_TRUSTED_IPS="$(echo "$TRUSTED_IPS" \
    | tr ',' '\n' \
    | sed 's/^ *//;s/ *$//' \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
    | grep -v '^127\.' \
    || true)"

if [ -z "$EXTRA_TRUSTED_IPS" ]; then
    echo "Warning: no non-localhost trusted IPv4 found in trusted_ips."
    echo "For the bot, use something like: trusted_ips: 127.0.0.1,172.30.33.3"
else
    echo "Trusted IPs to add via GUI:"
    echo "$EXTRA_TRUSTED_IPS"
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
    x11vnc -display :99 -forever -nopw -bg -rfbport "$VNC_PORT" -noxdamage -noscr -nowf -cursor arrow &
fi

# ---------------------------------------------------------------------------
# GUI fallback automation
# ---------------------------------------------------------------------------

# SSL dialog — absolute screen coords (dialog appears centred on 1024x768).
SSL_BUTTON_X="${SSL_BUTTON_X:-455}"
SSL_BUTTON_Y="${SSL_BUTTON_Y:-452}"

# Main Gateway menu bar — relative to the Gateway window client area.
# "Configure" menu label sits at roughly x=270 in the 540-wide window.
CONFIGURE_MENU_X="${CONFIGURE_MENU_X:-157}"   # centre of "Configure" label
CONFIGURE_MENU_Y="${CONFIGURE_MENU_Y:-14}"
CONFIGURE_SETTINGS_X="${CONFIGURE_SETTINGS_X:-157}"
CONFIGURE_SETTINGS_Y="${CONFIGURE_SETTINGS_Y:-42}"   # first item "Settings"

# -------------------------------------------------------------------------
# Configuration window coordinates — ALL relative to the cfg window itself.
#
# From the screenshots the Configuration window is ~540 px wide × ~400 px tall
# (client area). The left tree pane is ~220 px wide.
#
# Left tree pane — API subtree items (after the node is expanded):
#   "API"             y ≈ 80   (parent node — we click this to expand)
#   "Settings"        y ≈ 93   (first child)
#   "Precautions"     y ≈ 106  (second child)
#   "News Config"     y ≈ 119  (third child)
#
# Strategy: click the API parent to ensure it is expanded, then use the
# Down-arrow key once to land on "Settings" (first child), which is
# unambiguous and coordinate-independent.
# -------------------------------------------------------------------------
API_TREE_PARENT_X="${API_TREE_PARENT_X:-86}"
API_TREE_PARENT_Y="${API_TREE_PARENT_Y:-80}"

# Right pane — used for focus & scrolling.
RIGHT_PANE_X="${RIGHT_PANE_X:-490}"
RIGHT_PANE_Y="${RIGHT_PANE_Y:-250}"

# Scrollbar drag — top → bottom to reach end of right pane.
API_SCROLLBAR_X="${API_SCROLLBAR_X:-535}"
API_SCROLLBAR_TOP_Y="${API_SCROLLBAR_TOP_Y:-115}"
API_SCROLLBAR_BOTTOM_Y="${API_SCROLLBAR_BOTTOM_Y:-380}"

# -------------------------------------------------------------------------
# Bottom-of-pane coordinates (visible in Image 4 after scrolling).
#
# "Allow connections from localhost only" checkbox:
#   Left edge of right pane ≈ x=340 (window-relative).
#   The checkbox square itself is at approximately x=347, y=393.
#   The label starts at x=360 — we click the checkbox square, not the label,
#   to avoid accidentally hitting a nearby control.
#
# Trusted IPs list and buttons (Image 4):
#   "Create" button:  x≈609, y≈423  (window-relative)
#   "Edit"   button:  x≈609, y≈440
#   "Delete" button:  x≈609, y≈457
#
# OK / Apply / Cancel bar at the very bottom of the window:
#   "OK"     x≈337, y≈514
#   "Apply"  x≈388, y≈514
#   "Cancel" x≈439, y≈514
# -------------------------------------------------------------------------
LOCALHOST_ONLY_CHECK_X="${LOCALHOST_ONLY_CHECK_X:-347}"
LOCALHOST_ONLY_CHECK_Y="${LOCALHOST_ONLY_CHECK_Y:-393}"

TRUSTED_CREATE_X="${TRUSTED_CREATE_X:-609}"
TRUSTED_CREATE_Y="${TRUSTED_CREATE_Y:-423}"

APPLY_X="${APPLY_X:-388}"
APPLY_Y="${APPLY_Y:-514}"

OK_X="${OK_X:-337}"
OK_Y="${OK_Y:-514}"

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

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
    [ -n "$win" ] && { echo "$win"; return 0; }
    win="$(find_window_by_name "Gateway")"
    [ -n "$win" ] && { echo "$win"; return 0; }
    return 1
}

find_configuration_window() {
    local win=""
    win="$(find_window_by_name "Configuration")"
    [ -n "$win" ] && { echo "$win"; return 0; }
    win="$(find_window_by_name "Trader Workstation Configuration")"
    [ -n "$win" ] && { echo "$win"; return 0; }
    return 1
}

find_ssl_window() {
    local win=""
    win="$(find_window_by_name "USE SSL")"
    [ -n "$win" ] && { echo "$win"; return 0; }
    win="$(find_window_by_name "SSL")"
    [ -n "$win" ] && { echo "$win"; return 0; }
    return 1
}

# Click at coordinates relative to a window's top-left corner.
click_window_rel() {
    local win="$1" x="$2" y="$3"
    [ -z "$win" ] && { gui_log "click_window_rel: empty window id"; return 0; }
    xdotool mousemove --window "$win" "$x" "$y" >/dev/null 2>&1 || true
    sleep 0.15
    xdotool click 1 >/dev/null 2>&1 || true
}

drag_window_rel() {
    local win="$1" x1="$2" y1="$3" x2="$4" y2="$5"
    [ -z "$win" ] && { gui_log "drag_window_rel: empty window id"; return 0; }
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
    local win="$1"; shift
    if [ -n "$win" ]; then
        xdotool key --window "$win" --clearmodifiers "$@" >/dev/null 2>&1 || true
    else
        xdotool key --clearmodifiers "$@" >/dev/null 2>&1 || true
    fi
}

scroll_down_window() {
    local win="$1" x="$2" y="$3"
    xdotool mousemove --window "$win" "$x" "$y" >/dev/null 2>&1 || true
    sleep 0.2
    for i in $(seq 1 40); do
        xdotool click 5 >/dev/null 2>&1 || true
        sleep 0.05
    done
}

scroll_api_settings_to_bottom() {
    local win="$1"
    echo "GUI fallback: scrolling API settings pane to bottom."

    # Give the right pane keyboard focus first.
    click_window_rel "$win" "$RIGHT_PANE_X" "$RIGHT_PANE_Y"
    sleep 0.3

    key_to_window "$win" End
    sleep 0.3

    for i in $(seq 1 8); do
        key_to_window "$win" Page_Down
        sleep 0.08
    done

    # Mouse-wheel scroll for good measure.
    scroll_down_window "$win" "$RIGHT_PANE_X" "$RIGHT_PANE_Y"
    sleep 0.3

    # Drag the scrollbar thumb all the way to the bottom.
    drag_window_rel "$win" \
        "$API_SCROLLBAR_X" "$API_SCROLLBAR_TOP_Y" \
        "$API_SCROLLBAR_X" "$API_SCROLLBAR_BOTTOM_Y"
    sleep 0.5

    scroll_down_window "$win" "$RIGHT_PANE_X" "$RIGHT_PANE_Y"
    sleep 0.5
}

# ---------------------------------------------------------------------------
# select_api_settings_tree
#
# Reliable strategy that avoids the Precautions/Settings ambiguity:
#   1. Click the "API" parent node to ensure it is selected & expanded.
#   2. Press the Right arrow to open the subtree if it was collapsed.
#   3. Press the Down arrow exactly ONCE — this lands on "Settings",
#      the first child, regardless of pixel-level y-position.
# ---------------------------------------------------------------------------
select_api_settings_tree() {
    local win="$1"
    echo "GUI fallback: navigating tree to API -> Settings."

    # Click the API parent node.
    click_window_rel "$win" "$API_TREE_PARENT_X" "$API_TREE_PARENT_Y"
    sleep 0.6

    # Expand the node (Right arrow is a no-op if already expanded).
    key_to_window "$win" Right
    sleep 0.4

    # Move down once — lands on "Settings" (first child of API).
    key_to_window "$win" Down
    sleep 0.6

    echo "GUI fallback: API -> Settings should now be active."
}

# ---------------------------------------------------------------------------
# ensure_localhost_only_unchecked
#
# The checkbox must end up UNCHECKED.  Because we cannot read its pixel state
# without imagemagick/tesseract, we use a two-pass approach:
#   Pass 1 – click the checkbox once, then Apply.
#   Read jts.ini: if LocalServerPort or AllowedHosts indicates the setting is
#   now open (localhost-only OFF), we're done.
#   Pass 2 – if jts.ini still shows localhost-only ON, click again + Apply.
#
# jts.ini key written by Gateway when localhost-only is ENABLED:
#   LocalServerPort=...  AND the TrustedIPs line will be absent or empty.
# When localhost-only is DISABLED the Gateway writes AllowedHosts= with IPs.
#
# Because jts.ini is only flushed on Apply/OK we apply after each toggle.
# ---------------------------------------------------------------------------
ensure_localhost_only_unchecked() {
    local win="$1"
    local max_passes=3
    local pass=0

    while [ $pass -lt $max_passes ]; do
        pass=$((pass + 1))
        echo "GUI fallback: localhost-only checkbox — pass $pass."

        # Click the checkbox.
        click_window_rel "$win" "$LOCALHOST_ONLY_CHECK_X" "$LOCALHOST_ONLY_CHECK_Y"
        sleep 0.5

        # Apply so jts.ini is written.
        click_window_rel "$win" "$APPLY_X" "$APPLY_Y"
        sleep 2.0

        # Re-open Settings pane (Apply may deselect tree node on some versions).
        select_api_settings_tree "$win"
        scroll_api_settings_to_bottom "$win"

        # Check jts.ini — Gateway writes "LocalServerOnly=1" when the box is checked.
        # When unchecked the key is absent or set to 0.
        local ini_val
        ini_val=$(grep -i "LocalServerOnly" /root/Jts/jts.ini 2>/dev/null || true)
        echo "GUI fallback: jts.ini LocalServerOnly line: '${ini_val}'"

        if echo "$ini_val" | grep -qi "LocalServerOnly=1"; then
            echo "GUI fallback: still checked after pass $pass — clicking again."
            continue
        else
            echo "GUI fallback: localhost-only is now OFF (unchecked). Done."
            return 0
        fi
    done

    echo "GUI fallback warning: could not confirm localhost-only unchecked after $max_passes passes."
}

# ---------------------------------------------------------------------------
# add_trusted_ips  — loops over all non-localhost IPs from TRUSTED_IPS
# ---------------------------------------------------------------------------
add_trusted_ips() {
    local win="$1"

    if [ -z "$EXTRA_TRUSTED_IPS" ]; then
        echo "GUI fallback: no extra trusted IPs to add."
        return 0
    fi

    echo "$EXTRA_TRUSTED_IPS" | while IFS= read -r ip; do
        [ -z "$ip" ] && continue
        echo "GUI fallback: adding trusted IP '$ip'."
        click_window_rel "$win" "$TRUSTED_CREATE_X" "$TRUSTED_CREATE_Y"
        sleep 1.0
        xdotool type --delay 30 "$ip" >/dev/null 2>&1 || true
        sleep 0.3
        key_to_window "" Return
        sleep 0.8
    done
}

# ---------------------------------------------------------------------------
# SSL reconnect watcher (background)
# ---------------------------------------------------------------------------
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
                echo "GUI fallback: SSL dialog found; accepting."
                xdotool windowactivate --sync "$ssl_win" >/dev/null 2>&1 || true
                sleep 0.2
                key_to_window "$ssl_win" Return
                sleep 0.5
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

# ---------------------------------------------------------------------------
# open_gateway_configuration_window
# ---------------------------------------------------------------------------
open_gateway_configuration_window() {
    local main_win="" cfg_win=""

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

    # Dismiss any stray popups.
    xdotool key Escape >/dev/null 2>&1 || true
    sleep 0.3

    # --- Attempt 1: mouse click on Configure menu ---
    gui_log "GUI fallback: opening Configure -> Settings via mouse."
    click_window_rel "$main_win" "$CONFIGURE_MENU_X" "$CONFIGURE_MENU_Y"
    sleep 0.8
    click_window_rel "$main_win" "$CONFIGURE_SETTINGS_X" "$CONFIGURE_SETTINGS_Y"
    sleep 2

    cfg_win="$(find_configuration_window || true)"
    if [ -n "$cfg_win" ]; then
        gui_log "GUI fallback: opened Configuration window $cfg_win via mouse."
        printf '%s\n' "$cfg_win"
        return 0
    fi

    # --- Attempt 2: Alt+C → Return ---
    gui_log "GUI fallback: mouse failed; trying Alt+C then Return."
    xdotool windowactivate --sync "$main_win" >/dev/null 2>&1 || true
    sleep 0.5
    key_to_window "$main_win" alt+c
    sleep 0.6
    key_to_window "" Return
    sleep 2

    cfg_win="$(find_configuration_window || true)"
    if [ -n "$cfg_win" ]; then
        gui_log "GUI fallback: opened Configuration window $cfg_win via Alt+C Return."
        printf '%s\n' "$cfg_win"
        return 0
    fi

    # --- Attempt 3: Alt+C → S ---
    gui_log "GUI fallback: trying Alt+C then S."
    xdotool windowactivate --sync "$main_win" >/dev/null 2>&1 || true
    sleep 0.5
    key_to_window "$main_win" alt+c
    sleep 0.6
    key_to_window "" s
    sleep 2

    cfg_win="$(find_configuration_window || true)"
    if [ -n "$cfg_win" ]; then
        gui_log "GUI fallback: opened Configuration window $cfg_win via Alt+C S."
        printf '%s\n' "$cfg_win"
        return 0
    fi

    gui_log "GUI fallback warning: could not open Configuration window."
    return 1
}

# ---------------------------------------------------------------------------
# apply_gateway_api_gui_settings  — main orchestration function
# ---------------------------------------------------------------------------
apply_gateway_api_gui_settings() {
    set +e

    if ! have_xdotool; then
        echo "GUI fallback warning: xdotool not installed."
        return 0
    fi

    echo "GUI fallback: starting API settings automation..."

    local cfg_win=""
    cfg_win="$(open_gateway_configuration_window | tail -n 1)"

    if ! echo "$cfg_win" | grep -Eq '^[0-9]+$'; then
        echo "GUI fallback warning: invalid Configuration window id: [$cfg_win]"
        return 0
    fi

    echo "GUI fallback: Configuration window id = $cfg_win"
    xdotool windowactivate --sync "$cfg_win" >/dev/null 2>&1 || true
    sleep 1

    # Step 1: Navigate to API -> Settings via keyboard (avoids Precautions misclick).
    select_api_settings_tree "$cfg_win"

    # Step 2: Scroll the right pane to the bottom to reveal the localhost checkbox.
    scroll_api_settings_to_bottom "$cfg_win"

    # Step 3: Ensure "Allow connections from localhost only" is UNCHECKED.
    #         This also calls Apply after each toggle so we can verify via jts.ini.
    ensure_localhost_only_unchecked "$cfg_win"

    # Step 4: After the last ensure_localhost_only_unchecked call the settings
    #         pane is still open (we re-opened it inside the function).
    #         Add all extra trusted IPs.
    add_trusted_ips "$cfg_win"

    # Step 5: Final Apply + OK.
    echo "GUI fallback: final Apply + OK."
    click_window_rel "$cfg_win" "$APPLY_X" "$APPLY_Y"
    sleep 1
    click_window_rel "$cfg_win" "$OK_X" "$OK_Y"
    sleep 5

    echo "GUI fallback: API settings automation complete."
    return 0
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
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
grep -nE "ApiOnly|TrustedIPs|LocalServerOnly|ReadOnlyApi|OverrideTwsApiPort|Bypass|AllowedHosts" \
    /root/Jts/jts.ini 2>/dev/null || true

echo "Gateway is ready. Waiting on IBC process..."
wait "$IBC_PID"
