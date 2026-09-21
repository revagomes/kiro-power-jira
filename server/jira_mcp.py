#!/usr/bin/env python3
"""
JIRA MCP Server — generic, project-agnostic.

Exposes JIRA ticket management as MCP tools over stdio transport.
Works with any JIRA instance (Cloud or Server) via REST API v2.

Configuration via environment variables:
    JIRA_PAT      — (required) Personal access token
    JIRA_BASE_URL — (required) JIRA instance URL, e.g. https://jira.example.com
    JIRA_PROJECT  — (required) Default project key, e.g. MYPROJ

Run via:
    uvx --from fastmcp fastmcp run server/jira_mcp.py
"""

import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from fastmcp import FastMCP


class JiraApiError(RuntimeError):
    """A JIRA REST API error carrying the HTTP status code.

    Subclasses RuntimeError so existing ``except RuntimeError`` handlers keep
    working, while callers that need to branch on the status (e.g. detecting an
    unknown link type via 404) can inspect ``.status`` precisely instead of
    substring-matching the formatted message.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# ── Environment bootstrap ─────────────────────────────────────────────────────
def _unquote(value: str) -> str:
    """Strip balanced surrounding quotes from a value (single or double)."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        return value[1:-1]
    return value


def _parse_env_value(raw: str) -> str:
    """Parse a .env value: strip inline comments (outside quotes), then unquote.

    Inline comments are recognised as ' #' (space + hash) only when the value
    is not quoted.  Quoted values are returned verbatim (minus the quotes).
    """
    raw = raw.strip()
    # If the value starts with a quote, find the matching closing quote.
    if raw and raw[0] in ("\"", "'"):
        quote = raw[0]
        end = raw.find(quote, 1)
        if end != -1:
            return raw[1:end]
        # No closing quote — return as-is without the opening quote.
        return raw[1:]
    # Unquoted value: strip trailing inline comment (space + #).
    if " #" in raw:
        raw = raw[: raw.index(" #")]
    return raw.strip()


def _load_env() -> None:
    """Bootstrap environment variables from a .env file next to this script.

    Resolution order for each variable:
      1. Already set in os.environ (e.g. shell export or MCP env block)
      2. Loaded from a .env file next to this script
      3. Known aliases (JIRA_URL -> JIRA_BASE_URL)

    Supports:
      - Comments (lines starting with #)
      - Blank lines
      - export prefix (``export KEY=VALUE``)
      - Balanced single/double quoting
      - Inline comments (`` # ...``) for unquoted values

    Will NOT overwrite variables already present in the environment.

    Trust assumption:
      The .env file is trusted local-only configuration. It MUST NOT be
      writable by untrusted parties. The file grants control over
      JIRA_BASE_URL and JIRA_PAT — an attacker with write access to
      server/.env can redirect API calls and capture the token.
    """
    env_path = pathlib.Path(__file__).parent / ".env"
    if env_path.is_file():
        print(
            f"[jira-mcp] Loading configuration from {env_path}",
            file=sys.stderr,
        )
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip optional 'export' prefix.
            if line.startswith("export "):
                line = line[7:]
            if "=" not in line:
                continue
            key, _, raw_value = line.partition("=")
            key = key.strip()
            value = _parse_env_value(raw_value)
            # Don't overwrite vars already in the environment.
            if key and key not in os.environ:
                os.environ[key] = value

    # Fallback: JIRA_URL -> JIRA_BASE_URL (common alias).
    if not os.environ.get("JIRA_BASE_URL") and os.environ.get("JIRA_URL"):
        os.environ["JIRA_BASE_URL"] = os.environ["JIRA_URL"]


# Only bootstrap .env when running as the MCP server (not when imported as a
# library, e.g. in tests).  When executed via ``fastmcp run``, __name__ is
# "__main__" at the module level — but FastMCP actually executes the file as a
# script, so we guard on a module-level flag that tests can disable.
if os.environ.get("_JIRA_MCP_SKIP_ENV") != "1":
    _load_env()

# ── Config (all from environment) ─────────────────────────────────────────────
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "")
JIRA_BASE = f"{JIRA_BASE_URL}/rest/api/2" if JIRA_BASE_URL else ""
JIRA_AGILE_BASE = f"{JIRA_BASE_URL}/rest/agile/1.0" if JIRA_BASE_URL else ""
JIRA_BROWSE = f"{JIRA_BASE_URL}/browse" if JIRA_BASE_URL else ""
PROJECT = os.environ.get("JIRA_PROJECT", "")

# Regex for validating JIRA ticket keys
TICKET_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")

FIELDS_FULL = (
    "summary,description,status,priority,assignee,reporter,"
    "labels,components,fixVersions,issuetype,comment,"
    "created,updated,resolution,issuelinks"
)
FIELDS_LIST = "summary,status,priority,assignee,issuetype,updated"

