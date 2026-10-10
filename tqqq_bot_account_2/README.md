# TQQQ Bot Account 2 (v7)

Bundled IBKR Gateway and TQQQ grid-trading bot for a second, independent IBKR account and its own Google Sheet. It is identical to the `tqqq_bot` add-on, except that it does not start automatically when Home Assistant boots.

**Warning: this add-on can trade live.** A new install starts in Paper with "Watch only" and "Gateway read-only" on, so it cannot trade until you turn those off.

The full description of the architecture, trading behavior, configuration options, account isolation and development workflow is in the repository's [main README](https://github.com/Wakeboardsam/V7-ha-ibkr-bot-suite/blob/main/README.md). This page covers only what an operator needs when configuring this add-on in Home Assistant.

## What runs inside

One instance runs one IBKR Gateway session (through IBC), an optional VNC server and one Python bot, all in this container. The bot connects to its own Gateway on `127.0.0.1`. Startup order: settings check, Xvfb, VNC (optional), IBC and Gateway, wait for the local API port, then the bot.

## Configuration page

The Configuration tab groups the options into sections, each with a plain-English name and description:

- **Account and trading**: Trading mode (paper or live), IBKR account ID, username and password, Watch only, Gateway read-only.
- **Google Sheet**: Sheet ID and the service-account key. Paste the JSON key as a **single line**; multi-line JSON may not round-trip through the Home Assistant password field.
- **Strategy and safeguards**: Bridge Anchor, price offset, trim limit, share-mismatch behavior, spread limit.
- **Time zone and schedule**: a US time zone, the nightly pause and the Gateway restarts. Times are 24-hour `HH:MM`.
- **Phone notifications**: one switch per alert, all off by default.
- **Advanced and troubleshooting**: API port, client ID, intervals, timeouts, log masking and VNC.

**Upgrading from 0.1.53 or earlier.** On its first start, the add-on moves your saved settings into the new sections and restarts once. If a value cannot be moved, everything else still is, and the add-on stops in Watch only before connecting to IBKR; the log names the value to check. If the log says not to save the Configuration page yet, start the add-on again instead.

**Switching between paper and live.** Stop the add-on, then change Trading mode, the account ID, the username and the password together, save, and start it. Paper uses IBKR's practice account, which has its own account ID (starting with `DU`) and usually its own username.

Never commit real values. Use `DU1234567`, `placeholder_user`, `placeholder_password` and `your_google_sheet_id_here`.

## Gateway settings persistence

Gateway runs with its active settings under `/root/Jts`, and selected settings are saved to and restored from `/data/ibgateway/persist` across restarts. This keeps first-run choices such as the SSL reconnect prompt. VNC may be needed once to click that prompt; after one successful click and a restart it should not recur.

## Watch only (dry run)

Watch only is on by default for a new install.

- It connects to the real Gateway and reads real broker, account and Sheet state.
- It places, cancels, modifies and transmits no orders.
- It is not paper trading and does not simulate fills or create fake order IDs.
- It logs `DRY RUN MODE ENABLED — NO ORDERS WILL BE PLACED, CANCELLED, OR MODIFIED` at startup.

To trade, turn off both Watch only and Gateway read-only.

## Logging

Normal IBKR market-data farm connection messages are logged as `INFO` or `WARNING`. Order failures, API failures that prevent trading, and account-scoping failures are logged as `ERROR` or `CRITICAL`. Account IDs are masked (`DU1****567`) unless "Hide account IDs in logs" is turned off; do not share logs if it is.

## VNC

VNC is for troubleshooting and manual login or two-factor approval only.

1. Turn on "Gateway screen (VNC)" under Advanced and troubleshooting.
2. The VNC server has **no password**. Port `5900` is unmapped by default; map it in the add-on's Network settings only if you need it, only on a trusted network, and use a different port for each add-on.
3. Turn VNC off and remove the port mapping afterwards.
