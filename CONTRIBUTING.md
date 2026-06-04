# Contributing Guidelines

- **Use feature branches**: All work should be done in dedicated branches off of `main`.
- **Keep PRs small**: Submit small, focused pull requests to make reviews easier.
- **Avoid unrelated refactors**: Do not mix structural/refactoring changes with new features or bug fixes.
- **No secrets or real account IDs**: Ensure no sensitive data is committed. Use placeholders exclusively.
- **Preserve v6 strategy behavior**: Do not change the existing trading strategy behavior unless a later task explicitly requires it.
- **Merge process**: The user (Sam) will review and merge PRs into `main`.
- **Testing**: Home Assistant testing will occur from the `main` branch after the merge.
- **Version bumps**: Add-on version bumps will be required in later PRs when add-on files exist, but are **not required** in this skeleton PR.