# ── MCP Server ────────────────────────────────────────────────────────────────
_server_name = f"JIRA {PROJECT}" if PROJECT else "JIRA"
mcp = FastMCP(_server_name)


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def _check_config() -> None:
    """Validate that all required config is available.

    Checks the module-level constants (which are the values actually used by
    API calls) rather than live os.environ, to stay self-consistent.
    Also enforces HTTPS to prevent credential leakage over cleartext.
    """
    missing = []
    if not os.environ.get("JIRA_PAT"):
        missing.append("JIRA_PAT")
    if not JIRA_BASE_URL:
        missing.append("JIRA_BASE_URL")
    if not PROJECT:
        missing.append("JIRA_PROJECT")
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            f"Set them in the mcp.json env block or export in your shell.\n"
            f"  Example:\n"
            f"    export JIRA_PAT=your-token\n"
            f"    export JIRA_BASE_URL=https://jira.example.com\n"
            f"    export JIRA_PROJECT=MYPROJ"
        )
    # Enforce HTTPS to prevent transmitting the Bearer token in cleartext.
    if JIRA_BASE_URL and not JIRA_BASE_URL.startswith("https://"):
        raise RuntimeError(
            "JIRA_BASE_URL must use HTTPS to protect credentials in transit. "
            f"Got: {JIRA_BASE_URL!r}. "
            "Change it to start with https:// ."
        )


def _validate_key(ticket: str) -> str:
    """Validate and normalize a JIRA ticket key."""
    normalized = ticket.strip().upper()
    if not TICKET_KEY_RE.match(normalized):
        raise ValueError(
            f"Invalid ticket key: '{ticket}'. Expected format: PROJECT-123"
        )
    return normalized


def _validate_jql(jql: str) -> str:
    """Validate a JQL string: reject control characters and null bytes.

    JQL is parsed server-side by JIRA. This client-side check prevents
    obviously malformed input from reaching the API. Cross-project queries
    are constrained by JIRA's permission model (the configured PAT's access),
    not by this client.
    """
    if "\x00" in jql or any(
        c != "\n" and c != "\r" and c != "\t" and ord(c) < 32 for c in jql
    ):
        raise ValueError(
            "Invalid JQL: contains control characters or null bytes."
        )
    return jql


def _get_pat() -> str:
    """Get JIRA PAT from environment."""
    _check_config()
    return os.environ["JIRA_PAT"]


def _quote_path(value: str) -> str:
    """URL-encode a value for safe inclusion in a URL path or query parameter.

    Applies percent-encoding to all special characters (including /, ?, #, &)
    so the value cannot break out of its path segment or query parameter slot.
    """
    return urllib.parse.quote(value, safe="")


# ── HTTP: block cross-host redirects (SSO gateway detection) ──────────────────
class _SSORedirectError(Exception):
    """Raised when an API request is redirected to a different host.

    Instances behind an interactive SSO reverse proxy (EU Login/ECAS, Okta,
    SiteMinder, etc.) answer API calls with a 30x to a login host. urllib
    would silently follow it to an HTML page, producing a confusing JSON parse
    error downstream. We stop at the first cross-host hop and carry an
    actionable message.
    """


class _NoCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that refuses to follow redirects leaving the origin host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old_host = urllib.parse.urlparse(req.full_url).netloc
        new_host = urllib.parse.urlparse(newurl).netloc
        if new_host and new_host != old_host:
            raise _SSORedirectError(
                f"Request to JIRA was redirected to a different host "
                f"('{new_host}'). This instance appears to be behind an "
                f"interactive SSO gateway that does not honor Personal Access "
                f"Token auth. PAT-only access is not supported for this "
                f"deployment."
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_NoCrossHostRedirect())


