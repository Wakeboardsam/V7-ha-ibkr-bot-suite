# Decision Log

- **2026-06-04**: v7 repo is public.
- **2026-06-04**: no license file yet.
- **2026-06-04**: stable source baseline is Wakeboardsam/v6_IBKR_WebAPI tag v6.3.1-Single_Account_Stable.
- **2026-06-04**: Phase 1 model is independent bot instances, not a centralized multi-account supervisor.
- **2026-06-04**: initial later add-on folders are planned as ibkr_gateway and tqqq_bot.

## 2026-06-05 — Step 02 HA scaffold validation passed

Outcome:
- Home Assistant repository install succeeded.
- V7_ibkr_gateway installed and started.
- V7_tqqq_bot installed and started.
- Both add-ons stayed running safely.
- Gateway runtime/login did not start.
- Bot runtime/strategy did not start.
- Account ID masking worked: DU1****567.
- This is the stable checkpoint before Step 03 v6 runtime port.

Decision:
- Preserve this scaffold as the known-good HA install baseline.
- Step 03 will port the real v6 tqqq_bot runtime into V7_tqqq_bot.
- Do not duplicate tqqq_bot for other accounts until the first runtime port works.

## 2026-06-08 — Step 03/PR 05 v6 runtime ported into tqqq_bot

Outcome:
- Ported the v6 TQQQ python bot runtime from `v6_baseline/v6_IBKR_WebAPI` into `tqqq_bot`.
- Verified account scoping logic correctly limits execution to `ibkr_account_id`.
- TQQQ Bot connect outward to `ibkr_gateway` in the staged implementation.
- Strategy components (Grid logic, Sheets, Bridge Anchor) remain unchanged.

Decision:
- `tqqq_bot` is configured to map Gateway connection options into the python environment in the staged implementation.
- Tests will live outside of the production Docker environment (`tqqq_bot/tests`).
- Gateway and IBC processes were separated from the bot for the PR05 micro-service boundary checkpoint.

## 2026-06-09 — Bundled Gateway + bot architecture chosen for Phase 1

Outcome:
- The project pivoted from treating shared `ibkr_gateway` mode as the primary Phase 1 path to a bundled Gateway + bot add-on model.
- Shared Gateway mode is cleaner in theory, but it created practical trusted-IP/container-networking friction in Home Assistant.
- The working v6 add-on already proves the same-container model can run successfully: Gateway + bot in one add-on, with the bot connecting to a local Gateway and writing to its configured Google Sheet.

Decision:
- The primary Phase 1 model is now:

  ```text
  one bundled add-on instance = one IBKR Gateway session = one trading bot = one IBKR account = one Google Sheet
  ```

- `tqqq_bot` becomes the first bundled implementation target.
- `ibkr_gateway` remains in the repo as optional/experimental shared-Gateway mode.
- Do not delete `ibkr_gateway` unless a later decision says it blocks the bundled path.
- Do not create account 2/account 3 add-on folders yet.
- Do not rebuild from scratch.
- Do not rename the repository.
- Preserve v6 strategy behavior, including grid logic, Bridge Anchor behavior, TQQQ-only scope, and current Google Sheets behavior unless a safety requirement explicitly requires a change.
- Keep v7 account-scoping safety changes.
- Future HA-testable add-on/config/runtime merges must bump the affected add-on version.
- Docs-only PRs do not need add-on version bumps unless they also change add-on/config/runtime files.

## 2026-06-10 — PR07 Copy Gateway Runtime Pieces into tqqq_bot

Outcome:
- Created the first bundled v7 Home Assistant add-on by adapting `tqqq_bot` to contain both IBKR Gateway and the Python bot runtime.
- `tqqq_bot` now handles the startup sequence: Xvfb -> VNC -> IBC -> Gateway -> wait for local API port -> start bot.
- `gateway_host` default was safely changed to `127.0.0.1` while remaining configurable.
- `tqqq_bot` add-on version was bumped so HA detects the changes.

Decision:
- `ibkr_gateway` folder is kept intact as optional/experimental shared-Gateway mode.
- Trading strategy code/behavior remains identical to v6 logic.
- We did not introduce `supervisord` since the `run.sh` background/exec pattern provides sufficient, minimal process management.
## 2026-06-15 — Implement session-boundary cancellation exception

Outcome:
Added logic to gracefully handle IBKR overnight order cancellations that typically happen around 03:50 ET.

