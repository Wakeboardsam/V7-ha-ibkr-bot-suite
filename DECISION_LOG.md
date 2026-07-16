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
