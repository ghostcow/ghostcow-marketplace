---
description: >
  Get a Semantic Scholar API key and save it for the s2 CLI. Use when the
  user installs the research-assistant plugin or when s2 warns that no API
  key was found.
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Edit
---

# Setup

`s2` reads its Semantic Scholar API key from `S2_API_KEY` in the environment,
or from a line `S2_API_KEY=<key>` in `~/.s2.env`. Without a key, requests
share the anonymous rate-limit pool and often fail with HTTP 429.

1. Read `~/.s2.env`. If it already holds an `S2_API_KEY=` line, run
   `s2 search "test" -n 1` and report whether the key works. A 403 error
   means the key is invalid. Stop here when the key works.
2. Tell the user to request a key with the form at
   https://www.semanticscholar.org/product/api#api-key-form. Offer to draft
   the form's free-text answers, such as the project description and the
   intended use, from what the user tells you about their work. Semantic
   Scholar emails the key after it reviews the request.
3. When the user gives you the key, write `S2_API_KEY=<key>` to
   `~/.s2.env`, keeping any other lines in the file, and set the file's
   mode to 600. Do not print the key back.
4. Run `s2 search "test" -n 1` and report whether the key works.
