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

## 2026-06-28 — Pre-SELL guard waits out a recent session-boundary cancel

Backfilled on 2026-10-08 from PR #23 (Account 1 0.1.22 at merge).

Outcome:
- After an overnight session-boundary cancel, the bot tried to replace the missing SELL while the broker's open-order list still showed the cancelled order as working. The pre-SELL guard then counted 0 shares available and raised a false `SELL_POSITION_MISMATCH_HALT`.

Decision:
- For 10 seconds after a session-boundary cancel, the pre-SELL guard fetches open orders again and skips the SELL placement cycle while any recently cancelled order still shows a non-terminal status. It counts only active orders and uses their remaining quantity.

## 2026-07-14 — Reconciliation counts only TQQQ stock

Backfilled on 2026-10-08 from PR #24 (Account 1 0.1.23 at merge).

Outcome:
- TQQQ option positions, such as short puts, were counted as TQQQ shares during reconciliation and execution syncs, which could raise false short-mismatch halts.

Decision:
- The IBKR adapter considers only stock contracts (`secType == "STK"`) for positions, open orders and executions, and the position snapshot reads only the configured ticker's stock. Same-symbol options are ignored.

## 2026-07-16 — Account 2 add-on created; parity enforced in CI

Backfilled on 2026-10-08 from PR #25 (both add-ons 0.1.24).

Outcome:
- `tqqq_bot_account_2` was created as a copy of the Account 1 runtime, as authorized on 2026-06-25, with safe committed defaults: `boot: manual`, paper mode, `dry_run: true`, `readonly_api: true`, VNC off and placeholder credentials.
- CI was added: `scripts/check_addon_parity.py` keeps the runtime files of the two add-ons identical, and `scripts/validate_account_addons.py` enforces Account 2's safe defaults and placeholders.

Decision:
- Account 1 stays the reference; every runtime change is made in both add-ons.
- Pytest was removed from CI in this pull request because the baseline had 3 failing tests. It was restored on 2026-10-07.

## 2026-07-24 — Ticks wait while session-boundary cancels are verified

Backfilled on 2026-10-08 from PR #26 (both add-ons 0.1.24 at merge).

Outcome:
- Reconciliation could run while the asynchronous check of a session-boundary SELL cancel was still in flight, before the row was confirmed `OWNED`, and raise a false `SELL_POSITION_MISMATCH_HALT`.

Decision:
- While any such check is in flight, ticks skip reconciliation and order placement. One further tick is skipped after the checks finish, so the Sheet sync and reconciliation see the verified status.

## 2026-07-28 — Startup warns when Gateway is stuck logged out

Backfilled on 2026-10-08 from PR #27 (Account 1 0.1.26).

Outcome:
- Gateway could sit at an expired-token or locked login screen while the startup log only repeated that it was waiting for the API port.

Decision:
- `wait_for_gateway.py` reads the IBC logs. When the latest login state stays `LOGGED_OUT` for five minutes, it prints a loud warning and sends a `GATEWAY_AUTH_REQUIRED` notification asking the operator to finish the login over VNC. The existing 1-hour live and 5-minute paper timeouts are unchanged.

## 2026-07-29 — Automatic dismissal of the expired-token dialog tried

Backfilled on 2026-10-08 from PR #28 (Account 1 0.1.27, Account 2 0.1.25 at merge) and PR #29 (both add-ons 0.1.28).

Outcome:
- PR #28 patched IBC with a `GatewayDialogHandler.java` to dismiss the expired-token dialog and log in again, in Account 1 only. It did not detect the dialog.
- PR #29 reverted it and re-implemented the handler in both add-ons, detecting the dialog from its full window structure.

Decision:
- Superseded on 2026-08-04, when the automation was removed.

## 2026-08-04 — Expired-token login automation removed

Backfilled on 2026-10-08 from PR #30 (both add-ons 0.1.29).

Outcome:
- The IBC patch was deleted from both add-ons, and the Dockerfiles went back to `default-jre` with no Java compile step.

Decision:
- Expired-token logins are handled by the operator over VNC, prompted by the 2026-07-28 warning and notification.
- The pull request itself did not record the reason. Recovered from the owner's 2026-07-29 and 2026-08-03 project discussion and backfilled on 2026-10-08: the patch still did not dismiss the expired-token dialog; manual recovery required clicking OK, entering the password and approving phone two-factor authentication. The owner requested removing the ineffective bypass while retaining the manual-login notification.

## 2026-08-05 — Missing working orders self-healed at startup

Backfilled on 2026-10-08 from PR #31 (both add-ons 0.1.30).

