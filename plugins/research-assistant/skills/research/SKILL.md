---
description: >
  Search and explore academic papers via Semantic Scholar.
  Use when the user asks about academic papers, citations,
  references, or research discovery.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

# s2 — Semantic Scholar CLI

`s2` is a CLI tool installed into PATH by a session-start hook.
Every command outputs one JSON object per line to stdout. Errors go
to stderr. All IDs accept S2 paper IDs, DOI:..., ArXiv:..., CorpusId:...,
PMID:..., PMCID:..., ACL:..., or URL from semanticscholar.org / arxiv.org.

ID-accepting commands take IDs via `-i ID [ID ...]` or read them from
stdin when `-i` is omitted — piped JSON lines with a `paperId` or
`authorId` field, or raw IDs. Override output fields on any command
with `-f field1,field2,...`. Run `s2 fields` for all field names.

## search

Find papers by keyword.
  s2 search QUERY [-n LIMIT] [-y YEAR] [-f FIELDS] [filters...]

  -n    max results (default: 10, max: 100)
  -y    year or range: 2020, 2018-2020
  -d    date range: 2020-06-01:2021-01-31, 2020-01:2021-06
  -t    publication types (comma-separated): JournalArticle, Conference,
        Review, CaseReport, ClinicalTrial, Dataset, Editorial,
        LettersAndComments, MetaAnalysis, News, Study, Book, BookSection
  --open-access          only papers with public PDFs
  --venue                venue names (comma-separated)
  --fields-of-study      e.g. Computer Science, Medicine
  --min-citations N      minimum citation count
  --match-title          return single best title match (ignores -n)

Default fields: title, paperId, year, authors, citationCount.

Use `-y` or `-d` to bound by time, `--fields-of-study` and `--venue`
to bound by domain, `-t` to restrict publication type, and
`--min-citations` to filter by impact. `--match-title` is the fastest
way to look up a known paper by title.

## get

Fetch full details for one or more papers by ID. Batches automatically
(500 IDs per request).
  s2 get [-i ID ...] [-f FIELDS]

Default fields: title, paperId, year, authors, abstract, url,
openAccessPdf. Use `-f` to add tldr, citationStyles, externalIds,
or other detail fields when needed.

## citations

Get papers that cite the given paper(s).
  s2 citations [-i ID ...] [-n LIMIT] [-f FIELDS]

  -n    max results per input paper (default: 10, max: 1000)

Each result includes a `sourcePaperId` field showing which input paper
was queried — use this to correlate results across multiple inputs.

Use `-f contexts,intents,isInfluential` to understand *how* papers cite
each other: `contexts` gives the surrounding text, `intents` labels the
reason (background, methodology, result comparison), `isInfluential`
flags high-impact citations.

## references

Get papers cited by the given paper(s). Same interface as `citations`.
  s2 references [-i ID ...] [-n LIMIT] [-f FIELDS]

  -n    max results per input paper (default: 10, max: 1000)

Also adds `sourcePaperId` and supports the same `-f contexts,intents,
isInfluential` extras.

## recommend

Get paper recommendations from seed paper(s).
  s2 recommend [-i ID ...] [-n LIMIT] [-f FIELDS] [-x ID ...] [--pool POOL]

  -n        max results (default: 10, max: 500)
  -x        negative example IDs — papers the results should NOT resemble
            (forces list-based mode)
  --pool    recommendation pool: "recent" (default) or "all-cs".
            Only available for single-seed; the list-based endpoint
            does not support pool selection.

One seed uses single-paper recommendations. Multiple seeds or `-x`
uses list-based recommendations. Use multiple diverse seeds to find
papers at the intersection of different topics.

## search-author

Search for authors by name.
  s2 search-author QUERY [-n LIMIT] [-f FIELDS]

  -n    max results (default: 10, max: 1000)

Default fields: authorId, name, paperCount, citationCount, hIndex.
Pipe results to `author-papers` to get an author's publications.

## author-papers

Get papers written by the given author(s).
  s2 author-papers [-i ID ...] [-n LIMIT] [-f FIELDS]

  -n    max papers per author (default: 10, max: 1000)

Each result includes a `sourceAuthorId` field showing which author was
queried — use this to correlate results across multiple authors.
Default output fields match `search` (scan fields).

## Error Handling

All errors print to stderr and exit 0 (so parallel tool calls are not
aborted). Actionable responses by error type:

- **Not found** — verify the paper/author ID is correct.
- **Server error** — transient; retry the same command.
- **Rate limited** — wait and retry, or reduce request volume.
- **Timeout** — the API didn't respond; retry.
- **Bad query** — check field names with `s2 fields`.
- **Forbidden** — check S2_API_KEY in ~/.s2.env.

## Sources and Disclosure

You draw on two sources during research: **papers** retrieved via s2
(verifiable, citable) and your own **knowledge** (broad but
unverifiable). The user needs to know which is which.

