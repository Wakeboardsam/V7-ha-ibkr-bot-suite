# v7 HA IBKR Bot Suite

## Purpose
This repository contains a Home Assistant compatible suite of add-ons/apps for managing multiple IBKR accounts using automated bots. It aims to integrate independent IBKR automated trading bots as Home Assistant add-ons.

## Current Status
**Step 03 Baseline Import Completed.**
- The stable source code from `v6.3.1-Single_Account_Stable` has been imported into `v6_baseline/` to serve as a clean staging area.
- The repository is an installable Home Assistant add-on repository.
- `V7_ibkr_gateway` and `V7_tqqq_bot` exist as installable scaffolds.
- **Note:** The add-ons currently do not execute the bot runtime or start the Gateway. The runtime porting and splitting into the scaffold add-ons will occur in PR 04 and beyond.

**Step 02 validation passed on Home Assistant:**
- Repository added successfully
- V7_ibkr_gateway installed and started successfully
- V7_tqqq_bot installed and started successfully
- Scaffold-only behavior confirmed
- Gateway did not start
- Bot runtime did not start
- Account ID masking confirmed as DU1****567
- No credentials or real account IDs committed

## Source Baseline
The stable source baseline for this project is the v6 repo:
- Repository: [Wakeboardsam/v6_IBKR_WebAPI](https://github.com/Wakeboardsam/v6_IBKR_WebAPI)
- Tag: `v6.3.1-Single_Account_Stable`

## Phase 1 Target Model
- **One bot instance** = **One IBKR account** = **One Google Sheet**
- *Note: We are not building a centralized multi-account supervisor yet.*

## Add-on Folders
- `ibkr_gateway`: Provides the shared IBKR Gateway / IBC service. (Scaffold only currently)
- `tqqq_bot`: The first trading bot, intended for a single IBKR account. (Scaffold only currently)

## Initial PR Sequence
- **PR 01**: repo setup skeleton
- **PR 02**: Add Home Assistant add-on scaffold for Gateway and TQQQ bot (installable, but no runtime)
- **PR 03**: Import clean v6 baseline into `v6_baseline/`
- **PR 04+**: Port/split the runtime into the v7 add-on folders (`ibkr_gateway` and `tqqq_bot`)

## ⚠️ Security Warning
This repository is public. **No real credentials or account IDs belong in the repo.** Please strictly use placeholders for any configuration examples or documentation. Refer to `SECURITY.md` for more details.
