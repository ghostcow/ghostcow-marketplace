#!/usr/bin/env bash
if [ -n "$CLAUDE_ENV_FILE" ]; then
  grep -qF "${CLAUDE_PLUGIN_ROOT}/scripts" "$CLAUDE_ENV_FILE" 2>/dev/null || \
    echo "export PATH=\"${CLAUDE_PLUGIN_ROOT}/scripts:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
exit 0
