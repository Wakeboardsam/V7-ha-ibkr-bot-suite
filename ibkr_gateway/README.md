# V7 IBKR Gateway Add-on

## Purpose

The `ibkr_gateway` add-on provides a standalone IBKR Gateway / IBC service for the Home Assistant bot suite.

After the 2026-06-09 architecture pivot, this add-on is retained as optional/experimental shared-Gateway mode for Phase 1. It is no longer the recommended primary Phase 1 production path.

The recommended Phase 1 path is a bundled Gateway + bot add-on per account, starting with `tqqq_bot`.

## Architecture Status

`ibkr_gateway` does not contain trading strategy logic, grid logic, Bridge Anchor behavior, Google Sheets trading logic, or bot runtime behavior. It only provides a Gateway connection.

Shared Gateway mode may be revisited later if Home Assistant container networking and IBKR trusted-IP behavior are solved cleanly.

Do not delete this add-on unless a later decision says it blocks the bundled add-on path.

## Optional / Experimental Shared-Gateway Mode

In shared-Gateway mode, separate bot add-ons connect to this Gateway add-on over the Home Assistant add-on network.

This model is no longer the primary Phase 1 path because it can create practical trusted-IP/container-networking friction.

For Phase 1, prefer:

```text
one bundled add-on instance = one IBKR Gateway session = one trading bot = one IBKR account = one Google Sheet
```

## Configuration Options

| Option | Type | Default | Description |
|---|---|---|---|
| `ibkr_username` | string | `placeholder_user` | The username for the IBKR account. Use a placeholder unless configuring through Home Assistant's secure Config UI. |
| `ibkr_password` | string (password) | `placeholder_password` | The password for the IBKR account. Use a placeholder unless configuring through Home Assistant's secure Config UI. |
| `trading_mode` | list (`paper`/`live`) | `paper` | The trading mode to start the Gateway in. |
| `api_port` | port | `7497` | The port the IBKR API service listens on inside the container. |
| `vnc_port` | port | `5900` | The port the VNC service listens on inside the container. |
| `readonly_api` | boolean | `false` | If true, sets `ReadOnlyApi=yes` in the IBC config, preventing orders from being placed through this Gateway. |
| `trusted_ips` | string | `127.0.0.1` | Trusted IPs for the API connection. Use placeholder/default-safe values in source-controlled examples. |
| `enable_vnc` | boolean | `false` | Enables optional VNC troubleshooting access. |

## Ports

- `7497` (tcp): Default API port.
- `5900` (tcp): Default VNC port.

Changing exposed ports can affect Home Assistant add-on behavior and should be handled in a later runtime/config PR with an add-on version bump.

## Connecting Bot Add-ons

Shared-Gateway mode is optional/experimental for Phase 1.

If this mode is used, bot add-ons connect to this Gateway using the Home Assistant service hostname or network alias, for example:

```yaml
gateway_host: "ibkr_gateway"
gateway_port: 7497
```

Do not assume `localhost` in shared-Gateway mode unless the bot and Gateway are deliberately running in the same container.

For the primary bundled Phase 1 path, the bot should connect to its local bundled Gateway instead:

```yaml
ibkr_host: "127.0.0.1"
ibkr_port: 7497
```

## VNC Usage

If `enable_vnc` is `true`, an X11 VNC server may start on port `5900`.

VNC is intended only for temporary private-network troubleshooting and IB Gateway GUI access, such as checking manual 2FA prompts or Gateway status.

Keep VNC disabled during normal headless operation to reduce resource usage and minimize attack surface:

```yaml
enable_vnc: false
vnc_port: 5900
```

## Secret Handling & Security

**Never commit secrets to git.**

Do not hardcode or commit:

- real IBKR usernames or passwords
- real IBKR account IDs
- OAuth certificates or private keys
- API tokens
- token caches
- Google service-account JSON files
- real Google Sheet IDs
- `.env` files or `.env` secret values
- logs or screenshots showing secrets or full account IDs

All documentation and default configurations must use placeholder values, such as:

```yaml
ibkr_username: "placeholder_user"
ibkr_password: "placeholder_password"
ibkr_account_id: "DU1234567"
google_sheet_id: "your_google_sheet_id_here"
```

Account IDs must be masked in logs, UI output, docs, and screenshots. Example masked format:

```text
DU1****567
```

Home Assistant's Config UI should be used for real runtime secrets. External secrets, certificates, or caches should be mounted externally and never baked into the container image.
