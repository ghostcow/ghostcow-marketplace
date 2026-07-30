# atlassian-activity-summary

Turns a date range into a short status update: three to seven claims about what a person did in Jira and Confluence, each naming an outcome and citing the issues behind it.

## Prerequisite

The Atlassian MCP server must be connected and authenticated in the session. Check with `/mcp`. The skill calls `searchJiraIssuesUsingJql`, `searchConfluenceUsingCql`, `getJiraIssue`, `getTransitionsForJiraIssue`, `atlassianUserInfo`, and `getAccessibleAtlassianResources`, and reads without writing.

## Use

Ask in plain language:

```
what did I do last week?
summarize my Jira activity for July 20-26
what has Dana been working on this sprint?
```

The skill resolves the date range, queries each source, and returns the claims with sourcing notes below them.

## What it collects

Four signals, because Atlassian indexes activity by author separately per verb and no single query returns all of it:

| Signal | Source |
| --- | --- |
| Prose the person wrote | comments they authored, descriptions of issues they created |
| Outcome | status transitions they made, queried per target status |
| Grouping | the parent or epic, so related items collapse into one claim |
| Confluence | pages they created or edited, including status pages |

Comment bodies carry the substance — findings, root causes, decisions — so the summary quotes them rather than counting them.

## Scope

Reports accomplishments. Description edits, attachments, issue links, worklogs, and full changelog audits are documented in the skill as out of scope for a summary, with the queries to reach them when a completeness audit is what's wanted.

Querying another person's activity stays bounded by your own Atlassian read permissions, and anything outside them is omitted silently — the skill says so when reporting on someone else.
