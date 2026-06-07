# Imported v6 Baseline

This directory (`v6_baseline/`) contains the clean imported baseline code from the stable v6 release.

- **Source repo**: `Wakeboardsam/v6_IBKR_WebAPI`
- **Source tag**: `v6.3.1-Single_Account_Stable`
- **Purpose**: This folder is a clean imported baseline to serve as staging and reference code for future porting to v7 Home Assistant add-ons.

## Notes
- No intentional trading strategy behavior changes were made during this import.
- No changes to account-scoping have been made.
- This codebase will be split into the respective v7 add-ons (`ibkr_gateway` and `tqqq_bot`) in future PRs.
- Secrets, logs, local state, and configuration artifacts have been sanitized to maintain repository security.
