# v7 HA IBKR Bot Suite

## Purpose
This repository contains a Home Assistant compatible suite of add-ons/apps for managing multiple IBKR accounts using automated bots. It aims to integrate independent IBKR automated trading bots as Home Assistant add-ons.

## Current Status
**Step 02 Scaffold Completed.**
- The repository is now an installable Home Assistant add-on repository.
- `ibkr_gateway` and `tqqq_bot` exist as installable scaffolds.
- **Note:** The add-ons currently do not execute the bot runtime or start the Gateway. Step 03 will port the real v6 `tqqq_bot` runtime. Gateway runtime/login is not active yet.

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
- **PR 03**: Port the real v6 `tqqq_bot` runtime into the scaffold
- **PR 04**: create/validate `ibkr_gateway` runtime
- *Later PRs*: copy `tqqq_bot` only after first bot works

## ⚠️ Security Warning
This repository is public. **No real credentials or account IDs belong in the repo.** Please strictly use placeholders for any configuration examples or documentation. Refer to `SECURITY.md` for more details.
