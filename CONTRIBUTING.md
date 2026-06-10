# Contributing Guidelines

- **Use feature branches**: All work should be done in dedicated branches off of `main`.
- **Keep PRs small**: Submit small, focused pull requests to make reviews easier.
- **Avoid unrelated refactors**: Do not mix structural/refactoring changes with new features, bug fixes, or documentation-only changes.
- **Do not rebuild from scratch**: Preserve the existing v7 repository and add-on folder structure unless a later task explicitly changes that direction.
- **Do not rename the repo**: The target repository remains `Wakeboardsam/V7-ha-ibkr-bot-suite`.
- **Do not create account copies yet**: Do not create account 2/account 3 add-on folders until the first bundled `tqqq_bot` path works safely.
- **Preserve v6 strategy behavior**: Do not change the existing grid strategy, Bridge Anchor behavior, TQQQ-only scope, or Google Sheets behavior unless a later task explicitly requires it for safety or packaging.
- **No secrets or real account IDs**: Ensure no sensitive data is committed. Use placeholders exclusively.
- **Merge process**: Sam will review and merge PRs into `main`.
- **Testing**: Home Assistant testing will occur from the `main` branch after merge.

## Version Bumps

Every HA-testable add-on/config/runtime merge must bump the affected add-on version so Home Assistant can detect and install the update.

Version bumps are required for changes such as:

- `config.yaml` changes
- Dockerfile changes
- `run.sh` changes
- Python runtime changes
- dependency changes
- bundled Gateway/bot runtime behavior changes

Docs-only PRs do not need add-on version bumps unless they also change add-on/config/runtime files.
