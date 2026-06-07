# V7 IBKR Gateway Add-on

## Purpose

The `ibkr_gateway` add-on acts as a shared IBKR Gateway / API service for the Home Assistant bot suite. It runs the official IBKR Gateway application via IBC (IB Controller) and exposes the API over the network for other add-ons (like the bot suite) to connect to.

**Important Architecture Note:** This add-on does *not* contain any trading strategy, grid logic, or bot runtime behavior. It only provides the Gateway connection. The target Phase 1 model requires that one bot add-on instance handles one IBKR account and one Google Sheet, while this Gateway add-on serves as the centralized connection point for those bots.

## Configuration Options

| Option | Type | Default | Description |
|---|---|---|---|
| `ibkr_username` | string | `placeholder_user` | The username for the IBKR account. **Use a placeholder unless you are in Home Assistant's secure Config UI.** |
| `ibkr_password` | string (password) | `placeholder_password` | The password for the IBKR account. **Use a placeholder unless you are in Home Assistant's secure Config UI.** |
| `trading_mode` | list (paper\|live) | `paper` | The trading mode to start the Gateway in. |
| `api_port` | port | `7497` | The port the IBKR API service will listen on inside the container and via Home Assistant exposed ports. |
| `vnc_port` | port | `5900` | The port to expose VNC on, if enabled. |
| `readonly_api` | boolean | `false` | If true, sets `ReadOnlyApi=yes` in the IBC config, preventing any orders from being placed. |
| `trusted_ips` | string | `127.0.0.1` | Trusted IPs for the API connection. (Currently standard placeholder config). |
| `enable_vnc` | boolean | `false` | Enables an optional VNC server. |

## Ports

- `7497` (tcp): Default API port. Exposed to Home Assistant.
- `5900` (tcp): Default VNC port. Exposed to Home Assistant.

## Connecting Bot Add-ons

Bot add-ons (like `tqqq_bot`) connect to this shared Gateway add-on using the Home Assistant service hostname or network alias.

In your bot add-on configuration, you should specify the gateway host and port. For example:
- `gateway_host`: `"ibkr_gateway"` (or the appropriate slug based on your network settings)
- `gateway_port`: `7497`

Do not assume `localhost` unless the bot and Gateway are deliberately running in the same container.

## VNC Usage

If `enable_vnc` is `true`, an X11 VNC server will start on port `5900`.
**VNC is intended ONLY for temporary private-network troubleshooting and IB Gateway GUI access.** For example, you may need VNC access to confirm manual 2FA prompts or to visually inspect the Gateway status if it fails to automatically authenticate via IBC.

Ensure VNC is disabled during normal headless operation to save resources and minimize attack surface.

## Secret Handling & Security

**NEVER COMMIT SECRETS TO GIT.**
Do not hardcode or commit:
- Real IBKR usernames, passwords, or account IDs (e.g., DU1234567)
- OAuth certificates or private keys
- Token caches
- Google service-account JSON files
- Any `.env` files with actual secrets

All documentation and default configurations must use placeholder values (like `placeholder_user`, `DU1234567`, `your_google_sheet_id_here`).

Home Assistant's architecture allows you to securely specify `ibkr_username` and `ibkr_password` through its Config UI, where they are protected and not checked into source control. External secrets, certificates, or caches should be mounted externally and never baked into the container.