def _api_request(
    url: str, method: str = "GET", payload: dict | None = None
) -> dict | list:
    """Authenticated request to JIRA REST API."""
    pat = _get_pat()
    headers = {"Authorization": f"Bearer {pat}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        # 30-second timeout bounds worst-case hang when JIRA is slow or
        # unreachable.  Adequate for all normal API calls including search
        # pagination.  Not currently configurable — revisit if deployments
        # with known-slow instances need a longer window.
        #
        # Uses a custom opener that refuses cross-host redirects so an SSO
        # gateway bouncing us to a login host surfaces as a clear error
        # instead of a downstream JSON parse failure.
        with _OPENER.open(req, timeout=30) as resp:
            body = resp.read()
            if not body:
                return {}
            # A JIRA API endpoint returns JSON.  If we got HTML (or anything
            # else), we were almost certainly served a login/redirect page by
            # a proxy in front of JIRA rather than real API data.
            ctype = resp.headers.get("Content-Type", "")
            if "json" not in ctype.lower():
                raise RuntimeError(
                    f"Expected JSON from JIRA but received "
                    f"'{ctype or 'unknown content type'}' from {resp.geturl()}. "
                    f"The instance may be behind an SSO/login page; Personal "
                    f"Access Token auth may not be honored for this deployment."
                )
            try:
                return json.loads(body)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"JIRA returned a non-JSON response from {resp.geturl()} "
                    f"(likely an SSO/HTML login page rather than API data)."
                ) from e
    except _SSORedirectError as e:
        raise RuntimeError(str(e)) from e
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            err = json.loads(body)
            # Surface only JIRA's user-facing error messages, not raw internals.
            msgs = err.get("errorMessages", []) + list(
                err.get("errors", {}).values()
            )
            if msgs:
                raise JiraApiError(
                    f"JIRA API error ({e.code}): {'; '.join(msgs)}",
                    status=e.code,
                ) from e
            # Structured response but no user-facing messages — generic error.
            raise JiraApiError(
                f"JIRA API error ({e.code}): request failed", status=e.code
            ) from e
        except (json.JSONDecodeError, AttributeError):
            # Do not leak raw response body — it may contain internal details.
            raise JiraApiError(
                f"JIRA API error ({e.code}): request failed "
                f"(non-JSON response from server)",
                status=e.code,
            ) from e
    except urllib.error.URLError as e:
        raise JiraApiError(f"Connection failed: {e.reason}", status=None) from e


def _jira_get(path: str) -> dict | list:
    return _api_request(f"{JIRA_BASE}{path}")


def _jira_post(path: str, payload: dict) -> dict:
    return _api_request(f"{JIRA_BASE}{path}", method="POST", payload=payload)


def _jira_put(path: str, payload: dict) -> dict:
    return _api_request(f"{JIRA_BASE}{path}", method="PUT", payload=payload)


def _jira_delete(path: str) -> dict:
    return _api_request(f"{JIRA_BASE}{path}", method="DELETE")


def _agile_get(path: str) -> dict | list:
    return _api_request(f"{JIRA_AGILE_BASE}{path}")


def _agile_post(path: str, payload: dict) -> dict:
    return _api_request(f"{JIRA_AGILE_BASE}{path}", method="POST", payload=payload)


def _valid_link_type_names() -> list[str]:
    """Return the list of issue-link type names defined on this instance.

    Used to produce an actionable error when a caller supplies a link type the
    instance does not recognise. Best-effort: on any failure, returns an empty
    list rather than masking the original error.
    """
    try:
        data = _jira_get("/issueLinkType")
    except RuntimeError:
        return []
    if not isinstance(data, dict):
        return []
    return [
        t["name"]
        for t in data.get("issueLinkTypes", [])
        if isinstance(t, dict) and t.get("name")
    ]


_RAW_CUSTOMFIELD_RE = re.compile(r"^customfield_\d+$")

# Module-level cache of the instance's field catalog. Populated lazily on first
# resolution and reused for the process lifetime (field ids are stable at
# runtime). Stored as a tuple of (lookup_map, display_names):
#   lookup_map:  lower-cased field name → field id (case-insensitive exact match)
#   display_names: original field names, preserved for actionable error messages
_FIELD_CACHE: tuple[dict[str, str], list[str]] | None = None


def _reset_field_cache() -> None:
    """Clear the cached field catalog. Primarily for tests."""
    global _FIELD_CACHE
    _FIELD_CACHE = None


def _load_field_catalog() -> tuple[dict[str, str], list[str]]:
    """Fetch and cache the instance field catalog.

    Returns (lookup_map, display_names). Never caches a failure: if the API
    call raises, the cache stays empty so a subsequent call retries rather than
    serving a poisoned negative result.
    """
    global _FIELD_CACHE
    if _FIELD_CACHE is not None:
        return _FIELD_CACHE
    data = _jira_get("/field")  # may raise; intentionally not cached on failure
    lookup: dict[str, str] = {}
    names: list[str] = []
    if isinstance(data, list):
        for f in data:
            if isinstance(f, dict) and f.get("name") and f.get("id"):
                name = f["name"].strip()
                lookup[name.lower()] = f["id"]
                names.append(name)
    _FIELD_CACHE = (lookup, names)
    return _FIELD_CACHE


def _resolve_field_id(name_or_id: str) -> str:
    """Resolve a human field name (or raw customfield_* id) to a field id.

    - A value already matching ``customfield_\\d+`` is returned unchanged and
      does not trigger a catalog fetch.
    - Names are matched case-insensitively but exactly (no fuzzy/substring), so
      "Epic Link" never collides with "Epic Link Status".
    - An unresolved name raises ValueError listing available field names to help
      the caller correct a typo.
    """
    candidate = name_or_id.strip()
    if _RAW_CUSTOMFIELD_RE.match(candidate):
        return candidate
    lookup, names = _load_field_catalog()
    key = candidate.lower()
    if key in lookup:
        return lookup[key]
    available = sorted(names, key=str.lower)
    raise ValueError(
        f"Unknown field '{name_or_id}'. Could not resolve it to a field id on "
        f"this JIRA instance. Available field names include: "
        f"{', '.join(available[:40])}"
        + (" …" if len(available) > 40 else "")
    )


