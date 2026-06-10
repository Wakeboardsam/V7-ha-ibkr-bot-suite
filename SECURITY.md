# Security Policy

## Secrets and Sensitive Data

This public repo must never contain secrets, credentials, or real account identifiers.

Do not open GitHub issues, PRs, commits, logs, screenshots, or documentation containing:

- IBKR usernames or passwords
- real IBKR account IDs
- API tokens
- OAuth certificates
- private keys
- Google service-account files
- Google Sheet IDs
- `.env` files or `.env` secret values
- token caches
- logs or screenshots showing secrets or full account IDs

## Placeholders

Always use placeholders for sensitive configuration examples. Examples:

```yaml
ibkr_username: "placeholder_user"
ibkr_password: "placeholder_password"
ibkr_account_id: "DU1234567"
google_sheet_id: "your_google_sheet_id_here"
ibkr_client_id: 1
```

`DU1234567` is a placeholder example only. Do not commit a real IBKR account ID.

Account IDs must be masked in logs, UI output, docs, and screenshots. Example masked format:

```text
DU1****567
```

## Accidental Commits

If a secret is accidentally committed:

1. Rotate or revoke it immediately in the respective service (IBKR, Google, etc.).
2. Purge it from the repository history.
3. Review recent logs, screenshots, issues, and PR text for additional exposure.
