---
name: "jira"
displayName: "JIRA"
description: "Manage JIRA tickets, boards, sprints, and backlog directly from chat sessions. Query, create, update, transition, and comment on tickets using the JIRA REST API v2. Works with any JIRA instance and project."
keywords: ["jira", "ticket", "issue", "sprint", "board", "backlog", "transition", "comment", "search", "jql", "project management", "agile", "scrum", "kanban"]
author: "Renato Vasconcellos Gomes"
---

# JIRA

## Overview

This Power provides full JIRA project management capabilities via MCP tools. It connects to any JIRA instance (Cloud or Server) and exposes ticket lifecycle operations — from querying and creation through to transitions and sprint management.

**Key capabilities:**

- **Ticket lookup** — View full ticket details including description, comments, and links
- **JQL search** — Query tickets with any JQL expression
- **Ticket creation** — Create bugs, tasks, stories with full field support
- **Ticket updates** — Modify priority, assignee, labels, components, versions
- **Status transitions** — Move tickets through workflow states
- **Comments** — Add comments to tickets (e.g., MR links, status updates)
- **Linking** — Connect related tickets
- **Board & Sprint management** — List boards, sprints, move tickets between sprints
- **Reporting** — Status and component summaries

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **JIRA_PAT** | Personal access token for your JIRA instance |
| **JIRA_BASE_URL** | Base URL of your JIRA instance (e.g., `https://jira.example.com`) |
| **JIRA_PROJECT** | Project key (e.g., `MYPROJ`, `TEAM`, `OPS`) |
| **Python 3.11+** | Required for the MCP server |
| **uvx** | Used to run the FastMCP server (part of `uv` toolchain) |

The MCP server is **self-contained** inside this power (`server/jira_mcp.py`). No project-specific scripts are required.

Configuration is entirely via environment variables:

| Variable | Required | Default |
|----------|----------|---------|
| `JIRA_PAT` | Yes | — |
| `JIRA_BASE_URL` | Yes | — |
| `JIRA_PROJECT` | Yes | — |

If any required variable is missing, the server returns an actionable error message.

## Available MCP Tools

| Tool | Purpose |
|------|---------|
| `jira_view` | View a ticket with full details (description, comments, links) |
| `jira_search` | Search tickets using JQL |
| `jira_my_open` | List your currently open tickets |
| `jira_backlog` | List project backlog by priority |
| `jira_sprint` | List current sprint tickets |
| `jira_create` | Create a new ticket |
| `jira_update` | Update ticket fields (priority, assignee, labels, etc.) |
| `jira_transitions` | List available status transitions for a ticket |
| `jira_transition` | Move a ticket to a new status |
| `jira_comment` | Add a comment to a ticket |
| `jira_link` | Link two tickets together |
| `jira_boards` | List project Scrum/Kanban boards |
| `jira_sprints` | List active/future sprints for a board |
| `jira_move_to_sprint` | Move a ticket into a sprint |
| `jira_status_summary` | Count open issues grouped by status |
| `jira_component_summary` | Count open issues grouped by component |

## Activation Keywords

This power activates when you mention:
- jira, ticket, issue, PROJECT-XXXX (any ticket key pattern)
- sprint, backlog, board
- transition, status, assign
- JQL, search tickets
- create ticket, new bug, new task

## Steering

Load the appropriate workflow based on the user's intent:

- **Starting work on a ticket** → `readPowerSteering("jira", "jira-workflow.md")`
- **Looking up ticket details** → `readPowerSteering("jira", "jira-lookup.md")`

## Quick Usage Examples

### Look up a ticket

User: "What's PROJ-1234 about?"
→ Call `jira_view(ticket="PROJ-1234")` and summarize the result.

### Find your open work

User: "What tickets are assigned to me?"
→ Call `jira_my_open()` and present the list.

### Search with JQL

User: "Find all P1 bugs in the API component"
→ Call `jira_search(jql="project=PROJ AND type=Bug AND priority=P1 AND component=API")`

### Start working on a ticket

User: "I'm starting work on PROJ-1234"
→ Call `jira_transition(ticket="PROJ-1234", status="In Progress")`

### Create a ticket

User: "Create a bug for the broken pagination"
→ Call `jira_create(summary="Pagination broken on search results", issue_type="Bug", priority="P2")`

### Post MR link as comment

User: "Post the MR link to PROJ-1234"
→ Call `jira_comment(ticket="PROJ-1234", body="GitLab MR: [title|url]")`

## JQL Quick Reference

| Pattern | Example |
|---------|---------|
| My open tickets | `assignee=currentUser() AND statusCategory!=Done` |
| Unresolved bugs | `type=Bug AND resolution=Unresolved` |
| Updated this week | `updated >= startOfWeek()` |
| High priority | `priority in (P1, P2, Blocker, Critical)` |
| Specific component | `component = "Backend"` |
| Current sprint | `sprint in openSprints()` |
| Text search | `text ~ "pagination"` |
| Created recently | `created >= -7d` |

Note: The configured `JIRA_PROJECT` is automatically scoped in shortcut tools (`jira_my_open`, `jira_backlog`, `jira_sprint`, `jira_status_summary`, `jira_component_summary`). For `jira_search`, include `project=KEY` in your JQL if needed.

## Troubleshooting

### Authentication Errors (401)

The `JIRA_PAT` token has expired or is invalid. Generate a new one from your JIRA profile → Personal Access Tokens.

### Permission Denied (403)

Your token doesn't have permission for the requested operation. Check that your JIRA account has the required project role.

### Transition Not Available

Use `jira_transitions` first to see which transitions are currently available for the ticket's state. Not all transitions are available from all states.

### Connection Timeout

Ensure network connectivity to your JIRA instance. If behind a VPN, make sure it's connected.

### Missing Configuration

If you see "JIRA_BASE_URL is not set" or "JIRA_PROJECT is not set", update the `env` block in your `mcp.json` or export the variables in your shell.
