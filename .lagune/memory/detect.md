# JIRA MCP Server Detect Map

- **Scope:** Full project scan
- **Mapped:** 2026-08-12

## Findings

### Bearer token in every outbound request

- **What it is:** Every API call to JIRA includes the `JIRA_PAT` as a Bearer token in the Authorization header. The token is loaded from the environment and sent over HTTP to whatever URL is configured in `JIRA_BASE_URL`.
- **Why it matters:** If `JIRA_BASE_URL` is misconfigured (typo, attacker-controlled, or HTTP instead of HTTPS), the PAT leaks to the wrong host on the very first request. The token grants full read/write access to the JIRA project.
- **Evidence:** The `_api_request` function, which builds every outgoing request, reads the PAT and attaches it as a header unconditionally without verifying the destination scheme or host.

### No HTTPS enforcement on outbound requests

- **What it is:** The server constructs URLs from `JIRA_BASE_URL` and opens them with `urllib.request.urlopen`. There is no check that the URL scheme is HTTPS.
- **Why it matters:** A misconfigured or maliciously overridden `JIRA_BASE_URL` using plain HTTP would transmit the Bearer token and all ticket data in cleartext, visible to any network observer.
- **Evidence:** The `_api_request` function, where the URL is opened without any scheme validation before making the request.

### Ticket key validated but JQL passed through unescaped

- **What it is:** Ticket keys are validated against a strict regex (`^[A-Z][A-Z0-9]+-\d+$`). However, the `jql` parameter in `jira_search` is URL-encoded but otherwise passed directly to the JIRA search endpoint without any sanitization.
- **Why it matters:** While JIRA's server-side JQL parser handles this, passing arbitrary user-constructed strings directly to a remote API means any JIRA-side JQL injection or unexpected behavior (e.g., information disclosure across projects) is not mitigated client-side.
- **Evidence:** The `jira_search` tool function and `_fetch_issues` helper, where `jql` is URL-encoded via `urllib.parse.quote` and concatenated into the request URL.

### Error responses may expose internal details

- **What it is:** When a JIRA API call fails, the error handler reads the response body and includes it (up to 300 characters) in the RuntimeError message. This message is returned to the MCP client.
- **Why it matters:** JIRA error responses can contain internal server details, stack traces, or partial configuration information. Forwarding these to the MCP client (and ultimately to the AI agent and user) leaks information that should stay internal to the JIRA instance.
- **Evidence:** The except block in `_api_request`, which reads `e.read().decode()` and includes a truncated slice in the raised exception.

### .env file loader reads from a fixed path

- **What it is:** The `_load_env` function reads and parses a `.env` file from the same directory as the script. Any key-value pair in that file that is not already in the environment is injected into `os.environ`.
- **Why it matters:** An attacker with write access to the `server/` directory (e.g., via a compromised dependency, CI artifact, or shared filesystem) can drop a `.env` file that overrides `JIRA_BASE_URL` to point at an attacker-controlled server, capturing the PAT on the next run.
- **Evidence:** The `_load_env` function, which resolves the path via `pathlib.Path(__file__).parent / ".env"` and sets values in `os.environ` without verifying file ownership or permissions.

### No request timeout surfaced to the user

- **What it is:** All HTTP requests use a hardcoded 30-second timeout. If JIRA is slow or unreachable, the MCP tool hangs for up to 30 seconds with no feedback to the caller.
- **Why it matters:** A hanging tool call provides a poor user experience and, in the case of a deliberately slow server (e.g., Slowloris-style), could be used to exhaust connection resources or stall agent workflows.
- **Evidence:** The `urllib.request.urlopen(req, timeout=30)` call in `_api_request`.

### URL construction via string concatenation

- **What it is:** API endpoint URLs are built by concatenating a base URL constant with path segments and query parameters using f-strings and manual `urllib.parse.quote` calls.
- **Why it matters:** While ticket keys are validated, any future tool that accepts a string parameter not guarded by the same regex (e.g., a component name, sprint name, or username with special characters) could produce malformed or injectable URLs if not properly encoded.
- **Evidence:** The `_jira_get`, `_jira_post`, `_jira_put` helpers and all tool functions that build path strings like `f"/issue/{_validate_key(ticket)}"` or `f"/board?projectKeyOrId={PROJECT}"`.

## Applied sub-skills

None. No sub-skills are installed in this project.

