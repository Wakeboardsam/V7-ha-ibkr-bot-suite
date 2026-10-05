# CLAUDE.md

Working instructions for AI agents in this repository. Read [`README.md`](README.md) first: it is the authoritative guide to the architecture, trading behavior, configuration and development commands. This file does not repeat it.

This repository operates a live-capable trading bot. When unsure, stop and ask rather than guess.

## Scope and intended behavior

- Keep each change small and focused: one problem per branch and pull request, and no unrelated refactors.
- Preserve the intended strategy: grid logic, Bridge Anchor behavior, TQQQ-only scope and Google Sheets behavior stay as they are unless the task explicitly requires a safety or packaging change.
- Do not rebuild the project, rename the repository, or reorganize the add-on folders.
- Current code shows what is implemented, not necessarily what is intended or correct. When code and documentation disagree, report the conflict instead of silently choosing one.

## Account isolation and secrets

- One add-on instance serves one IBKR account and one Google Sheet. Never weaken account scoping, account-ID masking, or the refusal to trade without a configured account.
- This repository is public. Never commit credentials, real account IDs, real Sheet IDs, service-account files, keys, tokens, `.env` files, or logs and screenshots that contain them. Use the placeholders listed in `README.md` and `SECURITY.md`.

## Two add-ons stay in parity

- `tqqq_bot` is the reference. A production-code change goes into `tqqq_bot_account_2` in the same pull request, and `scripts/check_addon_parity.py` must pass.
- Keep Account 2's committed safe defaults. `scripts/validate_account_addons.py` enforces them.

## Testing

- Do not delete, skip or weaken existing tests or assertions to get a result.
- Production-code changes: run the tests for the changed code, the full suites for both add-ons, the parity check and the configuration validation before pushing. The commands are in the "Development and operations" section of `README.md`.
- Report results exactly. Compare against the baseline recorded in `README.md`, and say which failures are new, which already existed, and which checks you could not run.
- Documentation-only changes: check links, referenced paths and commands, and confirm the diff touches no code, configuration or version.

## Version bumps and decision log

- Bump the affected add-on's `config.yaml` version for any change Home Assistant must detect, as listed in `README.md`. Documentation-only changes need no bump.
- Add a `DECISION_LOG.md` entry when halt, circuit-breaker or reconciliation behavior changes, and for other significant behavior decisions. Keep earlier entries and their dates unchanged. Routine wording edits need none.
- Keep `README.md` accurate: update it in the same pull request when a change alters behavior it describes.

## Review and reporting

- Back every reported problem with evidence: file and line, the scenario that triggers it, and whether a test demonstrates it or it is only reasoning. Mark anything unproven **needs verification**, and do not present a suspicion as a confirmed bug.
- Use feature branches off `main` and the pull request template (`.github/pull_request_template.md`), including rollback impact and the checks actually run.
- Push only to the branch you were assigned. Open a pull request only when asked. Never merge, enable auto-merge, or deploy: the repository owner reviews and merges.
