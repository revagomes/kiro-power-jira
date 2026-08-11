---
applyTo: ""
---

# JIRA Ticket Lookup

## When to Use

When the user asks about a JIRA ticket — its status, details, description, assignee, or what it's about — use the MCP tools to fetch the information directly.

## Lookup Patterns

### Single Ticket Query

When the user mentions a ticket key (e.g., "What's PROJ-1234?", "Tell me about PROJ-1234"):

1. Call `jira_view(ticket="PROJ-1234")`
2. Present a concise summary: key, summary, status, priority, assignee
3. Include description highlights (first few sentences or bullet points)
4. Mention recent comments if relevant
5. Note any linked tickets

### Search Queries

When the user asks a question that implies searching (e.g., "Are there any open bugs?", "What P1 tickets exist?"):

1. Translate the natural language query into JQL
2. Call `jira_search(jql="...")` with appropriate filters
3. Present results as a concise list: key, summary, status, priority

### Common JQL Translations

| User says | JQL |
|-----------|-----|
| "my tickets" / "assigned to me" | `assignee=currentUser() AND statusCategory!=Done` |
| "open bugs" | `type=Bug AND statusCategory!=Done` |
| "P1 issues" / "critical" | `priority in (P1, Blocker, Critical) AND statusCategory!=Done` |
| "what's in the sprint" | `sprint in openSprints()` |
| "component X issues" | `component="X" AND statusCategory!=Done` |
| "recently created" | `created >= -7d ORDER BY created DESC` |
| "blocked" / "reopened" | `status=Reopened` |
| "unassigned" | `assignee is EMPTY AND statusCategory!=Done` |

Note: Add `project=KEY` to JQL when using `jira_search` directly. The shortcut tools (`jira_my_open`, `jira_backlog`, etc.) scope to the configured project automatically.

### Status Overview

When the user asks "how's the project going?" or "what's the status?":

1. Call `jira_status_summary()` for a breakdown by status
2. Optionally call `jira_component_summary()` if component detail is relevant
3. Present as a brief summary with counts

## Response Format

Keep responses concise and scannable:

- **Single ticket:** Key, summary, status, priority, assignee, then description highlights
- **Search results:** Table or bullet list with key + summary + status
- **Summaries:** Counts by category, highlight anything unusual (many critical issues, blocked items)

Do NOT dump raw API output. Synthesize and summarize for the user.