Decision:
If a cancellation occurs between 03:45 ET and 04:05 ET, the bot checks the current position snapshot. If the position snapshot successfully confirms > 0 position, the engine preserves the `OWNED` status of the row and removes the stale `WORKING_SELL` tracking instead of halting. For BUY and BRIDGE_BUY tracking, the working status is gracefully cleared. If the position snapshot is not > 0 or fails, the engine correctly fails closed and halts. The timezone boundary checks enforce strictly `America/New_York` to avoid any DST or execution server timezone issues.
## 2026-06-15 — Update session-boundary cancellation to use async snapshot check

Outcome:
Moved the position snapshot query out of the sync `_handle_order_update` handler into an async helper `_handle_session_boundary_cancel_async`.

Decision:
The `get_verified_symbol_snapshot` function is inherently asynchronous. Checking the state in a sync handler blocks the loop or returns an un-awaited coroutine, resulting in incorrect halting behavior. We now delegate the verification to `create_task()` which awaits the state of the symbol position before enforcing an unexpected fail-closed halt or safely preserving `OWNED` row status. Tests have been fully updated to support the new async behavior. Duplicate `mark_cancelled` calls were also removed.
## 2026-06-15 — Update session-boundary snapshot verification to fail closed strictly

Outcome:
Updated `_handle_session_boundary_cancel_async` to enforce strict validation against the snapshot struct returned by the broker.

Decision:
The code now wraps `await self.broker.get_verified_symbol_snapshot(TICKER)` in a try/except block. If an exception occurs, or if `snapshot_status` is not explicitly `"OK"` (e.g. `PARTIAL`, `UNAVAILABLE`), the engine safely defaults to a hard fail-closed halt (`SELL_CANCELLED_NO_FILL_HALT`). This ensures we never falsely assume safety upon encountering broker connectivity or data structure edge cases. Tests were added to verify exception and `PARTIAL` status scenarios.
## 2026-06-25 — Authorize Account 2 Duplication

Outcome:
Account 1 is declared the stable baseline and Account 2 duplication is authorized as the `tqqq_bot_account_2` bundled add-on.

Decision:
The `tqqq_bot_account_2` add-on provides a second independent bot copy. It must be created using manual boot, paper mode, dry-run enabled, read-only API enabled, VNC disabled, and placeholders for credentials to maintain a strict safe default posture. Stale documentation forbidding the creation of Account 2 has been updated.

## 2026-10-04 — Consolidate repository documentation

Outcome:
- `README.md` is now the single authoritative guide to the project: architecture, startup and recovery, trading lifecycle, Google Sheet, configuration, account isolation, notifications, and development, testing, parity, versioning and rollback.
- `CLAUDE.md` holds concise working rules for AI agents and points to the README for everything else. `CONTRIBUTING.md` is reduced to a pointer. The v6 baseline note in `docs/` was folded into the README and removed. Add-on READMEs now cover only add-on-specific operator details.

Decision:
- Current behavior is documented in `README.md`; this log keeps the historical reasons for decisions. Earlier entries are unchanged, including those that describe superseded plans (for example the staged shared-Gateway implementation and the instruction not to create account copies).
- Changes to halt, circuit-breaker or reconciliation behavior require a decision log entry. Other significant behavior changes continue to be recorded here; routine wording edits are not.

## 2026-10-04 — Bridge Anchor re-anchor flushes the old grid

Outcome:
- On 2026-10-02 a Bridge Anchor fill re-anchored the grid (row 7 went from 65 to 64 shares, row 8 from 62 @ 80.39 to 61 @ 81.70), but the BUY orders already working on rows 8 to 10 stayed at the broker with the old prices and sizes. An hour later the old row 8 BUY filled for 62 shares against a Sheet value of 61, and the share-mismatch check repeated every minute with the Bridge Anchor still armed and no SELL on row 8.
- Cause: a normal full sell-out cancels the lower BUYs because the active window collapses to row 7 when nothing is owned. The bridge path takes row 7 straight from sold to owned, so that flush never ran.

