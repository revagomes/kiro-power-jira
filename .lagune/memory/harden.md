# JIRA MCP Server Hardening Record

- **Scope:** All fixes from the defense plan
- **Hardened:** 2026-08-12

## Applied

### No HTTPS enforcement on outbound requests

- **Status:** Applied
- **What changed:** Added an HTTPS scheme check in `_check_config` that raises a clear RuntimeError if `JIRA_BASE_URL` does not start with `https://`. The server now refuses to start with an HTTP URL.
- **Where:** The `_check_config` function, after the missing-variable checks.
- **Verdict:** Pending

### Bearer token in every outbound request

- **Status:** Applied
- **What changed:** The HTTPS enforcement above ensures the Bearer token is never sent over cleartext. The check runs on every API call (via `_get_pat` -> `_check_config`), blocking any request to a non-HTTPS endpoint.
- **Where:** The `_check_config` function (same control as the HTTPS finding — the dependency is structural).
- **Verdict:** Pending

### Error responses may expose internal details

- **Status:** Applied
- **What changed:** Sanitized the error handler in `_api_request`. When JIRA returns structured JSON errors, only the `errorMessages` and `errors` values (JIRA's user-facing messages) are surfaced. When the response is not JSON or has no user-facing messages, a generic "request failed" message is returned instead of the raw response body.
- **Where:** The `except urllib.error.HTTPError` block in `_api_request`.
- **Verdict:** Pending

### .env file loader reads from a fixed path

- **Status:** Applied
- **What changed:** Added a trust assumption section to the `_load_env` docstring documenting that the .env file must not be writable by untrusted parties. Added a stderr warning log when a .env file is loaded so operators know configuration came from a file. The HTTPS enforcement also mitigates redirection attacks via .env override.
- **Where:** The `_load_env` function docstring and the file-loading block.
- **Verdict:** Pending

### Ticket key validated but JQL passed through unescaped

- **Status:** Applied
- **What changed:** Added a `_validate_jql` function that rejects JQL strings containing null bytes or control characters (except tab, newline, carriage return). Wired it into `_fetch_issues` so all JQL-based queries pass through validation at the chokepoint.
- **Where:** The new `_validate_jql` helper and the top of `_fetch_issues`.
- **Verdict:** Pending

### URL construction via string concatenation

- **Status:** Applied
- **What changed:** Added a `_quote_path` helper that applies `urllib.parse.quote(value, safe='')` for safe URL segment encoding. Applied it to the `PROJECT` value in the `jira_boards` query parameter. Ticket keys were already safe (strict regex), and the helper is now available for any future parameter.
- **Where:** The new `_quote_path` helper and the `jira_boards` tool function.
- **Verdict:** Pending

### No request timeout surfaced to the user

- **Status:** Applied
- **What changed:** Added a code comment documenting why the 30-second timeout was chosen and noting it is adequate for normal API calls. No code behavior change — this is informational hardening.
- **Where:** The `urllib.request.urlopen` call in `_api_request`.
- **Verdict:** Pending

## Remaining

None. All planned fixes were fully applied.
