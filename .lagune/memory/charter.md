# JIRA MCP Server Security Charter

## Principles

### I. Secrets never live in code or version history

Never commit a secret (PAT, token, password, API key). Always load secrets from the environment or a dedicated secrets manager. The `.env` file MUST remain in `.gitignore` and MUST NOT be committed.

- Why: A leaked JIRA PAT in git history grants full account access to whoever finds it, and git history is permanent. A single exposed token can read, modify, and delete every ticket in the project.

### II. All input is untrusted until validated

Always validate and sanitize data from users, MCP tool arguments, and JIRA API responses before it reaches any URL path, HTTP header, or output. Never interpolate raw user input into URL paths or query strings without proper encoding.

- Why: Unchecked input is how injection attacks work. A malicious ticket key could inject path segments into the JIRA REST URL. Unsanitized JQL could trigger server-side errors or information disclosure.

### III. Network requests stay within the declared trust boundary

Never make HTTP requests to hosts other than the configured `JIRA_BASE_URL`. Always reject or ignore any attempt to redirect API calls to an arbitrary endpoint, whether through `.env` manipulation, argument injection, or response-driven redirection.

- Why: An attacker who can redirect the server's requests to their own host captures the Bearer token on the first call, gaining full JIRA access without needing the PAT directly.

### IV. Error messages never leak internal state

Never expose raw stack traces, file system paths, or token fragments in error responses returned to the MCP client. Always return a structured error with a safe message and, where useful, a remediation hint.

- Why: Detailed error internals reveal server layout, library versions, and partial credentials, all of which lower the cost of a targeted attack.

### V. Environment loading has no side effects on library consumers

Never mutate `os.environ` unconditionally at import time. Always guard environment bootstrap behind a flag so that tests and library importers are not silently affected.

- Why: Unguarded side effects on import can override test fixtures, mask misconfiguration, or cause non-deterministic behavior across test suites, making security regressions harder to catch.

## Baseline discipline

Lagune holds this charter, every principle, every time. A principle is not suspended because a control looks small, familiar, or unlikely to be hit. This is not a judgement call.

### Only the controls the project needs

Lagune recommends and applies only the controls this project's context calls for. A control the project does not need is never added for completeness, and a generic checklist is not thoroughness. Every later phase acts on what the system actually does, never on what it might hypothetically do.

- Why: effort spent on risks the project does not have buries the risks it does have. Fewer, right-sized controls are easier to apply, prove, and keep true than a checklist no one finishes.

### Prefer the simplest vetted control

When a control is needed, reach for the safest option already proven, in order: a control this project already has, then a platform or framework built-in, then a well-maintained vetted library, and only then custom code. Never hand-roll a security primitive (cryptography, escaping, authentication, sessions) that a vetted standard already provides. A new dependency is new attack surface, justified and not assumed. Code, an endpoint, or a feature the project does not use is attack surface too, so removing it is itself a control.

- Why: hand-rolled security is where subtle, unaudited bugs live, and a second control duplicating an existing one is the one that gets forgotten and drifts. Boring, standard controls are easier to audit and harder to get wrong, and less surface is less to defend.

### When a control seems skippable

A control is held even when a reason to skip it feels reasonable:

- "Too small to need a control": small gaps are where breaches start.
- "Already handled elsewhere": assumed coverage is exactly how gaps hide.
- "Unlikely to be hit": attackers target the path no one is watching.
- "It works, ship it": working and safe are different claims, and the charter requires both.

## Governance

This charter supersedes ad hoc security decisions made during development. Any change to a principle requires updating the version number, re-running `/lagune.detect` to check new scope, and a review by the project maintainer. The charter is the single source of truth for what "secure" means in this project.

Version: 1.0.0 | Ratified: 2026-08-12