Decision:
- After a Bridge Anchor fill the bot cancels every working BUY from the old grid and places nothing until the broker no longer shows them and the old row 7 SELL has finished. The wait is bounded: a cancel with no callback after 60 seconds is sent again, an old BUY absent from the broker on two consecutive ticks is released, and a re-anchor still unsettled after five minutes is reported to the Errors tab and by a `BRIDGE_REANCHOR_STALLED` notification.
- The Sheet counts as recalculated only when row 7's buy price matches the fill price and row 7 reads the same on two consecutive ticks. The bot writes `G7` again if the fill price has not appeared.
- The tick that places the trim SELL ends there. The new row 7 SELL, window BUYs and bridge order follow on later ticks.
- Standing check: a working BUY on row 8 or below that does not match its Sheet row on two consecutive ticks is cancelled and placed again. Row 7's anchor BUY keeps its existing warn-only check, because cancelling it rewrites `G7`.
- Share-mismatch behavior change: in both `halt` and `warn` modes an unexplained mismatch now cancels a Bridge Anchor order that is still armed and sends one `SHARE_MISMATCH` notification per distinct pair of share counts. It still does not set the persistent halted state.
- Six existing tests that set `ANCHOR_RECALC_PENDING` directly now run one extra tick before their unchanged assertions, because of the two-read rule.
- Not changed: the bridge phase is still held in memory only, and `_cancel_bridge_anchor` still releases order tracking before the broker confirms the cancel.

## 2026-10-05 — Health reports the real trading state; re-anchor survives a restart

Outcome:
- Health showed "Running" while the share-mismatch check blocked trading, because it looked only at the reconciliation-halt flag. Its order comparison also flagged every valid Bridge Anchor order, by comparing the internal action `BRIDGE_BUY` with the broker's `BUY`.
- A restart between a Bridge Anchor fill and its trim lost the bridge phase: the bot reported broker 65 against Tracker 64 every minute and placed no SELL.

Decision:
- One function describes the engine's current state, and Health, Errors rows and notifications use it. The states are listed in `README.md`. A share mismatch is reported as a pause (`halt` mode) or limited trading (`warn` mode); it does not set the persistent halted state and clears only when a tick verifies fresh broker and Tracker counts agree. Recovery writes a `SHARE_MISMATCH_CLEARED` Errors row and notification.
- `BRIDGE_HALTED` now records its reason and is reported once by notification. The one reconciliation latch that had no notification (missing or invalid `WORKING_SELL` in the share check) now sends `HALT_RECONCILIATION`.
- Health validates a bridge order against its stop and limit and a trim against its trim quantity.
- Restart recovery uses a small record in the add-on's `/data` folder rather than a Tracker status marker, because row 7's status after a bridge fill must stay exactly `OWNED:<id>`. The record is account-fingerprinted and is honoured only when row 7 and the broker still agree with it. A re-anchor that halted leaves no record and is never resumed automatically. No trim is ever inferred from a share difference alone.
- The share comparison after a re-anchor counts every row the Tracker shows as owned, so an old-grid BUY that fills before its cancel lands stays accounted for; excess within `bridge_max_auto_trim_shares` is trimmed. Shares that may come from an old BUY whose outcome the bot never saw are not trimmed: the bridge flow halts.
- Not changed: the share-mismatch comparison itself and its tolerance, the trim limit, the per-tick Errors row while a mismatch persists, and `BRIDGE_HALTED` being held in memory only.

## 2026-10-05 — Re-anchor record carries unknown BUYs and the trim

Outcome:
- A review of `375c33f` reproduced a restart safety bug: an old-grid BUY that left the broker without a report was remembered as unknown only in memory. With three unexplained shares plus the bridge's one, a running bot halted and sold nothing, but a restarted bot sold four shares and reported Running.
- The same review found that a bridge halt's first Errors row had code `ERROR` and no status, that a restart while a trim was working ended in a reconciliation halt, and that Health accepted a plain stop order as a valid bridge.

Decision:
- The record now names unreported old-grid BUYs, and is written before their Tracker rows are cleared. A restart restores that uncertainty, so shares the bridge fill does not explain are still not trimmed.
- The record also carries the trim SELL's order ID, quantity and limit price, written before the order is sent. A restart restores the wait for the trim only on an exact match of those terms and of the remaining excess. A saved trim that is gone with excess remaining halts the bridge flow; it is not replaced.
- A bridge halt enters the halt state before it writes its Errors row, through one helper, so the row has code `BRIDGE_HALTED` and the status Health shows. Other Errors rows written by the engine now carry the status as well.
- The share comparison does not place a trim while one this process already sent is working. This closes an older case where a placement call that failed after reaching the broker led to two trims for one excess share.
- Health requires the bridge order type to be exactly `STP LMT`.
- Not changed: the trim limit, the share-mismatch comparison and its tolerance, and the looser stop-order test reconciliation uses when it matches an untracked bridge order to the Tracker.

## 2026-10-05 — A saved trim that cannot be resumed is cancelled