def _apply_custom_fields(
    fields: dict, custom_fields: dict | None
) -> list[str]:
    """Merge a custom_fields map into ``fields``, resolving names to ids.

    Typed parameters already present in ``fields`` take precedence: a colliding
    custom field is skipped and its key returned in the ignored list so the
    caller can report it rather than silently overwriting.

    Returns the list of custom-field keys that were ignored due to collision.
    An empty/None map is a no-op and does not fetch the field catalog. Blank or
    whitespace-only keys are skipped and reported in the ignored list.
    """
    if not custom_fields:
        return []
    ignored: list[str] = []
    for raw_key, value in custom_fields.items():
        # Skip blank/whitespace-only keys rather than aborting the whole
        # create/update with a confusing "Unknown field ''" error.
        if not raw_key or not raw_key.strip():
            ignored.append(raw_key)
            continue
        field_id = _resolve_field_id(raw_key)
        if field_id in fields:
            ignored.append(raw_key)
            continue
        fields[field_id] = value
    return ignored


def _apply_epic_link(fields: dict, epic_link: str) -> None:
    """Resolve the instance's "Epic Link" field and set it in ``fields``.

    Raises a clear ValueError if the instance has no "Epic Link" field (e.g.
    team-managed / next-gen projects, which use the native ``parent`` field
    instead) rather than silently doing nothing.
    """
    if not epic_link:
        return
    try:
        field_id = _resolve_field_id("Epic Link")
    except ValueError as e:
        raise ValueError(
            "Cannot set epic_link: this JIRA instance has no 'Epic Link' field. "
            "Team-managed/next-gen projects use the native 'parent' field instead "
            "— set it via custom_fields={'parent': {'key': '<EPIC-KEY>'}}."
        ) from e
    fields[field_id] = epic_link


def _apply_story_points(fields: dict, story_points: float | None) -> None:
    """Resolve the instance's "Story Points" field and set it in ``fields``.

    ``None`` means "not provided" and is a no-op; ``0`` is a valid value and is
    applied. Raises a clear ValueError if the instance has no such field.
    """
    if story_points is None:
        return
    try:
        field_id = _resolve_field_id("Story Points")
    except ValueError as e:
        raise ValueError(
            "Cannot set story_points: this JIRA instance has no 'Story Points' "
            "field. Set the correct field via custom_fields instead."
        ) from e
    fields[field_id] = story_points


def _epic_link_field_id_or_none() -> str | None:
    """Best-effort resolution of the Epic Link field id for read paths.

    Returns None (instead of raising) when the instance has no Epic Link field
    or the catalog cannot be loaded, so read operations degrade gracefully.
    """
    try:
        return _resolve_field_id("Epic Link")
    except (ValueError, RuntimeError):
        return None


def _fetch_issues(
    jql: str, fields: str = FIELDS_LIST, max_results: int = 50
) -> list:
    """Fetch issues with pagination. Hard cap at 1000 to prevent runaway."""
    _validate_jql(jql)
    issues: list = []
    start = 0
    hard_cap = 1000
    while True:
        page_size = min(max_results - len(issues), 50)
        if page_size <= 0:
            break
        encoded = urllib.parse.quote(jql)
        data = _jira_get(
            f"/search?jql={encoded}&startAt={start}"
            f"&maxResults={page_size}&fields={fields}"
        )
        batch = data.get("issues", [])
        issues.extend(batch)
        if len(issues) >= data.get("total", 0) or not batch:
            break
        if len(issues) >= hard_cap:
            break
        start += len(batch)
        time.sleep(0.2)
    return issues


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def jira_view(ticket: str) -> dict:
    """View a JIRA ticket with full details including description, comments, and links.

    Args:
        ticket: Ticket key, e.g. PROJ-1234
    """
    key = _validate_key(ticket)
    # Resolve the instance-specific Epic Link field id (best-effort) so we can
    # request and surface it for read-back. Degrades gracefully if absent.
    epic_field_id = _epic_link_field_id_or_none()
    requested_fields = FIELDS_FULL
    if epic_field_id:
        requested_fields = f"{FIELDS_FULL},{epic_field_id}"
    data = _jira_get(f"/issue/{key}?fields={requested_fields}")
    f = data["fields"]
    epic_link = ""
    if epic_field_id:
        epic_link = f.get(epic_field_id) or ""
    result = {
        "key": data["key"],
        "url": f"{JIRA_BROWSE}/{data['key']}",
        "summary": f.get("summary", ""),
        "type": (f.get("issuetype") or {}).get("name", ""),
        "status": (f.get("status") or {}).get("name", ""),
        "priority": (f.get("priority") or {}).get("name", ""),
        "resolution": (f.get("resolution") or {}).get("name", "Unresolved"),
        "reporter": (f.get("reporter") or {}).get("displayName", ""),
        "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
        "created": f.get("created", "")[:10],
        "updated": f.get("updated", "")[:10],
        "epic_link": epic_link,
        "labels": f.get("labels", []),
        "components": [c["name"] for c in f.get("components", [])],
        "fix_versions": [v["name"] for v in f.get("fixVersions", [])],
        "description": f.get("description") or "",
        "links": [],
        "comments": [],
    }
    for link in f.get("issuelinks", []):
        if "outwardIssue" in link:
            result["links"].append({
                "type": link["type"]["outward"],
                "ticket": link["outwardIssue"]["key"],
            })
        elif "inwardIssue" in link:
            result["links"].append({
                "type": link["type"]["inward"],
                "ticket": link["inwardIssue"]["key"],
            })
    for c in (f.get("comment") or {}).get("comments", []):
        result["comments"].append({
            "author": (c.get("author") or {}).get("displayName", "Unknown"),
            "created": c.get("created", "")[:16],
            "body": c.get("body", ""),
        })
    return result


