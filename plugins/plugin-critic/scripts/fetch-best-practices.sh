#!/bin/bash
#
# Fetch Claude prompting best practices guide.
# Exits non-zero on any failure — the review cannot proceed without this file.
#
# Usage: fetch-best-practices.sh <output-file>

set -euo pipefail

URL="https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices.md"
OUTPUT="${1:?Usage: fetch-best-practices.sh <output-file>}"

HTTP_CODE=$(curl --fail --silent --show-error --location \
  --output "$OUTPUT" \
  --write-out '%{http_code}' \
  "$URL" 2>&1) || {
  echo "ERROR: Failed to download best practices (curl exit code $?)." >&2
  echo "URL: $URL" >&2
  exit 1
}

if [ "$HTTP_CODE" -lt 200 ] || [ "$HTTP_CODE" -ge 300 ]; then
  echo "ERROR: Best practices fetch returned HTTP $HTTP_CODE." >&2
  echo "URL: $URL" >&2
  exit 1
fi

if [ ! -s "$OUTPUT" ]; then
  echo "ERROR: Best practices file is empty after download." >&2
  echo "URL: $URL" >&2
  exit 1
fi

if ! grep -q '^#' "$OUTPUT"; then
  echo "ERROR: Downloaded file does not look like markdown (no headings found)." >&2
  echo "This may be an error page or HTML response." >&2
  echo "URL: $URL" >&2
  exit 1
fi
