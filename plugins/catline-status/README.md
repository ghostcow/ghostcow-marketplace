# catline-status

Claude Code statusline showing model, working directory, git branch, and remaining context — with rotating cat face animations.

![statusline preview](statusline-preview.svg)

## Features

- **Status info** — model name, working directory, and git branch at a glance
- **Remaining context** — shows how much of the context window is still available
- **20 rotating cat faces** that change every second for decorative personality

## Setup

Run `/catline-status:setup` to configure the statusline automatically.

### Manual setup

Add this to your `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/path/to/airis-marketplace/plugins/catline-status/scripts/statusline.sh"
  }
}
```

## Requirements

- `jq` (for JSON parsing)
- `git` (for branch display)
