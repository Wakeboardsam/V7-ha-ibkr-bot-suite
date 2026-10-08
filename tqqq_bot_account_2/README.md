# TQQQ Bot Account 2 (v7)

Bundled IBKR Gateway and TQQQ grid-trading bot for a second, independent IBKR account and its own Google Sheet. It is a runtime copy of the `tqqq_bot` add-on with safer committed defaults.

**Warning: this add-on can trade live. Keep `paper_trading: true` and `trading_mode: paper` while testing, and use `dry_run: true` to validate without placing orders.**

The full description of the architecture, trading behavior, configuration options, account isolation and development workflow is in the repository's [main README](https://github.com/Wakeboardsam/V7-ha-ibkr-bot-suite/blob/main/README.md). This page covers only what an operator needs when configuring this add-on in Home Assistant.

## Safe defaults

This add-on ships with `boot: manual`, `paper_trading: true`, `trading_mode: paper`, `dry_run: true`, `readonly_api: true` and VNC off. These committed defaults are checked by `scripts/validate_account_addons.py`. Changing them in the Home Assistant configuration for your own instance is expected; changing them in the repository is not.

## What runs inside

One instance runs one IBKR Gateway session (through IBC), an optional VNC server and one Python bot, all in this container. The bot connects to the Gateway on `127.0.0.1`; `ibkr_host` is forced to that value. Startup order: Xvfb, VNC (optional), IBC and Gateway, wait for the local API port, then the bot.

## Required configuration

Set these in the add-on configuration; the defaults in `config.yaml` are placeholders.

- `ibkr_username` and `ibkr_password`: IBKR login (password field).
- `ibkr_account_id`: the one account this instance may trade. The bot refuses live operation without it.
- `google_sheet_id` and `google_credentials_json`: the Sheet and its service-account JSON. Provide the JSON as a **single line**; multi-line JSON may not round-trip through the Home Assistant password field.
- `readonly_api` is `true` by default and makes the Gateway API read-only; set it to `false` together with `dry_run: false` to allow orders.
- `paper_trading` and `trading_mode` should agree. The paper API port is `7497`, live is `7496`.

Never commit real values. Use `DU1234567`, `placeholder_user`, `placeholder_password` and `your_google_sheet_id_here`.

## Gateway settings persistence

Gateway runs with its active settings under `/root/Jts`, and selected settings are saved to and restored from `/data/ibgateway/persist` across restarts. This keeps first-run choices such as the SSL reconnect prompt. VNC may be needed once to click that prompt; after one successful click and a restart it should not recur.

## Dry run

`dry_run` is `true` by default for this add-on. Set it to `false` only when you are ready for this instance to place orders.

- It connects to the real Gateway and reads real broker, account and Sheet state.
- It places, cancels, modifies and transmits no orders.
- It is not paper trading and does not simulate fills or create fake order IDs.
- It logs `DRY RUN MODE ENABLED — NO ORDERS WILL BE PLACED, CANCELLED, OR MODIFIED` at startup.

## Logging

Normal IBKR market-data farm connection messages are logged as `INFO` or `WARNING`. Order failures, API failures that prevent trading, and account-scoping failures are logged as `ERROR` or `CRITICAL`. Account IDs are masked (`DU1****567`) unless `mask_account_ids_in_logs` is turned off; do not share logs if it is.

## VNC

VNC is for troubleshooting and manual login or two-factor approval only.

1. Set `enable_vnc: true`.
2. The VNC server has **no password**. Port `5900` is unmapped by default; map it in the add-on's Network settings only if you need it, and only on a trusted network.
3. Turn VNC off and remove the port mapping afterwards.
