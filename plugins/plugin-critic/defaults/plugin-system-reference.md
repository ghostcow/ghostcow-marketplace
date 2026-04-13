# Claude Code Plugin System Reference

This document describes the Claude Code plugin system — its components, capabilities, and
conventions. Use it as the authoritative source for understanding plugin architecture when
evaluating plugin designs. The prompting best practices file covers how to write good
prompts; this file covers what the plugin system is and what it provides.

## Plugin Structure

A plugin is a package that extends Claude Code's capabilities. Every plugin lives in its
own directory with a required manifest and optional component directories:

```
plugin-name/
  .claude-plugin/
    plugin.json          # Required: plugin identity and configuration
  skills/                # Skill definitions (auto-discovered)
  agents/                # Agent definitions (auto-discovered)
  hooks/
    hooks.json           # Hook configuration (auto-discovered)
  scripts/               # Supporting scripts
  .mcp.json              # MCP server definitions (auto-discovered)
  .lsp.json              # LSP server definitions (auto-discovered)
  settings.json          # Default settings
  output-styles/         # Output style definitions
  bin/                   # Executables added to PATH
```

Only `plugin.json` goes inside `.claude-plugin/`. Everything else stays at the plugin root.

### plugin.json

The manifest declares the plugin's identity and locates its components. Required field:
`name` (kebab-case identifier used to namespace components — e.g., `my-plugin` makes
skills invokable as `/my-plugin:skill-name`).

Key optional fields:

| Field | Type | Purpose |
|-------|------|---------|
| `version` | string | Semver version (single source of truth) |
| `description` | string | Shown in plugin manager |
| `author` | object | `{ name, email, url }` |
| `skills` | string/array | Custom skill paths (replaces default `skills/`) |
| `agents` | string/array | Custom agent paths (replaces default `agents/`) |
| `hooks` | string/array/object | Hook config paths or inline config |
| `mcpServers` | string/array/object | MCP config paths or inline config |
| `userConfig` | object | Values prompted at enable time (sensitive values go to system keychain) |

Path behavior: all paths are relative to plugin root and start with `./`. Custom paths
replace the default directory entirely — to keep the default and add more, include both
in an array.

### Environment Variables

Two variables are available everywhere in plugin content — skill markdown, agent markdown,
hook commands, and MCP/LSP configs. Both are substituted inline and exported to
subprocesses:

- **`${CLAUDE_PLUGIN_ROOT}`**: absolute path to plugin installation directory. Use for
  scripts and config bundled with the plugin. Changes when plugin updates.
- **`${CLAUDE_PLUGIN_DATA}`**: persistent directory for plugin state that survives updates.
  Located at `~/.claude/plugins/data/{id}/`. Use for installed dependencies, caches, and
  generated files.

### Auto-Discovery

Claude Code auto-discovers components in default locations (`skills/`, `agents/`,
`hooks/hooks.json`, `.mcp.json`, `.lsp.json`). Custom paths in `plugin.json` override
these defaults.

## Skills

A skill is a `SKILL.md` file that injects instructions into Claude's context. Skills
extend what Claude can do — they are the primary mechanism for adding workflows,
slash commands, and specialized behaviors to a plugin.

### Invocation Modes

Skills can be triggered two ways:

- **Model-invoked**: Claude automatically loads the skill when it matches the
  description and seems relevant to the current task.
- **User-invoked**: the user manually runs `/skill-name`.

These modes are controlled by two independent frontmatter fields:

- `disable-model-invocation: true` — completely prevents automatic loading. Claude never
  triggers this skill; only the user can invoke it via `/name`. Use for workflows with
  side effects (deploy, commit, send messages).
- `user-invocable: false` — hides from the `/` menu. Claude can still load it
  automatically. Use for background knowledge users should not invoke directly.

### Activation Scope

The `paths` field narrows when a skill triggers automatically without disabling model
invocation entirely:

```yaml
paths: "src/components/**/*.tsx,src/**/*.css"
```

