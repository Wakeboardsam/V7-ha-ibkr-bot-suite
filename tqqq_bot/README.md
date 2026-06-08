# TQQQ Bot (v7)

The `tqqq_bot` add-on is a Home Assistant wrapper for the V6 TQQQ Grid Strategy. It automates trading using Interactive Brokers (IBKR).

**Warning: This add-on is capable of live trading. Ensure `paper_trading` is `true` while testing.**

## Architecture

This add-on connects to the shared `ibkr_gateway` add-on for API access. The bot itself contains only the Python runtime. **It requires `ibkr_gateway` to be installed, running, and logged into Interactive Brokers.**

**Important Policy:**
* One `tqqq_bot` instance = One IBKR Account = One Google Sheet.
* If you have multiple accounts, you must specify the exact `ibkr_account_id` in the add-on configuration.

## Required Configuration

You must configure the following options in the Home Assistant UI before starting the bot:

* **gateway_host**: The hostname of the gateway. Default is `ibkr_gateway` (the shared add-on).
* **gateway_port**: The port to connect to. Typically `7497` for Paper trading or `7496` for Live trading.
* **ibkr_account_id**: The IBKR account ID (e.g. `DU1234567`). **Required** if multiple accounts exist on the gateway.
* **google_sheet_id**: The ID of the Google Sheet containing the Grid Strategy (found in the URL).
* **google_credentials_json**: A raw JSON string containing the Google Service Account credentials. **DO NOT COMMIT THIS TO THE REPOSITORY.**

*Note: Logs will mask your account ID by default (e.g. `DU1****567`). You can disable this by setting `mask_account_ids_in_logs: false`, but be careful when sharing logs.*