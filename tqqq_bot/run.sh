#!/bin/bash
set -e

echo "tqqq_bot scaffold installed; v6 runtime port pending."
echo "Parsing Home Assistant options..."

if [ -f /data/options.json ]; then
    IBKR_ACCOUNT_ID=$(jq -r '.ibkr_account_id // "DU1234567"' /data/options.json)
    MASK_LOGS=$(jq -r '.mask_account_ids_in_logs // true' /data/options.json)

    if [ "$MASK_LOGS" = "true" ]; then
        # Mask the account ID (e.g. DU1234567 -> DU1****567)
        # Keep the first 3 chars and the last 3 chars. Fill middle with ****.
        # This is a simple bash regex substitution approach.
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
        echo "Configured IBKR account: ${IBKR_ACCOUNT_ID}"
    fi
else
    echo "Warning: /data/options.json not found. This is normal during local testing outside HA."
fi

echo "Boot validation complete. Bot runtime is NOT starting yet."
echo "Sleeping indefinitely to keep HA add-on running safely..."

# Sleep forever so HA keeps the add-on running
tail -f /dev/null