When set, Claude loads the skill automatically only when working with files matching
the glob patterns. This provides fine-grained activation control — the skill remains
model-invokable but only in relevant file contexts. Without `paths`, a model-invokable
skill can trigger in any context where its description matches.

### Frontmatter Reference

| Field | Default | Description |
|-------|---------|-------------|
| `name` | directory name | Display name (lowercase, hyphens, max 64 chars) |
| `description` | first paragraph | What the skill does and when to use it. Claude uses this to decide when to load the skill automatically. Descriptions over 250 chars are truncated in listings. |
| `argument-hint` | (none) | Autocomplete hint. Example: `[issue-number]` |
| `disable-model-invocation` | false | Prevent automatic loading. User must invoke via `/name`. |
| `user-invocable` | true | Set false to hide from `/` menu (background knowledge only). |
| `allowed-tools` | (none) | Tools Claude can use without asking permission when skill is active. Space-separated string or YAML list. Supports glob patterns: `Bash(git *)` pre-approves all git commands. |
| `paths` | (none) | Glob patterns limiting automatic activation to matching files. Comma-separated string or YAML list. |
| `model` | inherit | Model override when skill is active: `sonnet`, `opus`, `haiku`, or full model ID. |
| `effort` | inherit | Effort level override: `low`, `medium`, `high`, `max` (Opus only). |
| `context` | inline | Set to `fork` to run in an isolated subagent context. |
| `agent` | general-purpose | Subagent type when `context: fork` is set: `Explore`, `Plan`, `general-purpose`, or a custom agent name. |
| `hooks` | (none) | Hooks scoped to this skill's lifecycle. |
| `shell` | bash | Shell for inline commands: `bash` or `powershell`. |

### String Substitutions

Available in skill content:

| Variable | Description |
|----------|-------------|
| `$ARGUMENTS` | All arguments passed when invoking the skill |
| `$ARGUMENTS[N]` / `$N` | Specific argument by 0-based index |
| `${CLAUDE_SKILL_DIR}` | Directory containing the skill's `SKILL.md` |
| `${CLAUDE_SESSION_ID}` | Current session ID |

### Dynamic Context Injection

The `` !`command` `` syntax runs shell commands before skill content is sent to Claude.
Output replaces the placeholder. Use for injecting dynamic state (git diff, PR metadata,
environment info) at skill load time.

### Lifecycle

Skill content enters the conversation as a single message and stays for the session.
Claude Code does not re-read the skill file on later turns. During context compaction,
the most recently invoked skills are re-attached (first 5,000 tokens each, shared
25,000-token budget across all re-attached skills).

## Agents

An agent is a specialized subagent that runs in its own context window with a custom
system prompt and scoped tool access. Agents handle tasks that benefit from isolation —
research that would flood the main conversation, parallel workstreams, or tasks requiring
different tool permissions.

### Definition Format

Agent definitions are markdown files with YAML frontmatter (the configuration) and a
markdown body (the system prompt):

```markdown
---
name: my-agent
description: When Claude should delegate to this agent
tools: Read, Grep, Glob
model: sonnet
---

System prompt instructions here...
```

### Frontmatter Reference

| Field | Default | Description |
|-------|---------|-------------|
| `name` | (required) | Unique identifier (lowercase, hyphens) |
| `description` | (required) | When Claude should delegate to this agent |
| `tools` | inherit all | Allowlist of tools agent can use. Inherits all from parent if omitted. |
| `disallowedTools` | (none) | Denylist of tools. Applied before `tools` allowlist if both specified. |
| `model` | inherit | `sonnet`, `opus`, `haiku`, full model ID, or `inherit` (same as caller). Resolution order: env var, per-invocation param, frontmatter, parent model. |
| `effort` | inherit | Effort level: `low`, `medium`, `high`, `max`. |
| `maxTurns` | (none) | Maximum conversation turns before auto-stop. |
| `skills` | (none) | Skills preloaded at startup. Array of skill names. |
| `memory` | user | Persistent memory scope: `user` (global), `project` (shared), `local` (gitignored). |
| `background` | (none) | Read-only memory scope. Same options as `memory`. |
| `isolation` | (none) | Set to `worktree` for isolated git worktree copy. |
| `mcpServers` | (none) | MCP servers available to this agent. |
| `permissionMode` | inherit | `ask`, `bypassPermissions`, `dontAsk`. |
| `initialPrompt` | (none) | Initial task message when spawned. |
| `hooks` | (none) | Hooks scoped to agent lifecycle. |
| `color` | (none) | UI color (hex format). |