@mcp.tool()
def jira_search(jql: str, limit: int = 50) -> list[dict]:
    """Search JIRA tickets using JQL query language.

    Args:
        jql: JQL query string, e.g. "project=PROJ AND type=Bug AND priority=P1"
        limit: Maximum number of results (default 50)
    """
    issues = _fetch_issues(jql, max_results=limit)
    results = []
    for issue in issues:
        f = issue["fields"]
        results.append({
            "key": issue["key"],
            "summary": f.get("summary", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "priority": (f.get("priority") or {}).get("name", ""),
            "type": (f.get("issuetype") or {}).get("name", ""),
            "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
            "updated": f.get("updated", "")[:10],
        })
    return results


@mcp.tool()
def jira_my_open(limit: int = 50) -> list[dict]:
    """List your currently open JIRA tickets (assigned to current user, not done).

    Args:
        limit: Maximum number of results (default 50)
    """
    jql = f"project={PROJECT} AND assignee=currentUser() AND statusCategory!=Done ORDER BY priority ASC, updated DESC"
    return jira_search(jql, limit=limit)


@mcp.tool()
def jira_backlog(limit: int = 50) -> list[dict]:
    """List the project backlog ordered by priority.

    Args:
        limit: Maximum number of results (default 50)
    """
    jql = f"project={PROJECT} AND statusCategory!=Done ORDER BY priority ASC, created ASC"
    return jira_search(jql, limit=limit)


@mcp.tool()
def jira_my_recent(limit: int = 20) -> list[dict]:
    """List your recently updated JIRA tickets (assigned to current user).

    Args:
        limit: Maximum number of results (default 20)
    """
    jql = f"project={PROJECT} AND assignee=currentUser() ORDER BY updated DESC"
    return jira_search(jql, limit=limit)


@mcp.tool()
def jira_my_summary() -> dict:
    """Summary of your assigned tickets grouped by status."""
    jql = f"project={PROJECT} AND assignee=currentUser()"
    issues = _fetch_issues(jql, fields="status", max_results=200)
    counts: dict[str, int] = {}
    for issue in issues:
        status = (issue["fields"].get("status") or {}).get("name", "Unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"total": sum(counts.values()), "by_status": counts}


@mcp.tool()
def jira_sprint(limit: int = 50) -> list[dict]:
    """List tickets in the current active sprint.

    Args:
        limit: Maximum number of results (default 50)
    """
    jql = f"project={PROJECT} AND sprint in openSprints() ORDER BY priority ASC, status ASC"
    return jira_search(jql, limit=limit)


@mcp.tool()
def jira_create(
    summary: str,
    issue_type: str = "Task",
    description: str = "",
    priority: str = "",
    assignee: str = "",
    component: str = "",
    labels: str = "",
    fix_version: str = "",
    epic_link: str = "",
    story_points: float | None = None,
    custom_fields: dict | None = None,
) -> dict:
    """Create a new JIRA ticket in the configured project.

    Args:
        summary: Ticket title/summary
        issue_type: Issue type - Bug, Task, Story, Improvement, Epic (default: Task)
        description: Description in Jira wiki markup (optional)
        priority: Priority - P1, P2, P3, P4, Blocker, Critical, Major, Minor (optional)
        assignee: Assignee username (optional)
        component: Component name (optional)
        labels: Comma-separated labels (optional)
        fix_version: Fix version name (optional)
        epic_link: Epic ticket key to link this issue under, e.g. PROJ-100 (optional).
            Resolves the instance's "Epic Link" field at runtime.
        story_points: Story points estimate (optional). Resolves the instance's
            "Story Points" field at runtime.
        custom_fields: Optional map of {field name or customfield_* id: value} for
            any instance-specific field (e.g. {"Story Points": 5}). Field names are
            resolved to ids at runtime. Values must match JIRA's expected write shape
            for that field. Typed parameters above take precedence on collision.
    """
    fields: dict = {
        "project": {"key": PROJECT},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }
    if description:
        fields["description"] = description
    if priority:
        fields["priority"] = {"name": priority}
    if assignee:
        fields["assignee"] = {"name": assignee}
    if component:
        fields["components"] = [{"name": component}]
    if labels:
        fields["labels"] = [l.strip() for l in labels.split(",")]
    if fix_version:
        fields["fixVersions"] = [{"name": fix_version}]

    _apply_epic_link(fields, epic_link)
    _apply_story_points(fields, story_points)
    ignored = _apply_custom_fields(fields, custom_fields)

    result = _jira_post("/issue", {"fields": fields})
    key = result.get("key", "unknown")
    out: dict = {"key": key, "url": f"{JIRA_BROWSE}/{key}"}
    if ignored:
        out["ignored_custom_fields"] = ignored
    return out


@mcp.tool()
def jira_update(
    ticket: str,
    summary: str = "",
    description: str = "",
    priority: str = "",
    assignee: str = "",
    component: str = "",
    labels: str = "",
    fix_version: str = "",
    epic_link: str = "",
    story_points: float | None = None,
    custom_fields: dict | None = None,
) -> dict:
    """Update fields on an existing JIRA ticket.

    Args:
        ticket: Ticket key, e.g. PROJ-1234
        summary: New summary/title (optional)
        description: New description (optional)
        priority: New priority (optional)
        assignee: New assignee username (optional)
        component: Component name (optional)
        labels: Comma-separated labels - replaces existing (optional)
        fix_version: Fix version name (optional)
        epic_link: Epic ticket key to link this issue under, e.g. PROJ-100 (optional).
            Resolves the instance's "Epic Link" field at runtime.
        story_points: Story points estimate (optional). Resolves the instance's
            "Story Points" field at runtime.
        custom_fields: Optional map of {field name or customfield_* id: value} for
            any instance-specific field (e.g. {"Story Points": 8}). Field names are
            resolved to ids at runtime. Values must match JIRA's expected write shape
            for that field. Typed parameters above take precedence on collision.
    """
    fields: dict = {}
    if summary:
        fields["summary"] = summary
    if description:
        fields["description"] = description
    if priority:
        fields["priority"] = {"name": priority}
    if assignee:
        fields["assignee"] = {"name": assignee}
    if component:
        fields["components"] = [{"name": component}]
    if labels:
        fields["labels"] = [l.strip() for l in labels.split(",")]
    if fix_version:
        fields["fixVersions"] = [{"name": fix_version}]

    _apply_epic_link(fields, epic_link)
    _apply_story_points(fields, story_points)
    ignored = _apply_custom_fields(fields, custom_fields)

    if not fields:
        raise ValueError("No fields to update. Provide at least one field.")

    key = _validate_key(ticket)
    _jira_put(f"/issue/{key}", {"fields": fields})
    out: dict = {"ticket": key, "updated_fields": list(fields.keys())}
    if ignored:
        out["ignored_custom_fields"] = ignored
    return out


@mcp.tool()
def jira_transitions(ticket: str) -> list[dict]:
    """List available status transitions for a ticket.

    Args:
        ticket: Ticket key, e.g. PROJ-1234
    """
    data = _jira_get(f"/issue/{_validate_key(ticket)}/transitions")
    return [
        {"id": t["id"], "name": t["name"], "to": t["to"]["name"]}
        for t in data.get("transitions", [])
    ]


@mcp.tool()
def jira_transition(ticket: str, status: str) -> dict:
    """Transition a ticket to a new status (e.g. "In Progress", "In Review", "Resolved").

    Args:
        ticket: Ticket key, e.g. PROJ-1234
        status: Target status name (use jira_transitions to see available options)
    """
    data = _jira_get(f"/issue/{_validate_key(ticket)}/transitions")
    transitions = data.get("transitions", [])
    target = status.lower()

    match = None
    for t in transitions:
        if t["name"].lower() == target or t["to"]["name"].lower() == target:
            match = t
            break

    if not match:
        available = [t["name"] for t in transitions]
        raise ValueError(
            f"Transition '{status}' not available for {ticket}. "
            f"Available: {', '.join(available)}"
        )

    _jira_post(
        f"/issue/{_validate_key(ticket)}/transitions",
        {"transition": {"id": match["id"]}},
    )
    return {"ticket": _validate_key(ticket), "transitioned_to": match["to"]["name"]}


@mcp.tool()
def jira_comment(ticket: str, body: str) -> dict:
    """Add a comment to a JIRA ticket.

    Args:
        ticket: Ticket key, e.g. PROJ-1234
        body: Comment body in Jira wiki markup
    """
    result = _jira_post(f"/issue/{_validate_key(ticket)}/comment", {"body": body})
    return {
        "ticket": _validate_key(ticket),
        "comment_id": result.get("id", ""),
        "created": result.get("created", "")[:16],
    }


@mcp.tool()
def jira_link(ticket: str, target: str, link_type: str = "Relates") -> dict:
    """Link two JIRA tickets together.

    The default link type is the JIRA-standard "Relates". Some instances name
    this link type differently (e.g. "Related"). If the given type is not known
    to the instance, this raises a ValueError listing the valid type names for
    that instance instead of surfacing a raw HTTP 404.

    Args:
        ticket: Source ticket key
        target: Target ticket key
        link_type: Link type name (Relates, Blocks, Clones, Duplicate, etc.)
    """
    src = _validate_key(ticket)
    dst = _validate_key(target)
    payload = {
        "type": {"name": link_type},
        "inwardIssue": {"key": src},
        "outwardIssue": {"key": dst},
    }
    try:
        _jira_post("/issueLink", payload)
    except JiraApiError as e:
        # A 404 means the instance has no link type with that name. Detect it via
        # the structured status code (never a substring on the message, which
        # could contain "404" for unrelated reasons such as a ticket key). Any
        # other failure (permission, connectivity, etc.) is re-raised unchanged.
        if e.status != 404:
            raise
        valid = _valid_link_type_names()
        listed = ", ".join(valid) if valid else "(none returned by the instance)"
        raise ValueError(
            f"Unknown link type '{link_type}' for this JIRA instance. "
            f"Valid link types: {listed}."
        ) from e
    return {"linked": f"{src} --[{link_type}]--> {dst}"}


@mcp.tool()
def jira_boards() -> list[dict]:
    """List Scrum/Kanban boards for the configured project."""
    data = _agile_get(f"/board?projectKeyOrId={_quote_path(PROJECT)}&maxResults=50")
    return [
        {"id": b["id"], "name": b["name"], "type": b.get("type", "")}
        for b in data.get("values", [])
    ]


@mcp.tool()
def jira_sprints(board_id: int) -> list[dict]:
    """List active and future sprints for a board.

    Args:
        board_id: Board ID (use jira_boards to find it)
    """
    data = _agile_get(
        f"/board/{board_id}/sprint?maxResults=20&state=active,future"
    )
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "state": s.get("state", ""),
            "start": (s.get("startDate") or "")[:10],
            "end": (s.get("endDate") or "")[:10],
        }
        for s in data.get("values", [])
    ]


