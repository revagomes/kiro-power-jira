# JIRA MCP Server Defense Plan

- **Scope:** All detect findings
- **Planned:** 2026-08-12

## Fixes

### Bearer token in every outbound request

- **Category:** Credential exposure to untrusted host (CWE-522)
- **CVSS:** CVSS:4.0/AV:N/AC:L/AT:P/PR:N/UI:N/VC:H/VI:H/VA:N/SC:N/SI:N/SA:N (8.2, High)
- **Priority:** High
- **Why this priority:** The PAT grants full read/write to the JIRA project. An attacker who controls the configured URL (via .env override or misconfiguration) captures it on the first call. Rated below Critical because an attacker must first control the base URL configuration, not just reach the service.
- **Upholds:** Secrets never live in code or version history, Network requests stay within the declared trust boundary
- **Depends on:** No HTTPS enforcement on outbound requests
- **Fix:** Before sending the first request, validate that `JIRA_BASE_URL` uses the HTTPS scheme. Reject `http://` URLs at startup (in `_check_config`) with a clear error message. This ensures the token is never sent in cleartext, regardless of misconfiguration.
- **References:** [CWE-522: Insufficiently Protected Credentials](https://cwe.mitre.org/data/definitions/522.html)

### No HTTPS enforcement on outbound requests

- **Category:** Cleartext transmission of sensitive data (CWE-319)
- **CVSS:** CVSS:4.0/AV:N/AC:L/AT:P/PR:N/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N (7.7, High)
- **Priority:** High
- **Why this priority:** The server transmits a Bearer token and potentially sensitive ticket data. A network observer (MITM on an untrusted network) can read everything in transit if HTTP is used. Requires the user to have misconfigured the URL as HTTP, but the code does nothing to prevent it.
- **Upholds:** Network requests stay within the declared trust boundary
- **Fix:** Add a scheme check in `_check_config` that rejects any `JIRA_BASE_URL` not starting with `https://`. Raise a clear RuntimeError at startup: "JIRA_BASE_URL must use HTTPS to protect credentials in transit."
- **References:** [CWE-319: Cleartext Transmission of Sensitive Information](https://cwe.mitre.org/data/definitions/319.html)

### Error responses may expose internal details

- **Category:** Information exposure through error message (CWE-209)
- **CVSS:** CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N (6.9, Medium)
- **Priority:** Medium
- **Why this priority:** Error messages from JIRA could contain internal hostnames, stack traces, or partial configuration. The exposure is informational (Low confidentiality), but the surface is reachable by anyone who can call an MCP tool, which is any user of the agent.
- **Upholds:** Error messages never leak internal state
- **Fix:** Sanitize JIRA error responses before raising. Extract only the JIRA `errorMessages` array (user-facing messages JIRA already intends to show). Drop the raw body fallback or limit it to a generic "JIRA returned an error (HTTP {code})" without the body content. Log the full body to stderr for debugging if needed, but never surface it to the MCP client.
- **References:** [CWE-209: Generation of Error Message Containing Sensitive Information](https://cwe.mitre.org/data/definitions/209.html)

### .env file loader reads from a fixed path

- **Category:** Untrusted search path for configuration (CWE-426)
- **CVSS:** CVSS:4.0/AV:L/AC:L/AT:P/PR:L/UI:N/VC:H/VI:H/VA:N/SC:N/SI:N/SA:N (5.4, Medium)
- **Priority:** Medium
- **Why this priority:** Requires local write access to the `server/` directory, which limits the attack surface to compromised dependencies or shared-filesystem scenarios. However, success means full JIRA PAT capture, so the impact is high while the reach is local.
- **Upholds:** Secrets never live in code or version history, Network requests stay within the declared trust boundary
- **Fix:** Document the trust assumption clearly in the function's docstring: the .env file is trusted local-only configuration and must not be writable by untrusted parties. Additionally, after loading, re-validate that `JIRA_BASE_URL` is HTTPS (covered by the HTTPS enforcement fix). Optionally log a warning to stderr when a .env file is loaded, so the operator knows configuration came from a file rather than the environment.
- **References:** [CWE-426: Untrusted Search Path](https://cwe.mitre.org/data/definitions/426.html)

### Ticket key validated but JQL passed through unescaped

- **Category:** Improper neutralization of special elements in query (CWE-943)
- **CVSS:** CVSS:4.0/AV:N/AC:L/AT:P/PR:L/UI:N/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N (2.4, Low)
- **Priority:** Low
- **Why this priority:** JQL is parsed server-side by JIRA, which has its own input validation. The risk is limited to JIRA returning unexpected cross-project data if the user's JIRA account has broader permissions than intended. The MCP tool user already has authenticated access to JIRA through the configured PAT, so the elevation is minimal.
- **Upholds:** All input is untrusted until validated
- **Fix:** Add a basic JQL sanitization: reject JQL strings containing control characters or null bytes (which have no legitimate use). Document that the JQL is executed with the permissions of the configured PAT and that cross-project queries are constrained by JIRA's permission model, not by this client.
- **References:** [CWE-943: Improper Neutralization of Special Elements in Data Query Logic](https://cwe.mitre.org/data/definitions/943.html)

### URL construction via string concatenation

- **Category:** Improper neutralization of special elements in URL path (CWE-116)
- **CVSS:** CVSS:4.0/AV:N/AC:L/AT:P/PR:L/UI:N/VC:L/VI:L/VA:N/SC:N/SI:N/SA:N (2.4, Low)
- **Priority:** Low
- **Why this priority:** Currently all user-facing path segments go through `_validate_key` which enforces a strict alphanumeric+dash regex. The risk is latent: future tools that accept free-text parameters (component names, usernames) could introduce path injection if they don't encode. Currently mitigated by validation, so this is preventive.
- **Upholds:** All input is untrusted until validated
- **Fix:** Introduce a `_quote_path` helper that applies `urllib.parse.quote(value, safe='')` to any value inserted into a URL path segment. Apply it to the `PROJECT` constant in board/sprint queries and to any future parameters. This makes the protection structural rather than relying on each caller to remember.
- **References:** [CWE-116: Improper Encoding or Escaping of Output](https://cwe.mitre.org/data/definitions/116.html)

### No request timeout surfaced to the user

- **Category:** Uncontrolled resource consumption (CWE-400)
- **CVSS:** CVSS:4.0/AV:N/AC:L/AT:P/PR:N/UI:N/VC:N/VI:N/VA:L/SC:N/SI:N/SA:N (6.3, Medium)
- **Priority:** Low
- **Why this priority:** The 30-second timeout exists and prevents indefinite hangs. The impact is limited to availability (a stalled tool call) and does not compromise data. The risk is primarily UX degradation, not a security breach. Downgraded from Medium score because the existing timeout bounds the worst case.
- **Upholds:** None directly
- **Fix:** This is informational. The existing 30-second timeout is adequate. Optionally, add a comment documenting why 30 seconds was chosen and consider making it configurable via an environment variable for deployments with known-slow JIRA instances.

