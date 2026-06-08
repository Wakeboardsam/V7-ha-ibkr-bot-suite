#!/bin/bash
set -e

echo "Starting V7_tqqq_bot runtime..."
echo "Parsing Home Assistant options..."

if [ -f /data/options.json ]; then
    IBKR_ACCOUNT_ID=$(jq -r '.ibkr_account_id // "DU1234567"' /data/options.json)
    MASK_LOGS=$(jq -r '.mask_account_ids_in_logs // true' /data/options.json)
    GATEWAY_HOST=$(jq -r '.gateway_host // "ibkr_gateway"' /data/options.json)
    GATEWAY_PORT=$(jq -r '.gateway_port // 7497' /data/options.json)

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
    echo "Connecting to Gateway at: ${GATEWAY_HOST}:${GATEWAY_PORT}"
else
    echo "Warning: /data/options.json not found. This is normal during local testing outside HA."
fi

echo "Starting the Python bot runtime..."
exec python -m main