Outcome:
- A review of `2c37e76` showed that when a restart refused to resume the saved trim because the broker's excess was already gone, the bot halted but left the SELL working at IBKR. It later filled, leaving 63 broker shares against 64 in the Tracker. Halting the engine does not stop an order already at the broker.
- The same review found that a bridge-halt Errors row whose first write failed was never written, and that startup reconciliation still accepted a plain stop order as a bridge while Health rejected it.

Decision:
- A trim that strictly matches the saved record but no longer matches the broker's excess is tracked and cancelled, with the cancel repeated until the broker no longer has the order. The bridge flow halts either way. The record is kept until the cancel is confirmed. A fill during the cancel is handled as the bot's own trim, and a trim fill no longer lifts a bridge halt.
- An order with the saved ID but different terms is still left alone: it is not verifiably the bot's order.
- The bridge-halt Errors row is marked written only when the Sheet accepts it, and is retried each tick until then. The notification is still sent once.
- Reconciliation halt behavior change: an untracked bridge order is matched to the Tracker only if it passes the strict stop-limit check Health uses. A plain stop order with the bridge's prices now halts with `EXTERNAL_OPEN_ORDER_RECONCILE_REQUIRED`.

## 2026-10-05 — Owed cancels and reports continue during a reconciliation halt

Outcome:
- A review of `86e2fb4` showed that once a reconciliation halt was set, the tick returned before the trim cancellation and bridge-halt reporting retries. A trim whose cancel the broker had refused stayed live after the broker recovered and sold another share (60 to 59), and a failed `BRIDGE_HALTED` Errors row was never written.
- It also showed that the saved record did not say the trim had to be cancelled. After an unconfirmed cancel, a second restart with the position back at 65 resumed the trim as a normal working order and the bot returned to Running without the operator.

Decision:
- Reconciliation halt behavior change: while halted the bot still places nothing, but it keeps cancelling orders it already owes a cancel for (a saved trim that must not run, and old-grid BUYs of a re-anchor in progress) and keeps retrying a bridge-halt Errors row that failed to write. The halt itself stays latched.
- The record carries the cancel requirement and the halt reason, written before the cancel is requested. A later restart cancels the trim and halts with that reason whatever the position is.
- The bot's own cancel of a saved trim is not treated as an IBKR session-boundary cancellation, even between 03:45 and 04:05 ET.
- Not changed: once the trim is confirmed gone, the record is removed and `BRIDGE_HALTED` is held in memory only, as before.

## 2026-10-05 — Halted cancels wait for a ready broker snapshot

Outcome:
- A review of `f4aee5c` showed that the cancel loop that runs during a reconciliation halt read open orders without checking that broker state was ready. In a simulated reconnect, two empty reads made the bot forget a trim that was still live and delete its record; the trim then sold a share (60 to 59). This was a simulation, not an observed IBKR reconnect.

Decision:
- While reconciliation-halted, the bot counts an order as absent only on a ready broker snapshot. Without one it keeps the order's tracking, the cancel requirement and the saved record, and starts its consecutive-absence counts over. The Errors row retry still runs.
- Ticks that are not halted were already skipped on an unready snapshot before any of this logic.

## 2026-10-06 — Cancelling an unfilled bridge no longer marks row 7 owned

Outcome:
- On 2026-10-06 at 04:12 the row 7 SELL filled for 64 shares and the Bridge Anchor order did not fill. Row 7 was correctly set to `IDLE`. One tick later the bot cancelled the bridge, and the helper that removes the `BRIDGE_BUY` part from a status added `OWNED:0` to a row that held nothing, writing `OWNED:0|IDLE`. The Tracker then claimed 63 shares against a broker position of 0 and the bot halted with `SELL_POSITION_MISMATCH_HALT`, leaving three old-grid BUYs working.
- The helper predates the re-anchor work. The case needs the bridge to stay unfilled after row 7 sells, which had not happened before.

Decision:
- Removing a part from a status keeps ownership only for a row that was owned before the removal. A row that held no shares stays `IDLE`. Nothing else changes: with row 7 `IDLE` and no shares, the existing full sell-out path cancels the lower BUYs and places the new anchor BUY.
- Not investigated here: why the Bridge order did not trigger when row 7 sold at its stop price before the regular session.

## 2026-10-07 — A partly filled working BUY is not a share mismatch

