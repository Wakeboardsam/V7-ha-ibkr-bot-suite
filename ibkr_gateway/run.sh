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
READONLY_BOOL="false"
if [ "$READONLY_API" = "true" ]; then
    READONLY_VAL="yes"
    READONLY_BOOL="true"
fi

# Persistent Gateway/TWS settings.
#
# Important:
# - /root/Jts is the Gateway install/runtime path inside the image.
# - /data survives Home Assistant add-on restarts.
# - IBC recommends TWS_SETTINGS_PATH for the settings store.
#
# This is intended to make Gateway GUI API settings survive restarts,
# including:
#   - Read-Only API unchecked
#   - Socket port set to API_PORT
#   - localhost-only disabled after you save it once in VNC
#   - trusted IPs saved after you save them once in VNC
TWS_INSTALL_DIR="/root/Jts"
TWS_SETTINGS_DIR="/data/jts"

echo "Preparing persistent Gateway settings directory..."
mkdir -p "$TWS_INSTALL_DIR"
mkdir -p "$TWS_SETTINGS_DIR"

# Keep settings private because IBC config contains login credentials.
umask 077

set_ini_value() {
    local file="$1"
    local key="$2"
    local value="$3"

    mkdir -p "$(dirname "$file")"
    touch "$file"

    if grep -qE "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

echo "Generating IBC config..."
mkdir -p /root/ibc
cat <<EOF > /root/ibc/config.ini
IbLoginId=${IBKR_USERNAME}
IbPassword=${IBKR_PASSWORD}
TradingMode=${TRADING_MODE}

# Use persistent HA add-on storage for Gateway/TWS settings.
# This should keep API GUI changes across Gateway restarts.
IbDir=${TWS_SETTINGS_DIR}

ReadOnlyApi=${READONLY_VAL}
OverrideTwsApiPort=${API_PORT}
AcceptIncomingConnectionAction=accept
AcceptNonBrokerageAccountWarning=yes

# API precaution/dialog bypasses carried forward from V6.
BypassOrderPrecautions=yes
BypassRedirectOrderWarning=yes
AllowBlindTrading=yes

# Save Gateway/TWS settings periodically so VNC-applied API changes persist.
SaveTwsSettingsAt=Every 5 mins

# Best-effort only. IBC documents this as FIX-only for Gateway, but keeping
# it here is harmless and documents the intended trusted API clients.
TrustedTwsApiClientIPs=${TRUSTED_IPS}
EOF

echo "Injecting API bypass and persistent API settings into jts.ini..."

# Write to both possible locations:
# - persistent settings store: /data/jts/jts.ini
# - runtime/install path: /root/Jts/jts.ini
#
# Some keys below are known IBC/Gateway-adjacent settings; some are best-effort
# candidates because IBKR does not clearly document every jts.ini GUI checkbox key.
# The durable fix is primarily the persistent /data/jts settings store.
for JTS_INI in "${TWS_SETTINGS_DIR}/jts.ini" "${TWS_INSTALL_DIR}/jts.ini"; do
    echo "Updating $JTS_INI"

    set_ini_value "$JTS_INI" "BypassOrderPrecautions" "true"
    set_ini_value "$JTS_INI" "BypassRedirectOrderWarning" "true"

    # API behavior.
    set_ini_value "$JTS_INI" "ReadOnlyApi" "$READONLY_BOOL"
    set_ini_value "$JTS_INI" "OverrideTwsApiPort" "$API_PORT"

    # Best-effort candidates for Gateway API remote-client persistence.
    # If Gateway ignores any of these, they are harmless; the persistent settings
    # directory should still preserve the setting once changed through VNC.
    set_ini_value "$JTS_INI" "ApiOnlyLocalhost" "false"
    set_ini_value "$JTS_INI" "AllowOnlyLocalhost" "false"
    set_ini_value "$JTS_INI" "TrustedTwsApiClientIPs" "$TRUSTED_IPS"
    set_ini_value "$JTS_INI" "TrustedIPs" "$TRUSTED_IPS"
done

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
export TWS_PATH="$TWS_INSTALL_DIR"
export TWS_SETTINGS_PATH="$TWS_SETTINGS_DIR"
export IBC_PATH=/opt/ibc

echo "TWS install path: $TWS_PATH"
echo "TWS settings path: $TWS_SETTINGS_PATH"

# Run IBC in the background.
/opt/ibc/gatewaystart.sh -inline < /dev/null &
IBC_PID=$!

echo "Waiting for Gateway to initialize on port $API_PORT..."
python3 /app/wait_for_gateway.py --port "$API_PORT" --timeout 300

echo "Gateway port is open."

echo "Gateway API setting candidates after startup:"
grep -RniE "localhost|trusted|socket|readonly|api|127\.0\.0\.1|172\.30" "$TWS_SETTINGS_DIR" "$TWS_INSTALL_DIR" 2>/dev/null || true
echo "End Gateway API setting candidates."

echo "Gateway is ready! Waiting on IBC process to keep container alive..."

# If the IBC process dies, the add-on should exit instead of silently tailing forever.
wait $IBC_PID