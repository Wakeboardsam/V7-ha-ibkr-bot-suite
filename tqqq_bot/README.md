# TQQQ Bot (v7)

The `tqqq_bot` add-on is the primary Phase 1 bundled Gateway + trading bot target for the v7 HA IBKR Bot Suite.

It is based on the proven v6 TQQQ Grid Strategy and is intended to preserve v6 strategy behavior while adding Home Assistant packaging and account-scoping safety.

**Warning: This add-on is capable of live trading. Keep `paper_trading: true` while testing.**

## Phase 1 Architecture Target

The intended Phase 1 bundled model is:

```text
one bundled add-on instance = one IBKR Gateway session = one trading bot = one IBKR account = one Google Sheet
```

For Phase 1, `tqqq_bot` is the first bundled implementation target.

The target bundled add-on contains:

1. IBKR Gateway runtime
2. IBC / Gateway startup configuration
3. optional VNC troubleshooting access
4. Python trading bot runtime
5. IBKR account configuration
6. Google Sheet configuration
7. account ID masking and account-scoping guardrails

The expected target startup sequence is:

```text
run.sh
  -> parse Home Assistant options
  -> generate IBC / Gateway config
  -> start Xvfb
  -> optionally start VNC
  -> start IBKR Gateway through IBC
  -> wait for local Gateway port
  -> start Python trading bot
```

In the target bundled architecture, the bot should connect to the Gateway inside the same add-on:

```yaml
ibkr_host: "127.0.0.1"
ibkr_port: 7497
```

The current implementation may be staged across PRs. Do not assume the bundled runtime is fully implemented until a code PR explicitly implements it.

## Shared Gateway Status

The separate `ibkr_gateway` add-on remains in the repository as optional/experimental shared-Gateway mode.

Shared `ibkr_gateway` mode is no longer the recommended primary Phase 1 path. The recommended Phase 1 path is bundled Gateway + bot per account, starting with this `tqqq_bot` add-on.

## Strategy Scope

Preserve v6 strategy behavior unless a later task explicitly requires a safety or packaging change.

Keep:

- existing grid logic
- existing Bridge Anchor behavior
- TQQQ as the only traded symbol for now
- existing Google Sheets behavior unless safe account separation requires adjustment

Do not rewrite the trading strategy in bundled-architecture PRs.

## Account-Scoping Policy

One `tqqq_bot` bundled instance must operate against one configured IBKR account and one configured Google Sheet.

If multiple IBKR accounts are visible and no `ibkr_account_id` is configured, the bot should warn loudly or refuse unsafe trading.

When `ibkr_account_id` is configured, the bot must:

- place orders explicitly into the configured account
- read only broker state for the configured account when possible
- process only fills/executions for the configured account when account data is available
- mask account IDs in logs and UI output by default

Example masked account format:

```text
DU1****567
```

## Target Placeholder Configuration

Use placeholder values only in source-controlled examples.

```yaml
active_broker: "ibkr"
paper_trading: true
ibkr_host: "127.0.0.1"
ibkr_port: 7497
ibkr_client_id: 1
ibkr_account_id: "DU1234567"
google_sheet_id: "your_google_sheet_id_here"
google_credentials_json: ""
poll_interval_seconds: 60
heartbeat_interval_seconds: 60
health_log_interval_seconds: 300
anchor_buy_offset: 1.5
share_mismatch_mode: "halt"
max_spread_pct: 0.5
enable_bridge_anchor: true
bridge_max_auto_trim_shares: 5
maintenance_enabled: true
maintenance_start_local: "23:44"
maintenance_end_local: "00:00"
maintenance_cancel_open_orders: true
mask_account_ids_in_logs: true
enable_vnc: false
vnc_port: 5900
```

Gateway/IBC-related fields may also be exposed as needed:

```yaml
ibkr_username: "placeholder_user"
ibkr_password: "placeholder_password"
trading_mode: "paper"
readonly_api: false
```

Password fields should use Home Assistant password schema fields.

## Security

Never commit real credentials, real account IDs, OAuth certs, private keys, API tokens, Google service-account files, Google Sheet IDs, `.env` secrets, token caches, or logs/screenshots containing sensitive data.

`DU1234567`, `placeholder_user`, `placeholder_password`, and `your_google_sheet_id_here` are placeholders only.
