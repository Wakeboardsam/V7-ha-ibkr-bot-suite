# v7 HA IBKR Bot Suite

A Home Assistant add-on repository that runs a TQQQ grid-trading bot against Interactive Brokers (IBKR), driven by a Google Sheet. Each add-on instance is self-contained and bound to exactly one IBKR account and one Google Sheet.

This README is the authoritative description of the project and how to operate and change it. Agent working rules are in [`CLAUDE.md`](CLAUDE.md), the reasons behind significant decisions are in [`DECISION_LOG.md`](DECISION_LOG.md), and the security policy is in [`SECURITY.md`](SECURITY.md).

**How to read this guide.** Statements without a tag describe behavior implemented in the current code (checked against add-on version 0.1.44). Code shows what is implemented, not necessarily what was intended, so two tags mark the gaps:

- **[Intended]** — documented project intent that the code or tests do not prove.
- **[Unverified]** — could not be confirmed from this repository (for example Google Sheet formulas or Home Assistant behavior).

## Contents

1. [Architecture](#architecture)
2. [Startup, readiness, maintenance and recovery](#startup-readiness-maintenance-and-recovery)
3. [Trading lifecycle](#trading-lifecycle)
4. [Google Sheet](#google-sheet)
5. [Configuration](#configuration)
6. [Account isolation and secrets](#account-isolation-and-secrets)
7. [Notifications](#notifications)
8. [Development and operations](#development-and-operations)

## Architecture

### One instance, one account

```text
one add-on instance = one IBKR Gateway session = one trading bot = one IBKR account = one Google Sheet
```

Each add-on bundles the IBKR Gateway (run through IBC), an optional VNC server for manual login, and the Python bot, all in one container. The bot connects to the Gateway on `127.0.0.1`. This is deliberately not a central supervisor: one bot process never trades more than one account.

The bundled design replaced an earlier shared-Gateway design because trusted-IP and container-networking friction in Home Assistant made the shared Gateway impractical, while the proven v6 bot already ran Gateway and bot together in one container (see the 2026-06-09 entry in the decision log).

### Folders

| Folder | Role |
|---|---|
| `tqqq_bot/` | **Account 1**, the stable baseline add-on. Source of truth for bot code and canonical tests. |
| `tqqq_bot_account_2/` | **Account 2**, an independent copy of the Account 1 runtime. Committed defaults are the safe ones: `boot: manual`, `dry_run: true`, `readonly_api: true`, paper mode. |
| `ibkr_gateway/` | Standalone Gateway add-on from the abandoned shared-Gateway design. Kept in the repository but **not usable with the current bots** (see below). |
| `v6_baseline/` | Imported source of the stable v6 release (`Wakeboardsam/v6_IBKR_WebAPI`, tag `v6.3.1-Single_Account_Stable`). Reference only; it is not built, tested or deployed from here. |
| `scripts/` | CI helper scripts (parity and configuration validation). |

Account 2 must remain a runtime copy of Account 1: the two `app/` trees, `wait_for_gateway.py`, `Dockerfile`, `run.sh` (modulo add-on names) and the other non-test files must be byte-identical, which CI enforces. Only `config.yaml` (name, slug, boot mode, safe defaults), `README.md` and `tests/` differ.

**`ibkr_gateway` status.** Both bundled bots force `ibkr_host` to `127.0.0.1` at startup (in `run.sh` and `main.py`), so they cannot connect to a Gateway in a different add-on. The shared-Gateway mode described in earlier project documents therefore does not work with the current code. The folder is retained until a decision removes it.

### Scope and strategy constraints

- The strategy is the v6 grid strategy: the grid logic, Bridge Anchor behavior, TQQQ-only scope and Google Sheets behavior come from the stable v6 baseline. Do not change them unless a safety requirement or Home Assistant packaging need explicitly requires it.
- The traded symbol is hard-coded to `TQQQ`.
- `active_broker` accepts only `ibkr`. A Schwab adapter exists only as a stub.
- The repository is public and its name does not change.

## Startup, readiness, maintenance and recovery

### Container startup (`run.sh`)

1. Read Home Assistant options from `/data/options.json`, log the account ID in masked form and force `ibkr_host` to `127.0.0.1`.
2. Restore saved Gateway settings and Java preferences from `/data/ibgateway/persist` into `/root/Jts` and `/root/.java`, so first-run Gateway choices (such as the SSL reconnect prompt) survive restarts.
3. Render the IBC configuration from `gateway/ibc_config.ini.template` (credentials, trading mode, read-only API flag, API port, auto and cold restart times) and set `BypassOrderPrecautions` and `BypassRedirectOrderWarning` in `jts.ini`.
4. Start Xvfb, then `x11vnc` only if `enable_vnc` is true.
5. Check that the Java runtime bundled with IB Gateway (`/opt/ibgateway_jre`) exists, then start Gateway through IBC.
6. Run `wait_for_gateway.py` until the API port opens or the timeout expires (3600 s for `live`, 300 s for `paper`). On timeout the container prints sanitized IBC logs and exits with an error.
7. Copy the Gateway settings back to `/data` once, then every `300` seconds in the background. The interval is a `run.sh` default; it is not exposed as an add-on option.
8. Start the Python bot (`python -m main`). When the bot exits, `run.sh` stops the other processes and exits with the bot's exit code.

**Login problems.** If IBC reports the Gateway as `LOGGED_OUT` for five minutes while the port is still closed, `wait_for_gateway.py` prints a loud warning and, when notifications are enabled with `notify_on_halts`, sends a Home Assistant alert every five minutes asking the operator to open VNC and sign in. Live accounts may need IBKR Mobile two-factor approval after a cold restart, host reboot, full add-on restart or session expiry. VNC has no password; enable it only for troubleshooting and do not expose its port to untrusted networks.

### Bot startup (`main.py`, then the engine)

1. Load configuration and install the account-ID masking filter on all logging.
2. Warn loudly if `trading_mode`, `paper_trading` and `ibkr_port` disagree (paper expects 7497, live expects 7496).
3. Refuse to start when `dry_run` is false and `ibkr_account_id` is empty.
4. Connect to IBKR and Google Sheets; load the 50 most recent execution IDs from the Fills tab to avoid logging duplicates; subscribe to executions.
5. Wait up to 30 seconds for a non-zero `TQQQ` price, otherwise shut down.
6. Start the heartbeat and Health tasks and begin the tick loop (every `poll_interval_seconds`).
7. The first tick that passes reconciliation sends one "TQQQ Bot Started" notification (`notify_on_startup_ok`).

### Readiness and the connection watchdog

A tick runs only when the broker connection is up and broker state is **READY**: account values are populated and a live positions request has completed. If the connection drops, the watchdog reconnects on the existing connection object, then on a fresh one. If the Gateway stays disconnected for more than 15 minutes, or the connection is up but account state stays not ready through two successive waits of about two minutes (the second after a fresh reconnect), the bot signals the container to restart (`SIGTERM` to PID 1). **[Unverified]** whether Home Assistant restarts the add-on after that exit: `config.yaml` defines no `watchdog` option.

### Nightly maintenance and restarts

IBKR restarts or disconnects Gateway around 23:50 (user-observed, America/Denver). The settings below cooperate:

- **Gateway auto restart** (`gateway_auto_restart_time`, default `11:48 PM`) has IBC restart the Gateway just before the observed disruption.
- **Gateway cold restart** (`gateway_cold_restart_time`, default `06:00 PM`) is a weekly full restart. **[Intended]** IBC runs it on Sundays; live accounts may then need two-factor approval.
- **Bot maintenance window** (`maintenance_start_local`–`maintenance_end_local`, default `23:44`–`00:00`, in `timezone`): on entering the window the bot cancels its open orders (when `maintenance_cancel_open_orders` is true), forgets its order tracking and trades nothing until the window ends.
- **Reconnect grace** (`maintenance_reconnect_grace_minutes`, default 30) extends the period after the window in which a disconnected Gateway does not trigger a container restart, avoiding a restart loop that would keep demanding two-factor approval. Trading stays paused while disconnected and resumes only when broker state is READY again.

### Shutdown

On `SIGTERM` the engine stops its loop, drains the fill-logging queue, cancels the orders it tracks (skipped in dry-run mode) and disconnects.

## Trading lifecycle

### Who computes what

The **Google Sheet decides the grid; the bot executes it.** The bot reads, for rows 7–100 of the `TQQQ_Tracker` tab, the status (column C), the owned flag `Y` (column D), the sell price (F), the buy price (G) and the share count (H). It does not compute prices or quantities. **[Unverified]** How the Sheet derives these values: the Sheet and its formulas are not in this repository.

The bot writes only: row status (column C, rows 7–100), the heartbeat (`C1`), the cash value (`C2`) and the anchor ask price (`G7`). The Sheet interface rejects writes to any other cell.

### Row statuses

Column C holds one status per row, and several parts can be combined with `|` (for example `OWNED:123|BRIDGE_BUY:456`).

| Status | Meaning |
|---|---|
| `IDLE` | Nothing owned or working. |
| `OWNED:<id>` | Shares are held for this row (`<id>` is the order that bought them, or `0`). |
| `WORKING_BUY:<id>` / `WORKING_SELL:<id>` | A BUY or SELL limit order is live at the broker. |
| `BRIDGE_BUY:<id>` | A Bridge Anchor stop-limit BUY is armed on row 7. |
| `TRIM_SELL:<id>` | A Bridge Anchor trim SELL is working on row 7. |
| `ERROR_RECONCILE_REQUIRED:<code>` | The bot stopped on this row; an operator must reconcile it. |
| `FAILED` | The bot skips the row. |

**Owned flag (`has_y`).** When the bot reads the Sheet, a row counts as owned when column D is `Y`, with one exception: a row whose status begins `ERROR_RECONCILE_REQUIRED` is also treated as owned. Once the bot changes a row's status itself, or overlays a status that has not yet been written to the Sheet, it recomputes the flag from the status text (`OWNED:` or `WORKING_SELL:`, plus `ERROR_RECONCILE_REQUIRED` for its own updates). The owned flag drives `distal_y`, the grid window, the Bridge Anchor's "only owned row" test and the Sheet-shares total in the share-mismatch check. The reconciliation share requirement is computed separately from status text (`OWNED:`, `WORKING_SELL:`, `BRIDGE_BUY:` and `TRIM_SELL:` rows).

### The tick

Each tick, in this order (any step can end the tick early):

1. Skip everything if the engine is halted.
2. Ensure the broker connection is up and READY (watchdog).
3. Handle the maintenance window.
4. Read the grid from the Sheet and overlay status updates not yet written back.
5. Read the position snapshot and open orders. If the snapshot is not READY, skip the tick.
6. Wait for any session-boundary cancellations to settle (see [Cancellations](#cancellations-and-sessions)).
7. Repair clerical Tracker mismatches for orders the running bot already owns.
8. Run reconciliation checks and halt if they fail (see [Reconciliation and halts](#reconciliation-and-halts)).
9. At the 16:00 and 20:00 ET boundaries, regenerate the session (cancel all bot orders, clear order tracking) and end the tick.
10. Write the account's total cash to `C2`.
11. If shares went from above zero to zero, a full sell cycle has completed: write a fresh ask to `G7` (resetting the anchor) and end the tick.
12. Cancel stale session orders and untracked or duplicate Bridge Anchor orders; run the share-mismatch checks; then handle Bridge Anchor states and evaluate the grid.
13. Write pending status updates to the Sheet and record the share count.

### Grid evaluation

Let `distal_y` be the highest row number whose status is owned. The **active window** runs from `max(7, distal_y − 3)` to `max(7, distal_y + 3)`.

- **Owned rows in the window** need a working SELL at the row's sell price for the row's share count. The bot places a missing one after the pre-SELL guard passes.
- **Rows beyond `distal_y` in the window** need a working BUY at the row's buy price. A working BUY on row 8 or below whose quantity or price no longer matches its row on two consecutive grid evaluations is cancelled and placed again from the Sheet on a later tick. A row that reads as zero shares or zero price is ignored, and a partly filled BUY is left in place.
- **Row 7 with nothing owned** is the anchor acquisition: the BUY price is the Sheet's buy price plus `anchor_buy_offset`, and the order is skipped while the bid/ask spread exceeds `max_spread_pct`.
- **Rows outside the window** have their working orders cancelled and their status reset to `OWNED:<id>` or `IDLE`.
- **Failed placements.** A BUY error returns the row to `IDLE` with a five-minute cooldown. A SELL error halts the engine.
- **Weekend gap.** From Friday 20:00 ET to Sunday 20:00 ET no new orders are placed.
- **Dry run.** With `dry_run`, the bot logs every order it would have placed or cancelled and sends none.

### Cancellations and sessions

Orders use the exchange and time-in-force for the current session: `OVERNIGHT` with `DAY` orders from 20:00 to 03:50 ET (Sunday evening through Friday morning), `SMART` with `GTC` orders otherwise. When the session changes, the bot cancels its own stale-session orders and places new ones on the next tick.

IBKR cancels overnight orders around 03:50 ET. A cancelled SELL between 03:45 and 04:05 ET is treated as expected only if a fresh position snapshot reports `OK` with a position above zero; the bot then removes the working SELL and keeps ownership. Any other result halts. After such a cancellation the bot waits for the cancellation callbacks, skips one further tick to let state settle, and halts if a callback does not arrive within 15 minutes.

Any other SELL that errors, is rejected or is cancelled with zero fill, and was not cancelled by the bot itself, halts the engine. Cancellations the bot starts (maintenance, session change, leaving the window) are recorded as intentional and preserve ownership.

### Bridge Anchor

The Bridge Anchor protects against a fast rally after row 7, the last owned row, sells. It arms only when all of these hold: the feature is enabled (`enable_bridge_anchor`), row 7 is the only owned row, row 7 has a working SELL, broker shares equal row 7's share count, the session is not `OVERNIGHT`, it is not the weekend gap, and no share mismatch is active. It then places a GTC stop-limit BUY for row 7's share count with the stop at row 7's sell price and the limit at that price plus `anchor_buy_offset`. It cancels the order when those conditions stop holding, and a separate check cancels a live Bridge order whenever no row 7 SELL is found at the broker. These checks run on each tick, so they reduce but do not eliminate the time a Bridge order can be live without its SELL. If row 7's SELL fills and the Bridge order does not, row 7 is `IDLE` with no shares: the bot cancels the Bridge order and carries on as after any full sell-out (fresh ask to `G7`, lower BUYs cancelled, new anchor BUY).

When the Bridge BUY fills, the anchor moves and every level is recalculated, so the bot re-anchors in fixed steps and places nothing new until each step is confirmed:

1. It writes the fill price to `G7`, marks row 7 owned, and cancels every working BUY left from the old grid. A normal full sell-out gets this flush when the active window collapses to row 7; the bridge path skips that state, so it is done explicitly.
2. On each tick it waits until the broker shows no old-grid BUY and the old row 7 SELL is no longer working. Order tracking is normally released by the broker's cancel or fill callback. To keep the wait bounded, a cancel with no callback after 60 seconds is sent again, and an old-grid BUY that the broker has not shown on two consecutive ticks is released without a callback; if that order had in fact filled, the share comparison in step 4 sees the extra shares.
3. It waits for the Sheet to recalculate: row 7's buy price must match the fill price, and row 7's sell price, buy price and share count must be identical on two consecutive reads. If the fill price has not appeared, the bot writes `G7` again.
4. It compares broker shares with the recalculated share count of every row the Tracker shows as owned. Normally that is row 7 alone; if an old-grid BUY filled before its cancel landed, that row is owned too and its shares are counted. Equal means normal operation resumes.
5. Excess shares, up to `bridge_max_auto_trim_shares`, are sold with a trim SELL at the current bid minus `anchor_buy_offset`. That tick ends there; the new row 7 SELL, the window BUYs and the next bridge order are placed on later ticks from a fresh broker read.
6. More excess than the limit, fewer shares than expected, an unusable bid, or a failed cancel moves the bridge flow to `BRIDGE_HALTED`, which stops all grid evaluation. The halt is entered first and then written to the Errors tab with code `BRIDGE_HALTED`, the reason and the same status text Health shows; if that write fails it is tried again on each tick until the Sheet accepts it. The halt is also sent once as a `BRIDGE_HALTED` notification. If a trim SELL this process sent is already working, the bot waits for it and does not place another. These halts need operator attention.

A re-anchor that has not settled after five minutes is reported once to the Errors tab and by a `BRIDGE_REANCHOR_STALLED` notification; the bot keeps waiting and places nothing.

**Fills that race the cancel.** An old-grid BUY that fills completely before its cancel lands marks its row owned, and the shares above the recalculated Tracker counts are trimmed in step 5 if they are within the limit. An old-grid BUY that was partly filled is cancelled like the others and its row returns to `IDLE`, so its filled shares count as excess: within the limit they are trimmed, above it the bridge flow halts and the operator reconciles. An old-grid BUY that left the broker without any cancel or fill report is treated as unknown: the bot then trims only the shares the bridge fill itself explains, and halts on anything more, whatever the trim limit.

**Restart during a re-anchor.** The bot keeps a small record of the re-anchor in progress in `/data/bridge_reanchor_state.json`: the bridge order ID, fill price and filled quantity, a fingerprint of the configured account, the IDs of old-grid BUYs that left the broker without a report, and, once a trim is being placed, the trim SELL's order ID, quantity and limit price. An unreported old-grid BUY is written to the record before its Tracker row is cleared; if the record cannot be written, the row keeps its `WORKING_BUY:<id>` status. The record is removed when the shares match, when the trim finishes, or when the bridge flow halts.

At startup the bot uses the record only if it matches the configured account and row 7 still reads `OWNED:<bridge order ID>` (checked on two reads before a non-matching record is discarded). Then:

- **No trim placed yet:** it resumes the re-anchor, with the unreported old-grid BUYs still counted as unknown. Old-grid BUYs still at the broker are picked up by the order IDs in the Tracker and cancelled.
- **Saved trim still working:** it restores the wait for the trim only if the broker order has the saved ID, is a SELL limit order with the saved quantity and limit price, and the broker's excess over the Tracker equals what the trim still has to sell. If the order matches the record but the excess no longer does, the trim must not run: the bot halts the bridge flow and cancels the order, sending the cancel again on later ticks until the broker no longer has it. Before the cancel is requested, the record is marked with the cancel requirement and the halt reason, and it stays until the cancel is confirmed. Another restart therefore cancels the trim and halts again with the same reason, even if the position has since moved to match the trim. The cancel keeps being retried during a reconciliation halt. A fill that beats the cancel is recorded as the bot's own trim, and reconciliation then halts if the broker holds fewer shares than the Tracker. An order with the saved ID but different terms is not the bot's to cancel: it is left alone and reconciliation halts on it as an unknown order.
- **Saved trim no longer at the broker:** if broker and Tracker shares now agree, the re-anchor is complete. If excess remains, the bridge flow halts and no replacement trim is placed, as when a running bot's trim is cancelled.

Without a matching record the bot does not trim: a share difference alone is handled as an ordinary share mismatch. A restart while the old row 7 SELL is still working ends in `EXTERNAL_OPEN_ORDER_RECONCILE_REQUIRED`, and `BRIDGE_HALTED` itself is held in memory only, so after a restart an unresolved bridge halt shows as a share mismatch.

### Fills and partial fills

Every execution reported by IBKR for the configured account and `TQQQ` stock is queued and appended to the Fills tab, de-duplicated by execution ID, with up to three retries. Executions on orders the bot does not track are logged with row `UNKNOWN`.

The engine changes a row's status on a fill only when the order is completely filled: a BUY becomes `OWNED:<id>`, a SELL becomes `IDLE`, a trim returns row 7 to `OWNED`. Partial fills are handled only through reconciliation: a working SELL that is partly filled counts for its remaining quantity (taken from the broker's remaining quantity), and a missing or invalid remaining quantity halts. **[Unverified]** Outside a Bridge Anchor re-anchor there is no dedicated handling or test for a partially filled working BUY, whose shares appear at the broker before its row changes status.

### Reconciliation and halts

Before the bot trades, and again each tick, it compares the Sheet with the broker:

- Any open `TQQQ` order that is not tracked and does not strictly match a Sheet row's order ID, side, quantity and price stops the bot (`EXTERNAL_OPEN_ORDER_RECONCILE_REQUIRED`). A Bridge Anchor order is matched with the same test Health uses: order type exactly `STP LMT`, row 7's shares, stop at row 7's sell price and limit at that price plus `anchor_buy_offset`.
- Any row already in `ERROR_RECONCILE_REQUIRED` stops the bot (`TRACKER_ERROR_RECONCILE_REQUIRED`).
- The shares the Sheet claims for owned and working rows, adjusted for partial fills, must not exceed broker shares, and every `WORKING_SELL` must be live at the broker with a valid remaining quantity (`SELL_POSITION_MISMATCH_HALT`).
- If a Tracker `WORKING_SELL` is missing at the broker but broker shares exactly match the Tracker with no partial fills, and the running bot is not tracking that order, the bot waits for a **second consecutive snapshot** before treating it as stale and allowing the SELL to be replaced. That case is not a halt. A missing `WORKING_BUY` is not repaired automatically.
- A **pre-SELL guard** runs immediately before every SELL and trim: broker shares minus working SELL quantity must cover the order, otherwise the bot halts instead of risking a short sale.
- A **share-mismatch check** compares broker shares with the Sheet's owned shares (partial-fill adjusted). A mismatch that exactly one combination of working-order rows explains, where those orders are gone from the broker, is repaired (rows set to `OWNED` or `IDLE`) and the tick ends. Any other mismatch is logged to the Errors tab as a circuit-breaker event. With `share_mismatch_mode: halt` the bot skips the tick and repeats the check on the next tick; with `warn` it continues but places no BUYs and arms no Bridge Anchor. In both modes an unexplained mismatch cancels a Bridge Anchor order that is still armed and sends one `SHARE_MISMATCH` notification per distinct pair of broker and Sheet share counts. The mismatch does not set the persistent halted state. It clears only when a later tick compares a fresh broker snapshot with the Tracker and the counts agree; the bot then writes a `SHARE_MISMATCH_CLEARED` row to the Errors tab and sends a notification. A trim SELL that is partly filled when a tick runs is reported as a mismatch until it completes.

A **reconciliation halt** sets `HALTED_RECONCILIATION`: the bot places nothing and re-prices nothing, writes the Errors and Health tabs (retrying in the background if the Sheet is unreachable), and sends the `HALT_RECONCILIATION` notification. A halt does not remove orders that are already at the broker, so two narrow duties continue on every tick while halted: cancels the bot already owes (a saved trim SELL that a restart decided must not run, and old-grid BUYs of a re-anchor that was in progress) and a bridge-halt Errors row whose earlier write failed. These cancels run only on a ready broker snapshot: while broker state is not ready (for example just after a reconnect) an empty order list is not taken as proof that an order is gone, so tracking, the cancel requirement and the saved record are kept and the cancels resume when the snapshot is ready. The Errors row retry does not depend on the broker. Every other working order stays at the broker until the operator deals with it. Halts latch until the add-on restarts, and restarting with an unresolved `ERROR_RECONCILE_REQUIRED` row halts again. The operator must compare the Sheet with the broker, correct the Tracker, then restart.

**Health status.** The Health tab's status column, the status column of Errors rows and the notifications all take their text from one description of what the engine is currently allowed to do. It is separate from the snapshot status: a snapshot marked `OK` means broker data is available, not that trading is permitted.

| Status | Meaning |
|---|---|
| `Running` / `Running (Mode=DRY_RUN)` | Normal operation. |
| `HALTED_RECONCILIATION` | Reconciliation halt. Latched until the add-on restarts. |
| `BRIDGE_HALTED: <reason>` | The bridge flow stopped. No orders are placed until the operator reconciles and restarts. |
| `PAUSED_MAINTENANCE` | Inside the maintenance window. |
| `PAUSED_SHARE_MISMATCH: broker N, tracker M` | Unexplained share mismatch in `halt` mode: nothing is placed. Rechecked every tick. |
| `LIMITED_SHARE_MISMATCH: broker N, tracker M` | Unexplained share mismatch in `warn` mode: SELLs continue, no BUYs, no Bridge Anchor. |
| `WAITING_BRIDGE_RECALC` | A re-anchor is waiting for old orders to clear or the Sheet to recalculate. |
| `WAITING_TRIM` | A trim SELL is working. |
| `PAUSED_WEEKEND_GAP` | Friday 20:00 ET to Sunday 20:00 ET: no new orders. |

The Health order comparison treats a Bridge Anchor order as a BUY and a trim as a SELL. A bridge order matches only when its order type is exactly the stop-limit type the bot places (`STP LMT`; a plain stop does not match), for row 7's shares, with the stop at row 7's sell price and the limit at that price plus `anchor_buy_offset`. A trim matches on the trim it placed (SELL limit order, trim quantity and limit price), not row 7's share count.

| Halt code | Meaning |
|---|---|
| `SELL_POSITION_MISMATCH_HALT` | Sheet claims more shares than the broker holds, a working SELL is missing or invalid, or the pre-SELL guard would oversell. |
| `EXTERNAL_OPEN_ORDER_RECONCILE_REQUIRED` | An open `TQQQ` order is neither tracked nor matched to the Sheet. |
| `TRACKER_ERROR_RECONCILE_REQUIRED` | A row is already marked `ERROR_RECONCILE_REQUIRED`. |
| `SELL_CANCELLED_NO_FILL_HALT` | A SELL was dropped without a fill and cancellation was not expected. |
| `IBKR_SHORT_REJECTION_HALT` | IBKR rejected a SELL as a short sale. |
| `SELL_ORDER_ERROR_RECONCILE_REQUIRED` / `TRIM_SELL_ORDER_ERROR_RECONCILE_REQUIRED` | A SELL or trim failed on placement. |
| `BRIDGE_POSITION_MISMATCH_HALT` | Fewer broker shares than row 7 claims when arming the Bridge. |
| `BRIDGE_CANCEL_FAILED_HALT` | A Bridge order could not be cancelled and may still be live. |
| `SESSION_BOUNDARY_CANCEL_TIMEOUT_HALT` | A session-boundary cancellation was not confirmed within 15 minutes. |

### Sheet synchronization

The bot keeps row statuses in memory first. Each change is numbered, and writes to the Sheet go through a single lock that skips a write if a newer status for that row was queued in the meantime. Failed writes are retried by later ticks. The next tick re-reads the Sheet, but pending local statuses override the Sheet's value until they have been written. This is intended to keep the bot from acting on an older Sheet value while a write is in flight; it does not rule out every timing gap between the Sheet, the broker and the bot.

## Google Sheet

The service account in `google_credentials_json` must have edit access to the Sheet named by `google_sheet_id`. The Sheet needs four tabs:

| Tab | Role |
|---|---|
| `TQQQ_Tracker` | The grid. Rows 7–100 are grid levels (status in C, owned flag in D, sell price F, buy price G, shares H). `C1` is the heartbeat, `C2` the account's total cash, `G7` the anchor ask. |
| `Fills` | One row per execution: timestamp, execution ID, row, type, price, quantity, order and perm IDs, symbol, then `LEVEL` and `PROFIT` formulas added by the bot. `PROFIT` refers to `TQQQ_Tracker!H3`. |
| `Health` | A periodic account-scoped snapshot every `health_log_interval_seconds`: last price, position, broker-sourced market price, value and average cost, net liquidation, snapshot status, open-order counts, and how broker orders match the Tracker. |
| `Errors` | Timestamp, severity, code, symbol, row, action, bot status and details for circuit breakers, halts and errors. |

The bot appends to `Fills`, `Health` and `Errors` and never edits their existing rows. Fills write with `USER_ENTERED` so the formulas evaluate; Health and Errors write raw values.

## Configuration

Options are set in the Home Assistant add-on UI. The defaults and schema live in each add-on's `config.yaml`, and the committed values must be placeholders. The runtime schema is `tqqq_bot/app/config/schema.py`.

| Group | Options | Role |
|---|---|---|
| Broker and account | `active_broker`, `paper_trading`, `trading_mode`, `ibkr_host`, `ibkr_port`, `ibkr_client_id`, `ibkr_account_id`, `ibkr_username`, `ibkr_password` | Which account the instance trades. `trading_mode` configures Gateway; `paper_trading` configures the bot; they should agree. `ibkr_host` is forced to `127.0.0.1`. `ibkr_port` defaults to 7497 (paper) and is also the port Gateway opens. |
| Safety | `dry_run`, `readonly_api`, `mask_account_ids_in_logs` | `dry_run` connects and reads real state but places, cancels and modifies no orders; it does not simulate fills. `readonly_api` makes IBC start the Gateway API read-only. Masking defaults to true. |
| Sheet | `google_sheet_id`, `google_credentials_json` | Target Sheet and service-account JSON. Enter the JSON as a single line; multi-line values may not round-trip through the Home Assistant password field. |
| Loop | `poll_interval_seconds` (60), `heartbeat_interval_seconds` (60), `health_log_interval_seconds` (300) | Tick, `C1` heartbeat and Health tab cadence. |
| Strategy | `anchor_buy_offset` (1.5), `max_spread_pct` (0.5), `enable_bridge_anchor` (true), `bridge_max_auto_trim_shares` (5), `share_mismatch_mode` (`halt` or `warn`) | Anchor price offset, spread limit for the anchor BUY, Bridge Anchor controls and mismatch behavior. |
| Maintenance | `maintenance_enabled`, `maintenance_start_local`, `maintenance_end_local`, `maintenance_reconnect_grace_minutes`, `maintenance_cancel_open_orders`, `timezone` | The nightly pause (see above). `timezone` also sets the container's `TZ`. |
| Gateway | `gateway_auto_restart_enabled`, `gateway_auto_restart_time`, `gateway_cold_restart_enabled`, `gateway_cold_restart_time`, `gateway_live_wait_timeout_seconds`, `gateway_paper_wait_timeout_seconds`, `enable_vnc`, `vnc_port` | IBC restart schedule, readiness timeouts and optional VNC. VNC is disabled by default and its port is unmapped. |
| Notifications | `notifications.*` | See [Notifications](#notifications). |

Account 2's committed defaults (manual boot, paper, `dry_run`, read-only API, VNC off, placeholder credentials) are checked by `scripts/validate_account_addons.py`.

## Account isolation and secrets

**Isolation.** Each bot may act only on its configured account:

- Orders carry the configured `ibkr_account_id`. The bot refuses to place orders when no account is configured outside dry-run mode, or when several accounts are visible and none is configured.
- Positions, portfolio items, open orders, executions and order-status callbacks are filtered to the configured account; events without an account are ignored. Only stock contracts count, so same-symbol options do not affect reconciliation.
- Account IDs are masked (for example `DU1****567`) in application logs, error messages, `run.sh` output and IBC log excerpts, unless `mask_account_ids_in_logs` is disabled; do not share logs if it is.
- Each instance has its own Gateway session, persisted settings directory under `/data`, credentials and Sheet.

**Secrets.** The repository is public. Never commit credentials, real account IDs, Google Sheet IDs, service-account files, OAuth certificates, private keys, API tokens, `.env` files, token caches, or logs and screenshots that show them. Use the placeholders `DU1234567`, `placeholder_user`, `placeholder_password` and `your_google_sheet_id_here`. Real values belong only in the Home Assistant add-on configuration. `SECURITY.md` lists what to do after an accidental commit.

## Notifications

When `notifications.enabled` is true and `webhook_url` is set, the bot posts JSON to a Home Assistant webhook. Sends run off the event loop, network and HTTP send errors are caught and logged rather than raised, and identical messages inside `dedupe_window_seconds` are dropped.

| Event | When | Controlled by |
|---|---|---|
| `FILL_BUY` / `FILL_SELL` | A tracked order fills. | `notify_on_fills` |
| `HALT_RECONCILIATION` | A reconciliation halt. | `notify_on_halts` |
| `BOT_STARTED` | The first tick passes reconciliation. | `notify_on_startup_ok` |
| `SHARE_MISMATCH` | Broker and Sheet share counts disagree and no missed fill explains it. Sent once per distinct pair of counts. | `notify_on_halts` |
| `SHARE_MISMATCH_CLEARED` | A tick verified that broker and Sheet share counts agree again. | `notify_on_halts` |
| `BRIDGE_HALTED` | The bridge flow halted. Sent once, with the reason. | `notify_on_halts` |
| `BRIDGE_REANCHOR_STALLED` | A Bridge Anchor re-anchor has not settled after five minutes. Sent once per re-anchor. | `notify_on_halts` |
| `GATEWAY_AUTH_REQUIRED` | Gateway stays logged out while its port is closed (sent by the startup script). | `notify_on_halts` |

`notify_on_errors` and `notify_on_order_submit` exist as options but no code reads them. The webhook URL is stored as a password-type option because it contains a secret.

## Development and operations

### Workflow

- Work on a feature branch from `main`. Keep each pull request small and focused, and do not mix refactors with fixes or features.
- Do not rebuild the project from scratch or reorganize the add-on folders without an explicit decision.
- Pull requests use `.github/pull_request_template.md`. The repository owner reviews and merges. Home Assistant testing happens from `main` after merge.
- Record significant behavior changes in `DECISION_LOG.md`. Changes to halt, circuit-breaker or reconciliation behavior always need an entry. Routine wording edits do not.

### Running the tests

The suites run from inside each add-on directory. Install dependencies, then run:

```bash
# Account 1: includes tests for wait_for_gateway.py, which import `tqqq_bot`
cd tqqq_bot
pip install -r requirements.txt -r requirements-test.txt
PYTHONPATH=app:.. python -m pytest -q

# Account 2
cd ../tqqq_bot_account_2
pip install -r requirements.txt -r requirements-test.txt
PYTHONPATH=app python -m pytest -q
```

`PYTHONPATH=app` makes the bot's modules importable. Account 1 also needs the repository root (`..`) on the path because `test_wait_for_gateway.py` imports `tqqq_bot`; without it, collection fails. Account 2 has no copy of that test file because tests stay canonical in `tqqq_bot`.

**Current baseline.** At add-on version 0.1.44, Account 1 runs 293 tests and Account 2 runs 284, and all pass. The three `tests/test_status_strings.py` failures recorded earlier were stale expectations: since 2026-06-28 an outside-window cancel leaves the row status unchanged until IBKR confirms the cancel, and the tests now cover that.

### Continuous integration

`.github/workflows/account-addon-ci.yml` runs on pushes and pull requests to `main`. It compiles the Python (`python -m compileall -q app tests wait_for_gateway.py`), syntax-checks `run.sh` (`bash -n`), runs the parity and configuration scripts below, runs both pytest suites with the `PYTHONPATH` shown above, and checks whitespace with `git diff --check`. Pytest was removed from CI on 2026-07-16 because of baseline failures and restored on 2026-10-07 once the baseline was green.

### Parity between accounts

A production-code change belongs in both add-ons in the same pull request, with Account 1 as the reference. Verify with:

```bash
python scripts/check_addon_parity.py        # app/, scripts and non-test files identical
python scripts/validate_account_addons.py   # Account 2 safe defaults, placeholders, matching option keys (needs PyYAML)
```

### Version bumps

Any change that Home Assistant must detect and install requires a version bump in the affected add-on's `config.yaml`: option or config changes, `Dockerfile` or `run.sh` changes, Python runtime changes, dependency changes, and bundled Gateway or bot behavior changes. Documentation-only pull requests need no bump unless they also change add-on files. The version is how Home Assistant recognizes an update.

### Before merging a code change

Run the tests for the code you changed and the full suites for both add-ons (compare with the baseline above, so a new failure stands out), then the parity script and the validation script.

### Deployment and rollback

There is no separate deployment pipeline: merging to `main` publishes the add-on version, and Home Assistant installs it when the operator updates the add-on. Keep `boot` for Account 2 as `manual` and test new behavior in `dry_run` or paper mode first. To roll back, revert the pull request and bump the add-on version, as for any runtime change, so Home Assistant detects the reverted code, then update the add-on. The pull request template asks each change to state its rollback impact.

## Imported v6 baseline

`v6_baseline/` contains the v6 source exactly as imported, with secrets and local state removed and no intentional behavior changes. It was the staging source for the v7 add-ons and remains as reference.
