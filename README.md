# v7 HA IBKR Bot Suite

## Purpose

This repository is a Home Assistant add-on repository for running the IBKR TQQQ grid bot as independent, account-scoped add-on instances.

The v7 project prepares the existing working single-account IBKR bot so it can be safely run against different IBKR accounts without allowing one bot instance to read from, write to, or trade the wrong account.

## Current Status

PR00 through PR05 are complete.

Known completed checkpoints:

- The repository is an installable Home Assistant add-on repository.
- The stable v6 source baseline has been imported into `v6_baseline/`.
- `ibkr_gateway` and `tqqq_bot` exist as add-on folders.
- The v6 TQQQ trading bot runtime has been ported into `tqqq_bot`.
- Account-scoping safety logic has been added for the configured `ibkr_account_id`.
- The v6 grid strategy behavior, Bridge Anchor behavior, TQQQ-only scope, and Google Sheets behavior are intended to remain preserved unless a later safety task explicitly requires a change.

Do not rebuild the repository from scratch. Do not rename the repository. Do not create account 2/account 3 add-on copies yet.

## Stable Source Baseline

The stable source baseline for this project remains the working v6 bot:

- Repository: `Wakeboardsam/v6_IBKR_WebAPI`
- Tag: `v6.3.1-Single_Account_Stable`

v6 is the proven working runtime pattern. v7 should reuse the working v6 behavior where possible while adding Home Assistant packaging and account-scoping safety.

## June 9, 2026 Architecture Pivot

On 2026-06-09, Phase 1 pivoted away from treating a shared `ibkr_gateway` add-on as the primary deployment path.

The primary Phase 1 target is now a bundled add-on architecture, starting with `tqqq_bot`.

Core Phase 1 rule:

```text
one bundled add-on instance = one IBKR Gateway session = one trading bot = one IBKR account = one Google Sheet
```

The bundled model is intended to preserve the proven v6 same-container shape while keeping the new v7 account-scoping safety changes.

The target bundled add-on contains:

1. IBKR Gateway runtime
2. IBC / Gateway startup configuration
3. optional VNC troubleshooting access
4. Python trading bot runtime
5. IBKR account configuration
6. Google Sheet configuration
7. account ID masking and account-scoping guardrails

This is intentionally not a centralized multi-account supervisor.

## Phase 1 Target Model

Correct Phase 1 model:

```text
Bundled add-on 1 -> Gateway 1 -> Bot 1 -> IBKR Account A -> Google Sheet A
Bundled add-on 2 -> Gateway 2 -> Bot 2 -> IBKR Account B -> Google Sheet B
Bundled add-on 3 -> Gateway 3 -> Bot 3 -> IBKR Account C -> Google Sheet C
```

Incorrect Phase 1 model:

```text
One bot process -> multiple IBKR accounts -> multiple Google Sheets
```

No account 2/account 3 folders should be created yet. The first goal is to make the initial bundled `tqqq_bot` path work safely in Home Assistant.

## Add-on Folders

- `tqqq_bot`: Primary Phase 1 target. This is the first bundled Gateway + trading bot add-on target. The current implementation may still be staged across PRs; documentation should not imply bundled runtime behavior is complete until the code implements it.
- `ibkr_gateway`: Retained as optional/experimental shared-Gateway mode. It is not the recommended primary Phase 1 production path after the June 9 architecture pivot.

Shared Gateway mode can be revisited later if Home Assistant container networking and IBKR trusted-IP behavior are solved cleanly.

## Trading Strategy Scope

Phase 1 must preserve current v6 strategy behavior.

Keep:

- current grid logic
- current Bridge Anchor behavior
- current order behavior unless account scoping requires a safety change
- TQQQ as the only traded symbol for now
- current Google Sheets behavior unless safe account separation requires adjustment

Strategy changes are out of scope unless they are directly required for account scoping, safe runtime separation, or Home Assistant packaging.

## Gateway Auto-Restart and Maintenance Recovery

The add-on uses IBC AutoRestartTime to handle IBKR’s nightly Gateway/TWS restart requirement. The default is 11:48 PM America/Denver, just before the user-observed 11:50 PM maintenance disruption.

The bot already prepares for the maintenance window by cancelling orders. During Gateway downtime, trading is paused and no new orders should be placed. The bot should reconnect after Gateway returns and only resume after broker state is READY.

ColdRestartTime is Sunday 06:00 PM America/Denver. Live accounts may still require IBKR Mobile 2FA after cold restart, host reboot, full add-on restart, or session expiration.

VNC remains manual and should only be enabled for troubleshooting or manual 2FA approval.

## Required Account-Scoping Safety

Each bot instance must only operate on its configured IBKR account.

When `ibkr_account_id` is configured, order placement must explicitly target that account.

Broker reads should be account-scoped when IBKR exposes account information, including:

- positions
- portfolio
- open orders
- wallet/cash
- net liquidation
- fills/executions

Account IDs must be masked in logs, UI output, docs, and screenshots. Example masked format:

```text
DU1****567
```

By default, `mask_account_ids_in_logs` is `true`. Do not share logs or debug output if this has been disabled.

If multiple IBKR accounts are visible and no `ibkr_account_id` is configured, the bot should warn loudly or refuse unsafe trading.

## Placeholder Configuration Only

Use placeholder values in source-controlled examples:

```yaml
active_broker: "ibkr"
paper_trading: true
ibkr_host: "127.0.0.1"
ibkr_port: 7497
ibkr_client_id: 1
ibkr_account_id: "DU1234567"
google_sheet_id: "your_google_sheet_id_here"
google_credentials_json: ""
mask_account_ids_in_logs: true
enable_vnc: false
```

Do not commit real values.

## Home Assistant Testing and Versioning Policy

Home Assistant testing occurs from the `main` branch after Sam reviews and merges a PR.

Every future HA-testable add-on/config/runtime merge must bump the affected add-on version so Home Assistant can detect and install the updated add-on.

Examples of changes that require a version bump:

- `config.yaml` changes
- Dockerfile changes
- `run.sh` changes
- Python runtime changes
- dependency changes
- bundled Gateway/bot runtime behavior changes

Docs-only PRs do not need an add-on version bump unless they also change add-on/config/runtime files.

Keep PRs small, focused, and easy to revert.

## Security Warning

This repository is public. No secrets, credentials, real account IDs, OAuth certificates, private keys, API tokens, Google service-account files, `.env` secrets, token caches, real Google Sheet IDs, or logs/screenshots containing sensitive data belong in the repo.

Use placeholders only. Refer to `SECURITY.md` for details.