- Paper-grounded claims cite the paper by ID (S2 ID, DOI, or ArXiv ID).
- Knowledge-based claims are explicitly marked as general understanding.

Each strategy below specifies a source policy:

- **Papers-only** — every factual claim cites a retrieved paper. When
  papers are insufficient, say so rather than filling from knowledge.
- **Papers-primary** — write from papers. Knowledge provides framing,
  transitions, and connective tissue, clearly marked as such.
- **Knowledge-appropriate** — knowledge is expected and useful. Papers
  provide grounding and verification.

Users ask research questions naturally — they do not declare which
strategy they need. Read the query, identify the underlying intent from
the descriptions below, and follow the matching strategy. When a query
spans multiple intents, chain the relevant strategies: gather material
first, then synthesize or write.

## Landscape Mapping

The user wants to survey a field, explore what's been studied, identify
gaps or underexplored areas, generate research directions, or connect
insights across sub-fields.

**Source**: papers-only. Search-first — do not let prior knowledge bias
which clusters you find.
**Output**: write structured synthesis to file with section headings and
per-section summaries. Include paper IDs in every reference so the user
can retrieve details in future sessions.

1. Decompose the research question into 3–5 keyword variants covering
   synonyms, alternative terminology, and adjacent fields. This builds
   diverse anchors spanning different author groups, years, and venues —
   avoiding capture of only one cluster.

2. Run `s2 search` for each variant. Pipe results to `s2 get` for
   abstracts. Read the most relevant abstracts to understand the
   landscape before expanding.

3. Snowball outward: `references` backward to find foundational work,
   `citations` forward for recent developments. Use `-f contexts,intents`
   on citations to understand *how* papers relate — not just that they
   cite each other.

4. Use `recommend` with multiple seeds from different sub-clusters to
   find bridging work connecting otherwise separate literatures.

5. Iterate: new papers become inputs for the next round. When an
   iteration yields no new relevant papers, traversal is complete.
   Papers appearing across multiple traversals sit at intersections
   in the citation graph and are likely central.

6. If new papers keep appearing steadily rather than declining, a
   cluster was missed — try different terminology or new recommend seeds.

For **gap analysis**: gaps are areas where traversal yields nothing in an
expected area. Citation `intents` reveal "future work" mentions pointing
to recognized but unaddressed problems.

For **ideation**: high-convergence areas with recent citations indicate
active fronts. Sparse areas between clusters suggest opportunities. Use
`-y` to distinguish emerging from established lines of work.

Example — survey a field and explore its structure:
  s2 search "retrieval augmented generation" -n 20 --fields-of-study "Computer Science" | s2 get
  s2 search "knowledge grounded language models" -n 20 | s2 get
  s2 citations -i <anchor_id> -n 30 -f title,year,contexts,intents
  s2 recommend -i <id_1> <id_2> <id_3> -x <already_found_id> -n 20

## Targeted Evidence

The user wants to find evidence for or against a claim, or understand
causal and relational links between concepts.

**Source**: papers-only. Search-first — searching before forming
hypotheses prevents confirmation bias.
**Output**: include paper IDs with every claim. For substantial evidence
reviews, write to file.

1. Search for papers making or testing the claim. Use multiple phrasings
   to avoid bias toward one framing of the relationship.

2. Get seed papers, then `citations` with `-f contexts,intents` to find
   papers engaging with the claim. `contexts` shows the exact text where
   a citation appears; `intents` shows why (background, methodology,
   result comparison).

3. Trace the evidence chain: `references` from supporting papers to find
   the original evidence. `citations` from key papers to find
   replications, extensions, and contradictions.

4. Explicitly search for contradicting evidence. If all results confirm
   the claim, search for alternative explanations or competing
   theories — a one-sided result may reflect search bias, not consensus.

Example — find evidence for a causal claim:
  s2 search "sleep deprivation cognitive performance" -n 15 -t MetaAnalysis,ClinicalTrial | s2 get
  s2 citations -i <key_paper_id> -n 20 -f title,year,contexts,intents
  s2 search "sleep deprivation no effect cognition" -n 10

## Concept Tracing

The user wants to understand a concept, compare approaches or methods,
or find guidance on experimental designs and protocols.

**Source**: papers-primary, knowledge-supplementary. Knowledge-first —
use your understanding to formulate precise queries, then ground and
verify with papers. Clearly mark claims from general understanding.
**Output**: conversational for quick explanations. For thorough
comparisons or methodology surveys, write to file.

1. Frame the concept from your understanding to identify key terms,
   alternative names, and related ideas. This improves query precision.

2. Search for the concept. Follow `references` backward from early
   results to find the foundational or defining paper.

3. Follow `citations` forward to trace how understanding evolved —
   refinements, competing definitions, alternative interpretations.

