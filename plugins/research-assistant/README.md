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
| `search-author` | Search authors by name |
| `author-papers` | Get papers by author ID(s) |
| `fields` | List all available field names for `-f` |

All commands output one JSON object per line. Commands that accept paper IDs take them via `-i ID [ID ...]` or read from stdin when `-i` is omitted, so commands are composable via pipes.

## Setup

API key (optional, increases rate limits):
create `~/.s2.env` containing `S2_API_KEY=<key>`.

## Dependencies

Requires [uv](https://docs.astral.sh/uv/). Dependencies are declared in the
PEP 723 metadata block in `s2.py` and resolved by `uv run` at runtime. The uv
cache is stored in `$TMPDIR/s2-uv-cache` to work within the Claude Code sandbox.

## Background

This plugin's research strategies are informed by the
[Asta Interaction Dataset](https://arxiv.org/abs/2602.23335) (Haddad et al.,
2026), a corpus of 200,000+ queries collected from
[Asta](https://asta.semanticscholar.org), AI2's research assistant platform
built on Semantic Scholar. Asta exposes two interfaces:

- [**Paper Finder**](https://paperfinder.allen.ai/) — LLM-powered literature
  search that decomposes queries, follows citations, and evaluates relevance
  through multi-step workflows
  ([blog](https://allenai.org/blog/paper-finder),
  [code](https://github.com/allenai/asta-paper-finder))
- [**Scholar QA**](https://qa.allen.ai) — scientific question answering that
  retrieves passages, extracts quotes, and synthesizes multi-section reports
  with per-claim attribution
  ([paper](https://arxiv.org/abs/2504.10861),
  [code](https://github.com/allenai/ai2-scholarqa-lib))

The Asta dataset introduces a taxonomy of 16 research query intents. This
plugin's six research strategies — Landscape Mapping, Targeted Evidence,
Concept Tracing, Constrained Review, Direct Retrieval, and Paper-Grounded
Writing — are derived from grouping those intents by the retrieval and
synthesis patterns they share.

## Limitations

- **No workflow isolation**: Asta launches separate, specialized workflows per
  research strategy (Paper Finder for retrieval, Scholar QA for synthesis).
  This plugin loads all strategy instructions into a single skill at session
  start. The researcher agent selects the appropriate strategy from context
  rather than invoking a dedicated sub-workflow. In prolonged conversations,
  the initial skill instructions may drift out of the agent's active context,
  which can degrade strategy adherence and output quality.

## Development

Requires [uv](https://docs.astral.sh/uv/). Run the test suite:

    scripts/run-tests -v
