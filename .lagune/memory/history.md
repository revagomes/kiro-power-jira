# Lagune History

## Closed findings

### Bearer token in every outbound request

- **Classification:** High
- **Category:** Credential exposure to untrusted host (CWE-522)
- **What it is:** Every API call to JIRA includes the `JIRA_PAT` as a Bearer token in the Authorization header. The token is loaded from the environment and sent over HTTP to whatever URL is configured in `JIRA_BASE_URL`.
- **Closed:** 2026-08-12

### No HTTPS enforcement on outbound requests

- **Classification:** High
- **Category:** Cleartext transmission of sensitive data (CWE-319)
- **What it is:** The server constructs URLs from `JIRA_BASE_URL` and opens them with `urllib.request.urlopen`. There is no check that the URL scheme is HTTPS.
- **Closed:** 2026-08-12

### Ticket key validated but JQL passed through unescaped

- **Classification:** Low
- **Category:** Improper neutralization of special elements in query (CWE-943)
- **What it is:** Ticket keys are validated against a strict regex (`^[A-Z][A-Z0-9]+-\d+$`). However, the `jql` parameter in `jira_search` is URL-encoded but otherwise passed directly to the JIRA search endpoint without any sanitization.
- **Closed:** 2026-08-12

### Error responses may expose internal details

- **Classification:** Medium
- **Category:** Information exposure through error message (CWE-209)
- **What it is:** When a JIRA API call fails, the error handler reads the response body and includes it (up to 300 characters) in the RuntimeError message. This message is returned to the MCP client.
- **Closed:** 2026-08-12

### .env file loader reads from a fixed path

- **Classification:** Medium
- **Category:** Untrusted search path for configuration (CWE-426)
- **What it is:** The `_load_env` function reads and parses a `.env` file from the same directory as the script. Any key-value pair in that file that is not already in the environment is injected into `os.environ`.
- **Closed:** 2026-08-12

### No request timeout surfaced to the user

- **Classification:** Low
- **Category:** Uncontrolled resource consumption (CWE-400)
- **What it is:** All HTTP requests use a hardcoded 30-second timeout. If JIRA is slow or unreachable, the MCP tool hangs for up to 30 seconds with no feedback to the caller.
- **Closed:** 2026-08-12

### URL construction via string concatenation

- **Classification:** Low
- **Category:** Improper neutralization of special elements in URL path (CWE-116)
- **What it is:** API endpoint URLs are built by concatenating a base URL constant with path segments and query parameters using f-strings and manual `urllib.parse.quote` calls.
- **Closed:** 2026-08-12
