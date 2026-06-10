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
