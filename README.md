# JIRA — Kiro Power

[![Kiro Power](https://img.shields.io/badge/Kiro-Power-blue)](https://kiro.dev)
[![License: GPL v2+](https://img.shields.io/badge/License-GPL%20v2%2B-blue.svg)](LICENSE)

Manage JIRA tickets, boards, sprints, and backlog directly from [Kiro](https://kiro.dev) chat sessions via MCP (Model Context Protocol).

Works with **any JIRA instance** (Cloud or Server) and **any project** — fully configured via environment variables.

## What It Does

This power exposes 16 MCP tools for interacting with the JIRA REST API v2:

- **Query:** View tickets, search with JQL, list your open work, browse backlog/sprint
- **Mutate:** Create tickets, update fields, transition status, add comments, link tickets
- **Board/Sprint:** List boards and sprints, move tickets between sprints
- **Report:** Status and component summaries

## Available Tools

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

## Requirements

- **Python 3.11+**
- **uvx** (from the [`uv`](https://docs.astral.sh/uv/getting-started/installation/) package manager)
- **JIRA Personal Access Token** with read/write access to your project

The power is fully self-contained — the MCP server lives at `server/jira_mcp.py` inside this directory. No external project scripts are needed.

## Configuration

All configuration is via environment variables — no JIRA instance or project is hardcoded:

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `JIRA_PAT` | Yes | Personal access token for authentication |
| `JIRA_BASE_URL` | Yes | JIRA instance URL (e.g., `https://jira.example.com`) |
| `JIRA_PROJECT` | Yes | Default project key (e.g., `MYPROJ`, `TEAM`) |

### Example configurations

**Atlassian Cloud:**
```bash
export JIRA_PAT="your-api-token"
export JIRA_BASE_URL="https://yourcompany.atlassian.net"
export JIRA_PROJECT="PROJ"
```

**JIRA Server (self-hosted):**
```bash
export JIRA_PAT="your-personal-access-token"
export JIRA_BASE_URL="https://jira.internal.company.com"
export JIRA_PROJECT="OPS"
```

**Multiple projects:** Install the power once, then switch projects by changing `JIRA_PROJECT` in the `mcp.json` env block. Or create multiple MCP server entries with different env configs.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/revagomes/kiro-power-jira.git
cd kiro-power-jira
```

### 2. Set up environment variables

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
export JIRA_PAT="your-personal-access-token"
export JIRA_BASE_URL="https://jira.example.com"
export JIRA_PROJECT="MYPROJ"
```

To generate a PAT:
- **JIRA Server:** Profile → Personal Access Tokens → Create
- **Atlassian Cloud:** Account Settings → Security → API Tokens → Create

### 3. Update the server path in `mcp.json`

Edit `mcp.json` and replace the path with your local clone location:

```json
{
  "mcpServers": {
    "jira": {
      "command": "uvx",
      "args": ["--from", "fastmcp", "fastmcp", "run", "/path/to/kiro-power-jira/server/jira_mcp.py"],
      "env": {
        "JIRA_PAT": "${env:JIRA_PAT}",
        "JIRA_BASE_URL": "${env:JIRA_BASE_URL}",
        "JIRA_PROJECT": "${env:JIRA_PROJECT}"
      }
    }
  }
}
```

### 4. Register the power in Kiro

Add to `~/.kiro/powers/registries/user-added.json` inside the `"powers"` array:

```json
{
  "name": "jira",
  "description": "JIRA ticket management via MCP",
  "source": {
    "type": "local",
    "path": "/path/to/kiro-power-jira"
  },
  "autoInstall": false
}
```

Add to `~/.kiro/powers/installed.json` under `"installedPowers"`:

```json
{
  "name": "jira",
  "registryId": "user-added"
}
```

### 5. Verify

```bash
# Test the server starts (set env vars first)
export JIRA_PAT="test" JIRA_BASE_URL="https://jira.example.com" JIRA_PROJECT="TEST"
uvx --from fastmcp fastmcp inspect /path/to/kiro-power-jira/server/jira_mcp.py
```

Expected output: `Tools: 16`

Then restart Kiro — the power should appear in the powers list.

## Usage Examples

Once installed, just talk naturally in your Kiro session:

```
"What's PROJ-1234 about?"
"Show me my open tickets"
"Find all P1 bugs"
"Move PROJ-1234 to In Progress"
"Create a bug for the broken pagination"
"What's in the current sprint?"
"Post a comment on PROJ-1234 with the MR link"
"How's the project status?"
```

## Multi-Project Setup

To manage multiple JIRA projects simultaneously, add multiple server entries in your `~/.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "jira-frontend": {
      "command": "uvx",
      "args": ["--from", "fastmcp", "fastmcp", "run", "/path/to/server/jira_mcp.py"],
      "env": {
        "JIRA_PAT": "${env:JIRA_PAT}",
        "JIRA_BASE_URL": "${env:JIRA_BASE_URL}",
        "JIRA_PROJECT": "FRONT"
      }
    },
    "jira-backend": {
      "command": "uvx",
      "args": ["--from", "fastmcp", "fastmcp", "run", "/path/to/server/jira_mcp.py"],
      "env": {
        "JIRA_PAT": "${env:JIRA_PAT}",
        "JIRA_BASE_URL": "${env:JIRA_BASE_URL}",
        "JIRA_PROJECT": "BACK"
      }
    }
  }
}
```

## How It Works

The power uses [FastMCP](https://github.com/jlowin/fastmcp) to expose Python functions as MCP tools over stdio transport. Each tool maps to one or more JIRA REST API v2 endpoints:

- **Read operations** use `GET /rest/api/2/issue`, `/search`, `/transitions`
- **Write operations** use `POST /rest/api/2/issue`, `/comment`, `/issueLink`
- **Update operations** use `PUT /rest/api/2/issue`
- **Agile operations** use `GET/POST /rest/agile/1.0/board`, `/sprint`

Authentication is via Bearer token (`JIRA_PAT`). All requests are made server-side — no credentials are exposed to the agent or chat context.

## Structure

```
kiro-power-jira/
├── POWER.md              ← Power manifest (frontmatter + instructions for Kiro)
├── mcp.json              ← MCP server configuration
├── server/
│   ├── jira_mcp.py       ← Self-contained MCP server (FastMCP + JIRA REST API)
│   └── run.sh            ← Launcher script (resolves own path, runs from anywhere)
├── steering/
│   ├── jira-workflow.md  ← Ticket lifecycle workflow guidance
│   └── jira-lookup.md   ← Ticket query and search patterns
├── .gitignore
├── LICENSE
└── README.md             ← This file
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Missing required environment variable(s)" | Set `JIRA_PAT`, `JIRA_BASE_URL`, and `JIRA_PROJECT` |
| 401 Unauthorized | Token expired — regenerate in JIRA profile |
| 403 Forbidden | Your token lacks permissions — check project role |
| Connection timeout | Ensure network/VPN access to your JIRA instance |
| Server won't start | Run `uvx --from fastmcp fastmcp inspect server/jira_mcp.py` |
| "Transition not available" | Use `jira_transitions` first to see available options |
| Tools not showing in Kiro | Verify `installed.json` entry and restart Kiro |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/add-watchers-tool`)
3. Add your tool to `server/jira_mcp.py` — follow the `@mcp.tool()` pattern
4. Test with `uvx --from fastmcp fastmcp inspect server/jira_mcp.py`
5. Update the tools table in `POWER.md` and `README.md`
6. Submit a pull request

## License

This project is licensed under the GNU General Public License v2.0 or later (GPL-2.0-or-later).
See [LICENSE](LICENSE) for the full text.