4. For **comparisons**: search each approach separately, then
   `recommend` with seeds from both to find head-to-head comparisons
   and survey papers.

5. For **methodology**: `references` from reviews to find original
   protocols. `citations` forward for recent refinements and known
   limitations.

6. Verify your prior understanding against the papers. When papers
   contradict your knowledge, trust the papers and note the discrepancy.

Example — trace a concept to its origin and evolution:
  s2 search "batch normalization" --match-title | s2 references -n 20
  s2 citations -i <defining_paper_id> -n 30 -f title,year,citationCount
  s2 recommend -i <approach_1_id> <approach_2_id> -n 15

## Constrained Review

The user wants a review constrained to specific time periods, venues,
methods, or domains, or wants to find how a method has been applied in
a particular area.

**Source**: papers-only. Search-first.
**Output**: write to file. Structure for selective reading with section
headings, per-section summaries, and complete citation metadata.

1. Define constraints: time range (`-y` or `-d`), publication type
   (`-t`), venue (`--venue`), field of study (`--fields-of-study`),
   open access (`--open-access`), or citation impact (`--min-citations`).

2. Search with constraints applied. Use
   `-f fieldsOfStudy,publicationVenue,publicationTypes` to verify
   results fall within scope.

3. Snowball within bounds: follow `citations` and `references` but only
   retain papers satisfying the constraints.

4. For **application inquiry**: find the foundational method paper, then
   `citations` to find who applied it in the target domain. Use
   `recommend` with the method paper + domain-specific papers as seeds.

5. Use `-y` with successive year ranges to read the timeline. Combine
   with `citationCount` to distinguish foundational contributions from
   incremental work.

Example — focused review of a method in a specific domain and period:
  s2 search "federated learning" -n 20 -y 2020-2024 --fields-of-study "Medicine" -t JournalArticle,Conference | s2 get
  s2 citations -i <seminal_id> -n 30 -f title,year,fieldsOfStudy
  s2 search-author "key researcher" -n 1 | s2 author-papers -n 20

## Direct Retrieval

The user wants a specific paper, a specific fact or statistic, or a
particular tool, dataset, or benchmark.

**Source**: knowledge-appropriate — use your understanding to identify
the right query.
**Output**: conversational. Include paper IDs so the user can retrieve
details later or continue exploring.

Known paper:
  s2 search "attention is all you need" --match-title
  s2 get -i DOI:10.48550/arXiv.1706.03762

Known author:
  s2 search-author "Yoshua Bengio" -n 1 | s2 author-papers -n 10

Known fact: search the topic, `get` for abstracts, read the paper for
the specific datum. Follow `references` if the fact traces to an
earlier source.

Tool or dataset: search by name, then `references` from papers using it
to find the original release paper.

## Paper-Grounded Writing

The user wants to write literature-grounded content — review sections,
abstracts, methods descriptions — or needs help interpreting results in
the context of existing literature.

**Source**: papers-primary. Knowledge provides narrative structure,
transitions, and interpretation framing — not factual claims. Mark
knowledge-based framing explicitly.
**Output**: write to file. Structure with section headings and summaries
for selective reading. Every factual claim cites a paper by ID.

1. Gather papers first using the strategies above. Do not begin writing
   until you have sufficient material — premature writing leads to
   filling gaps from knowledge where papers are thin.

2. Read papers and extract verbatim quotes before drafting. Write from
   quotes, not from memory — this ensures claims are grounded and
   traceable.

3. Structure output for the user's purpose: literature review sections,
   methods descriptions, or expanded arguments. Section headings with
   brief summaries allow the user to skip, skim, or deep-dive without
   reading sequentially.

4. For **data interpretation**: search for studies with comparable
   methods or results. Use `citations -f contexts` to find how others
   interpreted similar findings. Frame interpretation through these
   papers, not through general knowledge alone.

5. When papers are insufficient to cover a section, say so and suggest
   what additional searches might fill the gap. Do not fill silently
   from knowledge.

Example — write a literature review section on prompt injection defenses:
  s2 search "prompt injection defense" -n 20 -y 2023-2024 | s2 get
  s2 search "LLM input filtering adversarial" -n 15 | s2 get
  # Read abstracts, extract verbatim quotes into working notes
  # Group quotes by theme, then draft each section from quotes
  # Cite every claim: "...detection accuracy of 94% (paperId: abc123)"

## Reading Papers

When s2 results include an `openAccessPdf` URL, use WebFetch to read
the paper directly. For large PDFs where WebFetch struggles, use curl
to download the file and Read to view it in page ranges of 5 pages at
a time.

If no open-access link is available, use WebSearch to find the paper by
title — it may be hosted on ArXiv, author pages, or institutional
repositories.

Use WebSearch and WebFetch also for supplementary context beyond
academic papers, or when s2 doesn't return what you need.
