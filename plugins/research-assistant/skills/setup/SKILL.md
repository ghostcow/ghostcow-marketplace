---
description: >
  Set up s2 CLI permissions so commands run without prompting.
  Use when the user first installs the research-assistant plugin.
disable-model-invocation: true
allowed-tools: Bash, Read, Edit
---

# Setup

This is a separate, user-invoked skill because it modifies global config
(`~/.claude/settings.json`). The research skill should never see these
instructions — it has a different lifecycle, audience, and tool set.

Configure the user's `~/.claude/settings.json` for the research-assistant plugin:

1. Add `Bash(s2:*)` to `permissions.allow` so s2 commands run without approval.
2. Add `api.semanticscholar.org` to `sandbox.network.allowedDomains` so the
   s2 CLI can reach the Semantic Scholar API from within the sandbox.
3. Add `uv:*` to `sandbox.excludedCommands` so uv can install and cache
   dependencies outside the sandbox.

Read the file first, then merge all entries into the existing structure.
Create the file with the correct structure if it doesn't exist.
