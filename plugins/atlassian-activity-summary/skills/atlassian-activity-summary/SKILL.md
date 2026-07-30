---
name: atlassian-activity-summary
description: Summarize what a person did in Jira and Confluence over a date range. Use for "what did I do last week", standup or status-update prep, performance-review input, or when asked to find someone's comments, status transitions, or issues created in a window.
---

# Summarizing what a person did in Jira and Confluence

Produce three to seven claims about the person's work, each naming an outcome and citing the issues behind it — a summary they could paste into a status update:

> Closed out the payments-migration epic (15 sub-tasks, PROJ-4562..4575 + PROJ-4838). Found the root cause of the checkout timeouts: a generic error response after OAuth requests (PROJ-7537). Guardrails baseline shows the deny side at 78%, with every miss an adversarial input (PROJ-5741).

Four signals produce a claim. Collect these:

- **Prose the person wrote** — comment bodies, and descriptions of issues they created. This carries the substance.
- **Outcome** — the status work reached, distinguishing finished from in flight.
- **Grouping** — the parent or epic, so related items collapse into one claim.
- **Identity** — issue key, summary, and date to day precision, for citation and ordering.

## Setup

Work through the Atlassian MCP server. Call `getAccessibleAtlassianResources` for the cloudId and `atlassianUserInfo` for the requester's accountId. You need the accountId because queries return every comment on a matching issue, not only the person's.

The response lists one entry per product, so a single site appears more than once with the same `id` and differing scopes. Ask which to search only when the entries carry more than one distinct cloudId.

For someone else, resolve their accountId with `lookupJiraAccountId` and use it in place of `currentUser()`. Their activity stays bounded by your own read permissions and anything outside them is omitted silently, so say as much when reporting on another person.

Convert the requested period to explicit dates before querying. Get today's date from the environment rather than assuming it, and state the resolved range in your answer so the person can correct it.

JQL date literals resolve in the account's timezone while comment timestamps carry their own offset. Compare them in the account's timezone so an event at either edge of the window lands on the correct side.

Week boundaries follow the team's working week, which is not always Monday-to-Sunday — Sunday-to-Thursday is standard in Israel and much of the Middle East. Treat "this week" as running from the current week's start through today.

Determine the convention in this order: what the requester says; a memory file or earlier summary that records it; otherwise the pattern in the activity itself, since a team's quiet days show up as gaps. Failing all three, assume Monday-to-Sunday, state the assumption, and continue.

## The queries

Run the Confluence query first when the person keeps a status page: reading their own account of the week frames everything else. Windows are inclusive of both the first and last day throughout — a comment posted at 19:25 on the final day counts.

### Prose — comments the person wrote

```
commentedBy = currentUser() AND updated >= "<start>" ORDER BY updated DESC
```

Request `fields: ["summary", "status", "issuetype", "parent", "updated", "comment"]` with `responseContentFormat: "markdown"`. Keep comments where `author.accountId` matches and `created` falls in the window.

Responses run to hundreds of kilobytes because every user reference expands into avatar URLs. Expect to write the result to a file and filter it rather than reading it inline.

Comment bodies hold the findings, decisions, and root causes that make up the substance of a week, and this field reaches participation in other people's issues. Read them and quote the substantive lines.

Comments arrive under `fields.comment.comments` with their own `total` and `maxResults`. When `total` exceeds the number returned, refetch that issue with `getJiraIssue` to get the rest.

A comment may carry a chart or screenshot with little or no prose. Cite it as a result posted on that date and say the image was not read.

### Outcome — status transitions

Add a `TO` clause so the result set itself carries the outcome. A value list works in one call:

```
status changed BY currentUser() TO ("Done", "Archived") DURING ("<start> 00:00", "<end> 23:59")
status changed BY currentUser() TO ("In Progress", "In Review") DURING ("<start> 00:00", "<end> 23:59")
```

Include the times. Date-only bounds in `DURING` behave inconsistently — a window whose endpoints are the same date returns nothing even when transitions occurred that day. `<end>` is the last day you want included, not the day after.

Separate the finished statuses from the in-flight ones across calls, so the result set tells you which group an issue belongs to. Get the site's status names from `getTransitionsForJiraIssue` with `includeUnavailableTransitions: true` — without that parameter it returns only the transitions available from one issue's current status, which silently omits most of the list.

The `status` field returns the issue's status **now**, not the status the transition moved it to. Anyone transitioning the issue again afterward changes it, so an issue the person started can read as archived or reopened. The `TO` clause is what attributes the outcome correctly; never infer it from the current `status` field.