@mcp.tool()
def jira_sprint_issues(sprint_id: int, limit: int = 100) -> list[dict]:
    """List issues in a specific sprint.

    Args:
        sprint_id: Sprint ID (use jira_sprints to find it)
        limit: Maximum number of results (default 100)
    """
    data = _agile_get(
        f"/sprint/{sprint_id}/issue?maxResults={limit}&fields={FIELDS_LIST}"
    )
    issues = data.get("issues", [])
    results = []
    for issue in issues:
        f = issue["fields"]
        results.append({
            "key": issue["key"],
            "summary": f.get("summary", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "priority": (f.get("priority") or {}).get("name", ""),
            "type": (f.get("issuetype") or {}).get("name", ""),
            "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
            "updated": f.get("updated", "")[:10],
        })
    return results


@mcp.tool()
def jira_move_to_sprint(ticket: str, sprint_id: int) -> dict:
    """Move a ticket to a specific sprint.

    Args:
        ticket: Ticket key, e.g. PROJ-1234
        sprint_id: Sprint ID (use jira_sprints to find it)
    """
    _agile_post(f"/sprint/{sprint_id}/issue", {"issues": [_validate_key(ticket)]})
    return {"ticket": _validate_key(ticket), "moved_to_sprint": sprint_id}


@mcp.tool()
def jira_status_summary() -> dict:
    """Get a count of open issues grouped by status."""
    jql = f"project={PROJECT} AND statusCategory!=Done"
    issues = _fetch_issues(jql, fields="status", max_results=500)
    counts: dict[str, int] = {}
    for issue in issues:
        status = (issue["fields"].get("status") or {}).get("name", "Unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"total": sum(counts.values()), "by_status": counts}


@mcp.tool()
def jira_component_summary() -> dict:
    """Get a count of open issues grouped by component."""
    jql = f"project={PROJECT} AND statusCategory!=Done"
    issues = _fetch_issues(jql, fields="components", max_results=500)
    counts: dict[str, int] = {}
    for issue in issues:
        comps = issue["fields"].get("components", [])
        if not comps:
            counts["(none)"] = counts.get("(none)", 0) + 1
        for c in comps:
            counts[c["name"]] = counts.get(c["name"], 0) + 1
    return {"by_component": counts}


@mcp.tool()
def jira_create_version(
    name: str,
    description: str = "",
    released: bool = False,
) -> dict:
    """Create a new version (fixVersion) in the configured project.

    Args:
        name: Version name, e.g. "1.21.0"
        description: Optional version description
        released: Whether the version is already released (default: False)
    """
    _check_config()
    # Get the project numeric ID required by the versions API.
    project_data = _jira_get(f"/project/{_quote_path(PROJECT)}")
    project_id = project_data["id"]

    payload: dict = {
        "name": name,
        "project": PROJECT,
        "projectId": int(project_id),
        "released": released,
        "archived": False,
    }
    if description:
        payload["description"] = description

    result = _jira_post("/version", payload)
    return {
        "id": result.get("id", ""),
        "name": result.get("name", ""),
        "project": PROJECT,
        "released": result.get("released", False),
    }


@mcp.tool()
def jira_list_versions(
    released: str = "all",
    archived: bool = False,
) -> list[dict]:
    """List all versions in the configured project.

    Args:
        released: Filter by release status: "all", "released", or "unreleased" (default: "all")
        archived: Include archived versions (default: False)
    """
    _check_config()
    versions = _jira_get(f"/project/{_quote_path(PROJECT)}/versions")
    results = []
    for v in versions:
        if not archived and v.get("archived", False):
            continue
        is_released = v.get("released", False)
        if released == "released" and not is_released:
            continue
        if released == "unreleased" and is_released:
            continue
        results.append({
            "id": v.get("id", ""),
            "name": v.get("name", ""),
            "released": is_released,
            "archived": v.get("archived", False),
            "start_date": v.get("startDate", ""),
            "release_date": v.get("releaseDate", ""),
            "description": v.get("description", ""),
        })
    return results


@mcp.tool()
def jira_release_version(
    version_id: str,
    release_date: str = "",
) -> dict:
    """Mark a version as released.

    Args:
        version_id: Version ID (use jira_list_versions to find it)
        release_date: Release date in YYYY-MM-DD format (defaults to today)
    """
    _check_config()
    if not release_date:
        import datetime
        release_date = datetime.date.today().isoformat()

    payload: dict = {
        "released": True,
        "releaseDate": release_date,
    }
    result = _jira_put(f"/version/{_quote_path(version_id)}", payload)
    return {
        "id": result.get("id", ""),
        "name": result.get("name", ""),
        "released": result.get("released", False),
        "release_date": result.get("releaseDate", ""),
    }


@mcp.tool()
def jira_update_version(
    version_id: str,
    name: str = "",
    description: str = "",
    start_date: str = "",
    release_date: str = "",
    archived: bool = False,
) -> dict:
    """Update an existing version's metadata.

    Args:
        version_id: Version ID (use jira_list_versions to find it)
        name: New version name (optional)
        description: New description (optional)
        start_date: Start date in YYYY-MM-DD format (optional)
        release_date: Release date in YYYY-MM-DD format (optional)
        archived: Set to True to archive the version (default: False)
    """
    _check_config()
    payload: dict = {}
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description
    if start_date:
        payload["startDate"] = start_date
    if release_date:
        payload["releaseDate"] = release_date
    if archived:
        payload["archived"] = True

    if not payload:
        raise ValueError("No fields to update. Provide at least one field.")

    result = _jira_put(f"/version/{_quote_path(version_id)}", payload)
    return {
        "id": result.get("id", ""),
        "name": result.get("name", ""),
        "released": result.get("released", False),
        "archived": result.get("archived", False),
        "start_date": result.get("startDate", ""),
        "release_date": result.get("releaseDate", ""),
        "description": result.get("description", ""),
    }


@mcp.tool()
def jira_delete_version(
    version_id: str,
    move_issues_to: str = "",
) -> dict:
    """Delete a version from the project.

    Note: Some JIRA Server instances block DELETE on versions (405). If deletion
    fails, use jira_update_version with archived=True as an alternative.

    Args:
        version_id: Version ID to delete (use jira_list_versions to find it)
        move_issues_to: Version ID to reassign affected issues to (optional). If omitted, issues lose this fixVersion.
    """
    _check_config()
    path = f"/version/{_quote_path(version_id)}"
    if move_issues_to:
        path += f"?moveFixIssuesTo={_quote_path(move_issues_to)}&moveAffectedIssuesTo={_quote_path(move_issues_to)}"
    _jira_delete(path)
    return {"deleted": version_id, "moved_issues_to": move_issues_to or "(none)"}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()
