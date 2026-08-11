---
applyTo: ""
---

# JIRA Ticket Workflow

## When Starting Work on a Ticket

When the user indicates they are starting work on a JIRA ticket (mentioning a ticket key, saying "I'm working on...", or asking to pick up a task):

1. **View the ticket** — Call `jira_view` to understand the full context (description, comments, current status, links)
2. **Transition to In Progress** — Call `jira_transition(ticket, "In Progress")` unless already in that state
3. **Note the branch** — If a git branch is created, call `jira_comment` to post the branch name

## When Completing Work

When the user has finished implementation, created a commit, or is ready to submit:

1. **Post the MR link** — Call `jira_comment` with the MR/PR URL in Jira markup: `[MR Title|URL]`
2. **Transition to In Review** — Call `jira_transition(ticket, "In Review")`

## When Picking Up the Next Task

When the user asks "what should I work on next?" or similar:

1. **Check current sprint** — Call `jira_sprint()` to see sprint-scoped work
2. **Fallback to backlog** — If no sprint items, call `jira_my_open()` for assigned tickets
3. **Suggest the highest priority unstarted ticket** — Prefer high-priority bugs over tasks

## Jira Comment Formatting

When posting comments to JIRA, use Jira wiki markup (NOT Markdown):

| Element | Jira Markup |
|---------|-------------|
| Bold | `*text*` |
| Italic | `_text_` |
| Link | `[display text\|URL]` |
| Code | `{{inline code}}` |
| Code block | `{code}...{code}` |
| Heading | `h2. Heading` |
| Bullet list | `* item` |
| Numbered list | `# item` |

## General Status Flow Reference

```
Open → In Progress → In Review → To Test → Resolved → Closed
                  ↘ Reopened ↗
```

Not all transitions are available from every state. Always call `jira_transitions` first if unsure. Workflows vary by JIRA project configuration.
