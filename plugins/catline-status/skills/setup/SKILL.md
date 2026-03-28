---
name: setup
description: This skill should be used when the user asks to "set up catline-status", "install the statusline", "configure the cat statusline", or wants to enable the catline-status plugin's statusline display in Claude Code.
---

Configure the catline-status statusline by updating `~/.claude/settings.json`.

The `statusLine` setting requires an absolute path because `settings.json` does not support variable expansion at runtime.

## Steps

1. Confirm `jq` is installed (`which jq`). If missing, instruct the user to install it and stop.

2. Read `~/.claude/settings.json` (create it with `{}` if it doesn't exist).

3. Add or update the `statusLine` key. Preserve all existing settings — only add/update this entry:

```json
{
  "statusLine": {
    "type": "command",
    "command": "${CLAUDE_PLUGIN_ROOT}/scripts/statusline.sh"
  }
}
```

4. Inform the user to restart Claude Code for the statusline to take effect.