Outcome:
- After a start or restart, `WORKING_SELL` or `WORKING_BUY` order IDs kept in the Tracker but missing at the broker raised a false `SELL_POSITION_MISMATCH_HALT`, even when broker shares matched the Tracker.

Decision:
- When broker shares exactly matched the Tracker and nothing else was ambiguous, a missing `WORKING_SELL` became `OWNED` and a missing `WORKING_BUY` became `IDLE`. Superseded the next day.

## 2026-08-06 — A missing SELL must be missing on two ticks

Backfilled on 2026-10-08 from PR #32 (both add-ons 0.1.31).

Outcome:
- The 2026-08-05 self-healing was judged unsafe and removed, including the `WORKING_BUY` repair.

Decision:
- A tracked `WORKING_SELL` that is missing at the broker, and not tracked by the running engine, must be missing on two consecutive ticks before the halt is bypassed and the normal logic places the SELL again. This applies only when broker shares match the Tracker exactly, with no partial fills and no open SELL whose remaining quantity is unclear. The first missing tick is skipped. An order that reappears resets the count. In every other case the halt stays.

## 2026-09-01 — Tracker status writes are serialized

Backfilled on 2026-10-08 from PR #34 (both add-ons 0.1.32). PR #33, an earlier version of the same change, was not merged.

Outcome:
- Concurrent Tracker status writes could overwrite a `WORKING` cell with an older `IDLE` or `OWNED` value.

Decision:
- Status writes go through one lock, and the latest write wins.
- When a Tracker cell disagrees with a live broker order that the running engine already tracks, the bot corrects the cell, writes it and ends the tick before reconciliation. An unknown or manual broker order is never adopted; it stays under the existing halt rules.

## 2026-09-02 — Fills rows get Level and Profit formulas

Backfilled on 2026-10-08 from PR #35 (both add-ons 0.1.33).

Decision:
- Each new Fills row is written with Level and Profit formulas in columns J and K, built with `INDEX` and `ROW()`. Fills rows are written as `USER_ENTERED` so the formulas evaluate. Errors and Health rows are still written `RAW`.

## 2026-09-11 — Ticks wait for session-boundary cancel callbacks

Backfilled on 2026-10-08 from PR #36 (both add-ons 0.1.34).

Outcome:
- IBKR could remove an order from the open-order list before sending its cancel callback. Reconciliation in that gap missed the `WORKING_SELL` and raised a false `SELL_POSITION_MISMATCH_HALT`.

Decision:
- While a session-boundary cancel the bot sent has no callback yet, ticks skip reconciliation and order placement.
- If a callback is still missing after 15 minutes, the bot halts with `SESSION_BOUNDARY_CANCEL_TIMEOUT_HALT`.

## 2026-09-23 — The Tracker shows total cash instead of settled cash

Backfilled on 2026-10-08 from PR #37 (both add-ons 0.1.35).

Outcome:
- Settled cash dropped for a while after each trade, which made the Sheet's profit and loss figures misleading.

Decision:
- At the owner's request, the cash cell `C2` shows `TotalCashValue`, falling back to `TotalCashBalance`. `SettledCash` is ignored. If neither value is valid, the cell is left unchanged for that tick.

## 2026-09-26 — Gateway runs on its bundled Java runtime

Backfilled on 2026-10-08 from PR #38 (both add-ons 0.1.36). PR #39, an alternative fix, was closed unmerged.