### Tool Access

Agents inherit all tools from the parent conversation by default. Restrict access with:

- **Allowlist** (`tools`): only these tools are available.
- **Denylist** (`disallowedTools`): these tools are removed; all others remain.
- **Both**: denylist applied first, then allowlist resolved against remaining pool.

### Plugin Agent Limitations

Agents defined in plugin scope (`plugin-name/agents/`) have restricted capabilities:
`hooks`, `mcpServers`, and `permissionMode` fields are ignored. To use these features,
copy the agent to `.claude/agents/` or configure permissions in `settings.json`.

## Hooks

Hooks are event handlers that execute at specific points in Claude Code's lifecycle. They
can block actions, inject context, modify tool inputs, or log events.

### Configuration

Hooks can be defined in multiple locations:

- `~/.claude/settings.json` — all projects
- `.claude/settings.json` — single project (shared via version control)
- `.claude/settings.local.json` — single project (gitignored)
- `hooks/hooks.json` — plugin-scoped
- Skill and agent frontmatter — component-scoped

### Hook Types

- **Command** (`type: "command"`): run shell scripts
- **HTTP** (`type: "http"`): POST to endpoints
- **Prompt** (`type: "prompt"`): send to Claude for evaluation
- **Agent** (`type: "agent"`): spawn subagents for verification

### Key Events

| Event | When | Can block? |
|-------|------|-----------|
| `PreToolUse` | Before tool executes | Yes |
| `PostToolUse` | After tool succeeds | No |
| `UserPromptSubmit` | User submits prompt | Yes |
| `Stop` | Claude finishes responding | Yes |
| `SubagentStart` | Subagent spawns | No |
| `SubagentStop` | Subagent finishes | No |
| `SessionStart` | Session begins | No |
| `FileChanged` | Watched file changes | No |

Blocking hooks return exit code 2 with stderr as feedback to Claude.

## MCP Servers

Plugins can bundle Model Context Protocol servers that connect Claude with external tools.

Define in `.mcp.json` at plugin root or inline in `plugin.json`:

```json
{
  "mcpServers": {
    "server-name": {
      "command": "${CLAUDE_PLUGIN_ROOT}/servers/my-server",
      "args": ["--config", "${CLAUDE_PLUGIN_ROOT}/config.json"],
      "env": { "DATA_DIR": "${CLAUDE_PLUGIN_DATA}" }
    }
  }
}
```

Servers start automatically when the plugin is enabled. They appear as standard MCP tools
in Claude's toolkit. Supported transports: stdio (default), HTTP, SSE, WebSocket.

## LLM Capabilities in Plugin Context

### Tool Access Control

Plugins control what Claude can do through two mechanisms:

- **Skills**: `allowed-tools` pre-approves specific tools without per-use permission
  dialogs. Supports glob patterns (`Bash(git add *)`) for scoped approval.
- **Agents**: `tools` (allowlist) and `disallowedTools` (denylist) control which tools
  the agent can access at all.

These are independent mechanisms — skill tool approval affects the permission UX; agent
tool restriction affects availability.

### Context Windows

Each agent runs in its own context window, independent of the main conversation. This is
both a feature (isolation prevents context pollution) and a constraint (large inputs can
stress agent context limits). Skills re-attached after compaction share a 25,000-token
budget.

### Model and Effort Selection

Both skills and agents can override the model and effort level via frontmatter. This
allows plugins to route different tasks to different models — e.g., using a faster model
for exploration and a more capable model for synthesis. The `effort` field controls
thinking depth without changing the model.