Outcome:
- A test confirmed that a grid BUY still working at the broker with part of its quantity filled tripped the share-mismatch breaker. The broker already held the filled shares while the row stayed `WORKING_BUY`, and only partly filled SELLs were adjusted for. In `halt` mode the bot stopped placing all orders, including SELLs, until the BUY finished; in `warn` mode it stopped BUYs and the Bridge Anchor. It wrote an Errors row every tick and sent a notification for each new fill count.

Decision:
- The share-mismatch check adds the filled quantity of each `WORKING_BUY` whose order is still live at the broker for the configured account, capped at the row's share count, to the shares it expects.
- Filled shares of a BUY that is no longer live, and any shares beyond that filled quantity, are still a mismatch. Startup reconciliation and the `SELL_POSITION_MISMATCH_HALT` check are unchanged; they only halt when the broker holds fewer shares than the Tracker requires.

## 2026-10-07 — A share mismatch writes one Errors row per distinct mismatch

Outcome:
- With `share_mismatch_mode: halt`, an unexplained share mismatch pauses trading and recovers on its own once a fresh broker snapshot matches the Tracker. The notification was already sent once per distinct pair of broker and Sheet share counts, but the same `SHARE_MISMATCH` Errors row was written on every tick.

Decision:
- The owner chose to keep the pause and the automatic resume (no latch until restart), so a temporary difference does not need a restart, and to rely on the `SHARE_MISMATCH` notification to prompt a manual fix.
- The Errors row is now written once per distinct pair of counts, like the notification. A failed write is retried on the next tick. A different pair of counts, or the same pair again after a verified recovery, writes a new row. Both `halt` and `warn` modes behave this way.

## 2026-10-07 — The connection watchdog alerts before restarting the add-on

Outcome:
- When the Gateway stays disconnected for more than 15 minutes, or account data does not load after a fresh reconnect, the bot stops its container with `SIGTERM` to PID 1. Home Assistant restarts a stopped add-on only when that add-on's Watchdog toggle is on, and it is off by default. With it off the bot stayed down, and no notification said so.

Decision:
- Just before the stop, the bot sends a critical `WATCHDOG_RESTART` notification with the reason, controlled by `notify_on_halts`. The send is synchronous so it completes before the process exits. A failed send is logged and the stop still happens.
- The owner turns on Watchdog for both add-ons in Home Assistant. The restart conditions and the stop itself are unchanged.

## 2026-10-07 — Every notification has its own switch, all off by default

Outcome:
- `notify_on_halts` controlled seven different alerts, from reconciliation halts to Gateway login and watchdog restarts, so they could only be turned on or off together. `notify_on_errors` and `notify_on_order_submit` were offered as options but no code read them.

Decision:
- Each alert has its own switch: fills, bot started, order placed, reconciliation halt, Bridge halt, re-anchor not settling, share mismatch, share mismatch cleared, Gateway login needed, watchdog restart and other errors. Existing option names are kept so saved choices carry over.
- The owner chose that every switch is off by default, so an installation sends nothing until the operator turns on the alerts they want. Home Assistant shows a name and description for each switch from `translations/en.yaml`.
- "Other errors" covers only Errors-tab rows without an alert of their own, so a halt or a watchdog restart sends one alert through its own switch. Each automatic share repair alerts; any other repeated error alerts once until it clears. "Order placed" covers grid BUYs and SELLs, the Bridge Anchor BUY and trim SELLs.
- Switches change only what is sent to the phone. Errors-tab rows, Health and trading behaviour are unchanged.

## 2026-10-08 — Remove the unused standalone Gateway add-on

Outcome:
- The shared-Gateway design was intended to let multiple account bots use one Gateway. Trusted-IP and container-networking friction prevented that deployment from working, so each account now runs an independent add-on with its own bundled Gateway.
- Both current bots enforce a local Gateway connection at `127.0.0.1`. No script or CI job depends on the standalone `ibkr_gateway` add-on.

Decision:
- The owner approved deleting `ibkr_gateway/` and removing its current add-on references from the three READMEs. This supersedes the retention decisions of 2026-06-09 and 2026-06-10; earlier entries remain as history.
- Keep the one-add-on, one-Gateway, one-bot, one-account, one-Sheet architecture. Neither bot's runtime, configuration, trading behavior or version changes; removal of an unused add-on requires no update to either installed bot.
- Before merging, check Home Assistant Settings > Add-ons and uninstall `V7_ibkr_gateway` if it is still installed. Repository removal does not stop or uninstall an existing container, and that add-on will no longer be available for updates or rebuilds from this repository. Do not uninstall either bundled bot add-on.