Request `issuetype` and `parent` alongside the usual fields, then group by parent before writing: several sub-tasks reaching Done under one epic is one accomplishment. `issuetype` is what tells you whether an item is a sub-task, a task, or the epic itself.

Dates inside `DURING` take `YYYY/MM/DD`, unlike the quoted `YYYY-MM-DD` form used with `>=` comparisons.

### Scope — issues the person created

```
reporter = currentUser() AND created >= "<start>" AND created < "<end-exclusive>"
```

Reaches work opened during the window, including issues with no comments or transitions yet. Read the descriptions as prose signal — the person wrote them. New issues under a shared parent are one claim: a workstream opened.

### Confluence, when the person writes there

```
contributor = currentUser() AND lastmodified >= "<start>" ORDER BY lastmodified DESC
```

Through `searchConfluenceUsingCql`. Use `contributor` rather than `creator` so edits to pages other people own are included.

Set only the lower bound. `lastmodified` behaves like JQL's `updated`: a later edit by anyone pushes the page past a fixed ceiling, and a person's own status page is the likeliest casualty because they keep editing it.

`contributor` also matches pages where the person's edit was incidental or long before the window. Before treating a page as their prose, confirm they authored the in-window content — check the version author and, where entries are dated, whose entry it is. A colleague's status page listing their own work is not the requester's activity.

Run this when the request spans more than Jira or when the team keeps status pages. A weekly-status page whose entries cover the window is the strongest source available — read it first, then reconcile it against the queries above and note anything it omits.

An edit inside the window does not mean the page covers the window: a page often gets edited to write up an earlier period. Check the entry dates, not the edit date. When the page was edited in-window but has no entry for it, report the edit as work done and say the page has no entry yet — then offer to draft one from the summary.

CQL is a separate language from JQL — `contributor`, `lastmodified`, `creator`, `space`, `type`. JQL field names do not transfer.

## Writing the summary

Group events into claims and order them by significance. An epic reaching Done leads; a single comment on someone else's ticket comes last. When the natural grouping yields more than seven claims, merge the related ones rather than dropping any — a dropped claim reads as a week that did not happen.

Watch for bulk-transition clusters: many issues moved within a few minutes are one bookkeeping action, and the work behind them may predate the window. Say the workstream closed in the window rather than that it was executed there, and check the person's own comments or status page for when the work actually happened.

State each claim in a sentence that names the outcome, then cite the keys. Quote the specific finding when a comment carries one — the numbers and root causes are what the reader wants.

Compress contiguous key ranges: `PROJ-4562..4575` rather than fourteen keys in a row. List keys individually when they are not contiguous.

Keep the claims themselves pasteable. Put sourcing below them under its own heading, so the prose above stays usable as a status update and the notes below do not count against the three-to-seven budget.

In that section, say which sources you ran and name any that returned nothing — an empty result is a fact about the week. Where comments reference systems outside Atlassian — pull requests, experiment runs, dashboards, chat threads — say those were not queried.

## Deliberately out of scope

These are reachable, and they belong in an audit of completeness rather than a summary of accomplishments. Reach for them when that is the request:

- Edited comments. A comment whose `updated` differs from its `created` was revised. The current body is what the API returns, so the reportable fact is that an edit occurred and when.
- Description and summary edits. Fetch an issue with `expand: "changelog"` and diff `fromString` against `toString`, at one request per issue. Neither field has an author index — `description changed BY currentUser()` returns HTTP 400.
- Attachments, issue links, and parent reassociations. Changelog-only, at the same cost per issue.
- Worklogs, via `worklogAuthor` and `worklogDate`. Populated only where a team logs time.
- Watchers and voters, which describe current state at query time.

For a complete audit, add a changelog pass over the issues the three queries returned and filter entries by accountId. Changelogs are dense with automation accounts; app-type authors are system activity.

## Syntax that returns errors

Author fields accept a date predicate only through the `BY` operator. Pairing a predicate with `=` or `in` returns HTTP 400: *"The EQUALS operator does not support the use of the after ... predicate."*

```
commentedBy BY currentUser() AFTER "<start>" BEFORE "<end>"   ✓
commentedBy = currentUser() AFTER "<start>"                   ✗ 400
```

When narrowing by the `updated` field, set only the lower bound: `updated >= <window start>`. Because `updated` advances on every change, an edit by anyone after the window moves the issue past a fixed ceiling while the person's in-window work sits inside it. The open-ended form is a superset — filter to the window as you extract events.
