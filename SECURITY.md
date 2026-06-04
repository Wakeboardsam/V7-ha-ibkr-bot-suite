# Security Policy

## Secrets and Sensitive Data
This public repo **must never contain secrets or real account identifiers**.

Do not open GitHub issues or PRs containing:
- IBKR account numbers
- API keys
- OAuth certs
- Private keys
- Google service-account files
- Google Sheet IDs
- Logs or screenshots with sensitive data

## Placeholders
Always use placeholders for sensitive configuration examples. Examples:
- `ibkr_account_id: DU1234567`
- `google_sheet_id: your_google_sheet_id_here`
- `ibkr_client_id: 1`

## Accidental Commits
If a secret is accidentally committed:
1. **Rotate/revoke it immediately** in the respective service (IBKR, Google, etc.).
2. **Purge it from the repository history**.
