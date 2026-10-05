# V7 IBKR Gateway Add-on

## Purpose

The `ibkr_gateway` add-on runs a standalone IBKR Gateway (through IBC) with no trading logic. It comes from the shared-Gateway design, in which separate bot add-ons would connect to one Gateway.

**Status: retained but not usable with the current bots.** The project moved to bundled add-ons (one Gateway, one bot, one account and one Google Sheet per add-on) because shared-Gateway mode created trusted-IP and container-networking friction in Home Assistant. The bundled `tqqq_bot` and `tqqq_bot_account_2` add-ons force `ibkr_host` to `127.0.0.1`, so they cannot connect to this add-on. The folder stays in the repository until a decision removes it. See the repository's [main README](https://github.com/Wakeboardsam/V7-ha-ibkr-bot-suite/blob/main/README.md) and the 2026-06-09 entry in `DECISION_LOG.md`.

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

## VNC Usage

If `enable_vnc` is `true`, an X11 VNC server may start on port `5900`.

VNC is intended only for temporary private-network troubleshooting and IB Gateway GUI access, such as checking manual 2FA prompts or Gateway status.

Keep VNC disabled during normal headless operation to reduce resource usage and minimize attack surface:

```yaml
enable_vnc: false
vnc_port: 5900
```

## Secret Handling & Security

Never commit credentials, real account IDs or other secrets; use placeholders such as `placeholder_user` and `placeholder_password`. Enter real credentials only in the Home Assistant configuration. See `SECURITY.md` in the repository for the full policy.
