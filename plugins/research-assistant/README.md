# research-assistant

A Claude Code plugin for academic research — finding papers, exploring citation networks, surveying fields, and synthesizing findings via the Semantic Scholar API.

## CLI: `s2`

## Commands

| Command | Description |
|---|---|
| `search` | Search papers by keyword |
| `get` | Fetch paper details by ID |
| `citations` | Get papers that cite a given paper |
| `references` | Get papers cited by a given paper |
| `recommend` | Recommend papers from seed paper(s) |
| `read` | Save a paper's full text and PDF, with its figures and references |
| `search-author` | Search authors by name |
| `author-papers` | Get papers by author ID(s) |
| `fields` | List all available field names for `-f` |

All commands output one JSON object per line. Commands that accept paper IDs take them via `-i ID [ID ...]` or read from stdin when `-i` is omitted, so commands are composable via pipes.

## Setup

Run `/research-assistant:setup` to get a Semantic Scholar API key and save it
to `~/.s2.env`. Without a key, `s2` warns on every call and its requests often
fail with HTTP 429.

## Dependencies

Requires [uv](https://docs.astral.sh/uv/). Dependencies are declared in the
PEP 723 metadata block in `s2.py` and resolved by `uv run` at runtime. The uv
cache is stored in `$TMPDIR/s2-uv-cache`.

## Research skill and agent

The `research` skill makes the model the user's researcher. It searches the
literature for papers that bear on the user's question, reads the promising
ones cover to cover with their figures, and reports what they show. The skill
also describes the `s2` tools and sets rules for the report. Instructions in
the task prompt take precedence over the skill. The `researcher` agent loads
the skill and answers research questions from the literature.

## Development

Requires [uv](https://docs.astral.sh/uv/). Run the test suite:

    scripts/run-tests -v
