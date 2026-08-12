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
import time
import urllib.error
import urllib.parse
import urllib.request

from fastmcp import FastMCP


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
    """
    env_path = pathlib.Path(__file__).parent / ".env"
    if env_path.is_file():
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
    """Validate that all required env vars are set."""
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


def _validate_key(ticket: str) -> str:
    """Validate and normalize a JIRA ticket key."""
    normalized = ticket.strip().upper()
    if not TICKET_KEY_RE.match(normalized):
        raise ValueError(
            f"Invalid ticket key: '{ticket}'. Expected format: PROJECT-123"
        )
    return normalized


def _get_pat() -> str:
    """Get JIRA PAT from environment."""
    _check_config()
    return os.environ["JIRA_PAT"]


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
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            if not body:
                return {}
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            err = json.loads(body)
            msgs = err.get("errorMessages", []) + list(
                err.get("errors", {}).values()
            )
            raise RuntimeError(
                f"JIRA API error ({e.code}): {'; '.join(msgs)}"
            ) from e
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(
                f"JIRA API error ({e.code}): {body[:300]}"
            ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection failed: {e.reason}") from e


def _jira_get(path: str) -> dict | list:
    return _api_request(f"{JIRA_BASE}{path}")


def _jira_post(path: str, payload: dict) -> dict:
    return _api_request(f"{JIRA_BASE}{path}", method="POST", payload=payload)


def _jira_put(path: str, payload: dict) -> dict:
    return _api_request(f"{JIRA_BASE}{path}", method="PUT", payload=payload)


def _agile_get(path: str) -> dict | list:
    return _api_request(f"{JIRA_AGILE_BASE}{path}")


def _agile_post(path: str, payload: dict) -> dict:
    return _api_request(f"{JIRA_AGILE_BASE}{path}", method="POST", payload=payload)


def _fetch_issues(
    jql: str, fields: str = FIELDS_LIST, max_results: int = 50
) -> list:
    """Fetch issues with pagination. Hard cap at 1000 to prevent runaway."""
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
    data = _jira_get(f"/issue/{_validate_key(ticket)}?fields={FIELDS_FULL}")
    f = data["fields"]
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

    result = _jira_post("/issue", {"fields": fields})
    key = result.get("key", "unknown")
    return {"key": key, "url": f"{JIRA_BROWSE}/{key}"}


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

    if not fields:
        raise ValueError("No fields to update. Provide at least one field.")

    _jira_put(f"/issue/{_validate_key(ticket)}", {"fields": fields})
    return {"ticket": _validate_key(ticket), "updated_fields": list(fields.keys())}


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

    Args:
        ticket: Source ticket key
        target: Target ticket key
        link_type: Link type name (Relates, Blocks, Clones, Duplicate, etc.)
    """
    _jira_post("/issueLink", {
        "type": {"name": link_type},
        "inwardIssue": {"key": _validate_key(ticket)},
        "outwardIssue": {"key": _validate_key(target)},
    })
    return {"linked": f"{_validate_key(ticket)} --[{link_type}]--> {_validate_key(target)}"}


@mcp.tool()
def jira_boards() -> list[dict]:
    """List Scrum/Kanban boards for the configured project."""
    data = _agile_get(f"/board?projectKeyOrId={PROJECT}&maxResults=50")
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


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()
