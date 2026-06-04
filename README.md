# v7 HA IBKR Bot Suite

## Purpose
This repository contains a Home Assistant compatible suite of add-ons/apps for managing multiple IBKR accounts using automated bots. It aims to integrate independent IBKR automated trading bots as Home Assistant add-ons.

## Current Status
**Repo skeleton only.** No bot code has been imported yet.

## Source Baseline
The stable source baseline for this project is the v6 repo:
- Repository: [Wakeboardsam/v6_IBKR_WebAPI](https://github.com/Wakeboardsam/v6_IBKR_WebAPI)
- Tag: `v6.3.1-Single_Account_Stable`

## Phase 1 Target Model
- **One bot instance** = **One IBKR account** = **One Google Sheet**
- *Note: We are not building a centralized multi-account supervisor yet.*

## Initial Planned Add-on Folders (For Later PRs Only)
- `ibkr_gateway`
- `tqqq_bot`

## Initial PR Sequence
- **PR 01**: repo setup skeleton
- **PR 02**: import stable v6 baseline from `v6.3.1-Single_Account_Stable`
- **PR 03**: create/validate `ibkr_gateway` add-on
- **PR 04**: create/validate one `tqqq_bot` add-on
- *Later PRs*: copy `tqqq_bot` only after first bot works

## ⚠️ Security Warning
This repository is public. **No real credentials or account IDs belong in the repo.** Please strictly use placeholders for any configuration examples or documentation. Refer to `SECURITY.md` for more details.
