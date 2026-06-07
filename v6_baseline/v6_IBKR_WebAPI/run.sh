#!/bin/bash
echo "Parsing Home Assistant options..."
ENABLE_VNC=$(jq -r '.enable_vnc // false' /data/options.json)
IBKR_USER=$(jq -r '.ibkr_username // empty' /data/options.json)
IBKR_PASS=$(jq -r '.ibkr_password // empty' /data/options.json)
export IBKR_PORT=$(jq -r '.ibkr_port // 7497' /data/options.json)
PAPER_FLAG=$(jq -r '.paper_trading' /data/options.json)
TRADING_MODE="paper"
if [ "$PAPER_FLAG" = "false" ]; then
TRADING_MODE="live"
fi
echo "Generating IBC config..."
mkdir -p /root/ibc
cat <<EOF > /root/ibc/config.ini
IbLoginId=${IBKR_USER}
IbPassword=${IBKR_PASS}
TradingMode=${TRADING_MODE}
IbDir=/root/Jts
ReadOnlyApi=no
OverrideTwsApiPort=${IBKR_PORT}
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
    echo "Starting x11vnc..."
    x11vnc -display :99 -forever -nopw -bg &
fi

echo "Starting IB Gateway via IBC..."
export TWS_MAJOR_VRSN=1019
export TWS_PATH=/root/Jts
export IBC_PATH=/opt/ibc
/opt/ibc/gatewaystart.sh -inline < /dev/null &
echo "Waiting 30 seconds for Gateway to initialize..."
sleep 30
echo "=== IBC DIAGNOSTIC LOGS ==="
cat /root/ibc/logs/*.txt 2>/dev/null || echo "No IBC logs found."
echo "==========================="
echo "Starting Supervisord to launch Python Bot..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