Outcome:
- IB Gateway could fail to open, leaving a black VNC screen and the bot waiting, because IBC chose Java through `which java` and stale installer paths (as described in PR #39).

Decision:
- The image keeps Gateway's bundled JRE at `/opt/ibgateway_jre`, IBC is pointed at it, and the build checks that it runs.
- `run.sh` checks that this Java exists and runs before starting IBC, and exits with an error if not.

## 2026-09-28 — Notification when startup reconciliation passes

Backfilled on 2026-10-08 from PR #40 (both add-ons 0.1.37).

Decision:
- A new `notify_on_startup_ok` option sends one notification per start once the first reconciliation passes without a halt.

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

## 2026-10-08 — A restart keeps the live Bridge Anchor order

Outcome:
- After a restart the untracked-Bridge cleanup ran before the Tracker re-tracking, so the bot cancelled its own live Bridge order on the first tick. The next Bridge order's ID was added beside the old one on row 7, the cleanup read only the first ID, and it cancelled the new order as well. A restart went through three Bridge orders, with ticks in between when none was live. A Bridge order that had gone from the broker while the add-on was down caused the same extra place and cancel.

Decision:
- Outside the `OVERNIGHT` session, the Bridge order that row 7 names is kept and tracked again when it is live at the broker with row 7's intended terms (the same check reconciliation and Health use) and the bot has not already requested its cancel. A cancel the bot sent whose confirmation is late is therefore not undone.
- A new Bridge order's ID replaces any older `BRIDGE_BUY` ID on row 7.
- Unchanged: a bridge-like order the Tracker does not name, or a named one with other terms, halts reconciliation as an unknown order. During the `OVERNIGHT` session a Bridge order is not kept, as before.

## 2026-10-09 — A stale outside-window WORKING_BUY row is set to IDLE

Outcome:
- Leaving the active window cancels a row's BUY, and the row keeps `WORKING_BUY` until IBKR confirms the cancel. When that confirmation was lost, the order disappeared from tracking and from the broker while the row stayed `WORKING_BUY` indefinitely, with no error. A row left stale before a restart stayed the same way. The in-window path already places a new BUY for such a row; nothing handled the outside-window case.

Decision:
- The grid pass sets such a row to `IDLE` when two consecutive ticks find: the row is outside the window and not owned, its whole status is one `WORKING_BUY`, no status write is queued for it, the order is neither tracked, at the broker, nor an unresolved re-anchor BUY, broker shares match the Tracker on a fresh snapshot, and no reconciliation halt, re-anchor, trim or bridge halt is in progress. Any tick that stops earlier, the order reappearing, or a changed order ID starts the count again. Each clear writes an INFO `STALE_WORKING_BUY_CLEARED` row to the Errors tab.
- A BUY that filled silently, fully or in part, shows as a share mismatch and is never cleared this way. The existing repair owns the row only when exactly one combination of rows explains the difference; otherwise the mismatch pause stays and the row keeps its `WORKING_BUY` evidence for the operator.
- Unchanged: Bridge, trim and SELL rows, reconciliation halts, and in-window rows.

## 2026-10-10 — Sectioned Configuration page with saved settings moved automatically

Outcome:
- The Configuration page listed 37 options under their raw names in no particular order; only the notifications group had plain names and descriptions. Paper or live was set in three places (`trading_mode`, `paper_trading`, `ibkr_port`) that had to agree, the restart times mixed `23:44` and `11:48 PM`, and the time zone was free text. `run.sh` read booleans with jq's `//` operator, so a saved `false` for an option whose fallback is `true` (daily or weekly Gateway restart, log masking) was read as `true`.

Decision:
- The owner chose sections for every option, one Trading mode, 24-hour times, a US time-zone dropdown, a separate Advanced section, and identical add-ons. Options keep their names inside six sections (`account`, `google_sheet`, `strategy`, `schedule`, `notifications`, `advanced`), and every option has a plain-English name and description.
- `trading_mode` sets both the Gateway login and the bot's paper flag. `paper_trading`, `active_broker`, `ibkr_host` and `notifications.provider` leave the page. `ibkr_port` moves to Advanced and is no longer warned about when it differs from 7497 or 7496: the bot and its own Gateway always use the same configured port, and the owner's two accounts use different ports.
- Times are entered as 24-hour `HH:MM` and validated by the page. `run.sh` converts the daily restart to the `hh:mm AM/PM` form IBC requires and passes the Sunday cold restart as 24-hour `hh:mm`, the form IBC documents for it.
- Saved settings are not re-entered. On the first start of 0.1.54, `app/config/migrate_options.py` reads the saved options through the Supervisor API, saves them into the sections and restarts the add-on. A value that cannot be converted gets its new default while everything else is still moved, and the add-on stops in `dry_run` before starting the Gateway or the bot, so fixing that one field on the page loses nothing. If the saved settings cannot be read while the add-on still has placeholder settings, it stops and says not to save the page yet. No separate backup file is kept: on every path the old values either move or stay stored. This relies on Supervisor keeping saved options under their old names across a schema change, read from its source; the first real update confirms it.
- At the owner's choice, both add-ons now share the same safe fresh-install defaults: paper, `dry_run` on, `readonly_api` on and placeholder credentials. Saved settings are unaffected. `boot` stays `auto` for Account 1 and `manual` for Account 2, because changing it could stop Account 1 starting after a reboot.

## 2026-10-14 — Error alerts wait for the problem to outlast a recovery delay

Outcome:
- "Other errors" (`notify_on_errors`) alerted on the first failed engine tick and the first missing position snapshot. The nightly Gateway restart and brief IBKR outages (502/503 responses) produced these overnight even though the bot recovered on its own a minute or two later, so the alerts reported problems that were already gone.

Decision:
- `ENGINE_TICK_ERROR` and `POSITION_SNAPSHOT_UNAVAILABLE` now alert only when the problem has lasted `notifications.error_alert_delay_seconds` (default 600, ten minutes) without a successful tick or an OK snapshot. Each alerts once per episode and again only after recovery and a new full delay. `0` restores alerting on the first occurrence.
- Unchanged: every Errors-tab row is still written; `SHARE_RECONCILED` still alerts on each repair; the watchdog restart, halt and other alerts keep their own switches and timing.

## 2026-10-19 — Weekend shutdown replaces the Sunday cold restart

Outcome:
- IBC's documentation places IBKR's weekly re-authentication after Sunday 01:00 US/Eastern (Saturday 23:00 in Denver). The daily Gateway restart at 23:48 on Saturday night came after it and could not log in without IBKR Mobile approval. On 2026-10-17 the Gateway stayed logged out from 23:48; the watchdog restarted the add-on at 00:30 and the add-on retried hourly, each retry sending an IBKR Mobile push, with login, restart and Errors-tab alerts all night. The Sunday cold restart never ran as the planned weekly login, because the session was already gone.

Decision:
- The owner chose to turn the bot off for the weekend instead of tuning the alerts. With `schedule.weekend_pause_enabled` (default on), from `weekend_pause_start_friday` (default 18:15) to `weekend_pause_end_sunday` (default 09:00) in the add-on's time zone, the engine stops (one Health row with `WEEKEND_SHUTDOWN`, then the normal shutdown) and `run.sh` stops the Gateway and waits, keeping the add-on running so Home Assistant does not restart or stop it. The Sunday start is the weekly fresh login, at a time the owner can approve it.
- At the owner's choice the Sunday cold restart is removed (`gateway_cold_restart_*` leave the page and the IBC configuration); keeping it would have asked for a second approval right after the Sunday start. Saved values for it are dropped by Supervisor, and the pre-0.1.54 settings move drops them too.
- The default Friday time is after 20:00 US/Eastern, so the session boundary has already cancelled Friday's after-hours orders.
- Unchanged: the nightly maintenance window, the daily Gateway restart, the watchdog and the alert switches.

## 2026-10-19 — Gateway settings survive add-on restarts

Outcome:
- On both add-ons, every start showed the Gateway prompt "We are having trouble loading your settings, they may be corrupted", naming a missing `ibg.xml` and offering a weekday backup such as `ibg.Sun.xml`. Answering it, or choosing not to see it again, did not stick. `run.sh` copied the Gateway settings to `/data` only every 300 seconds while running and never after the Gateway stopped, and Home Assistant allowed its default 10 seconds to stop, so the Gateway's own settings file never reached `/data`. This cause is reasoned from the code and the prompt, not observed in the saved folder.

Decision:
- IBC has the Gateway save its settings hourly (`SaveTwsSettingsAt=Every 1 hours`). The owner preferred hourly to a few minutes: settings change rarely, the file is overwritten in place rather than growing, and the periodic copy then picks it up.
- `run.sh` copies the settings once more after the Gateway has stopped, and `config.yaml` sets `timeout: 60` for that.
- A startup log line says whether a saved `ibg.xml` was found and copied back and how large the saved settings are, so the operator can confirm it without opening the add-on's files.
- The two `jts.ini` lines for the precaution bypasses are removed: `jts.ini` does not hold them, and IBC already applies both through the Gateway's Configure dialog on every start. No other bypass is added and no Gateway prompt is answered automatically.

## 2026-10-20 — A half-written Gateway settings save is no longer restored

Outcome:
- After 0.1.57 the settings-recovery prompt still appeared on every start. The 0.1.58 file listing showed one settings folder holding `ibg.xml` (last written 2026-10-18 23:48, at the nightly restart), the seven weekday backups, and an `ibg.tmp.xml` from the previous run that `run.sh` had saved to `/data` and restored. The Gateway writes `ibg.tmp.xml` during a save; one left behind is a save that never finished. The hourly `SaveTwsSettingsAt` produced no newer `ibg.xml` in the 3.5-hour run before (needs verification against the IBC log).
- Working hypothesis, **needs verification**: the Gateway treats a leftover `ibg.tmp.xml` as an interrupted save and reports the settings as damaged. Because `rsync` copies without deleting, a saved `ibg.tmp.xml` came back on every start.

Decision:
- `run.sh` neither restores `ibg.tmp.xml` from `/data` nor copies it there. Copies already in `/data` stay in place and unused; nothing is deleted.
- If the prompt still appears with no `ibg.tmp.xml` present, `ibg.xml` itself is the next suspect.

## 2026-10-20 — Gateway settings prompt: log lines instead of more guesses

Outcome:
- With 0.1.59 no `ibg.tmp.xml` was present before start and the prompt still appeared. The Gateway saved a clean `ibg.xml` at the 23:48 restart on 2026-10-19; after the next full add-on restart the Gateway still called that file missing. The leftover-file hypothesis is ruled out. The bot trades normally with the prompt open.

Decision:
- The owner chose to read the Gateway's own logs. `run.sh` prints the settings-related lines from the IBC log and any plain-text Gateway log two minutes after login and after the Gateway stops, masking credentials, account IDs and the folder name. No settings file is changed.

## 2026-10-21 — Hourly Gateway settings save removed; machine identity logged

Outcome:
- The 0.1.61 log showed the Gateway checks the same settings folder `run.sh` restores, with `ibg.xml` present there, and still reports "File does not exist" for it after a full add-on restart.
- IBC logged "Saving Tws settings" at 21:00 on 2026-10-20, but `ibg.xml` kept its 2026-10-19 23:48 time. The scheduled File > Save Settings does not write `ibg.xml` for the Gateway; only the nightly restart does.
- Working hypothesis, **needs verification**: the Gateway cannot read settings written under a different machine identity, which changes when the add-on container is rebuilt, and reports the file as missing.

Decision:
- `SaveTwsSettingsAt` is removed from the IBC template; this replaces the hourly-save choice in the 2026-10-19 entry. The copy after the Gateway stops and the 300-second copy stay.
- Before the Gateway starts, `run.sh` prints 8-character SHA-256 fingerprints of the hostname, `/etc/machine-id` and network addresses, and whether each `ibg.xml` is plain XML. Values are not printed. No settings file and no machine identity is changed.

## 2026-10-21 — Gateway settings prompt: accepted as a Gateway issue; diagnostics removed

Outcome:
- With 0.1.62 the hostname and `/etc/machine-id` fingerprints stayed the same between two add-on starts, and the prompt appeared both times. It also appeared at the nightly in-container Gateway restart at 2026-10-20 23:48: the Gateway wrote `ibg.xml` while closing, then about 20 seconds later reported that same file as missing. `ibg.xml` is not plain XML (encrypted or binary). The machine-identity hypothesis is ruled out. The Gateway cannot load its own encrypted settings file, which `run.sh` cannot fix by copying files. "Don't display this message again" and "reset to default" do not stick, because they are stored in the same file. Trading is unaffected.

Decision:
- The owner chose to clean up rather than have the add-on click the prompt away; no Gateway prompt is answered automatically.
- Removed: the `ibg*.xml` file listings, the `[Gateway logs]` report and the machine-identity block added in 0.1.58–0.1.62.
- Kept: the settings restore (without `ibg.tmp.xml`), the 300-second copy, the copy after the Gateway stops, `timeout: 60`, and the one-line startup report. The prompt is documented as a known issue in `README.md`.

## 2026-10-21 — No IBC config copy in /data; xdotool removed

Outcome:
- `run.sh` copied the rendered IBC config, IBKR password included, to `/data/ibgateway/config.ini` on every start as a "diagnostic backup". Nothing read it, and `/data` is included in Home Assistant backups.
- `xdotool` was installed in the image but never used; it was left from early attempts to open the Gateway's Configure dialog with clicks and keystrokes. IBC opens that dialog itself after login to apply the API port, read-only flag, precaution bypasses and restart time.

Decision:
- The owner chose to stop writing the copy and to delete an existing one at startup. Older Home Assistant backups keep whatever they already contain.
- `xdotool` is removed from both Dockerfiles. No Gateway window is driven by the add-on.

## 2026-10-21 — Gateway launched without gatewaystart.sh

Outcome:
- `run.sh` exported launch settings that IBC's `gatewaystart.sh` then overwrote with its own hard-coded values, and the Dockerfile patched `gatewaystart.sh` (`xterm`, `JAVA_PATH`) to make it work.
- The owner keeps the one-hour Gateway wait: a missed 2FA push is retried about once an hour, through the add-on's exit and Home Assistant's restart, which suits a 09:00–18:00 approval window. Failing fast on an IBC crash was not pursued.

Decision:
- `run.sh` starts `/opt/ibc/scripts/displaybannerandlaunch.sh` directly with the values `gatewaystart.sh` used to set, including `TWOFA_TIMEOUT_ACTION=exit` and an empty `TRADING_MODE`. A side-by-side run with a stub `ibcstart.sh` gave identical arguments, environment and log file for the old and new launch. The Dockerfile no longer patches `gatewaystart.sh`. Login behavior and timing are unchanged.
