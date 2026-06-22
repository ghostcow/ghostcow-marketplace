---
name: paper-reading-guide
description: >
  Turn a paper into a structured reading guide: obtain the genuine full text
  (arXiv / DOI / PMC / URL / local PDF), render the pages that carry figures and
  diagrams, read it in full, and write a guide that maps where everything is and
  what is worth taking. Use whenever the user wants to deeply read, map, digest,
  extract, or build a reusable reading guide / "reading map" from a research paper
  or PDF — and for batch-processing several papers into one guide each. Triggers on
  phrasings like "make a reading guide", "map this paper", "deep-read this PDF",
  "render the figures and summarize", or handing over a list of papers to process.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

# Paper reading guide

Turn one paper into a **reading guide**: a short, faithful map of what the paper
contains, *where* each part lives (sections, pages, figures), and what is worth
lifting — written so a future reader (or a future you) can reconstruct the paper's
method without re-reading the whole thing.

The value comes from doing four things the obvious "summarize this PDF" shortcut
skips: getting the *real* full text (not an abstract or a paywall page), actually
*seeing* the figures, reading the *whole* thing, and recording exact *locations* so
the guide is verifiable rather than a vibe.

Work on **one paper per run**. To cover many papers, see *Batch mode* at the end —
fan out one subagent per paper so each gets a clean context and they run in parallel.

## The pipeline

### 1. Obtain the genuine full text
Resolve whatever the user gave you (an arXiv id, a DOI, a PMC id, a URL, a title, or
a local file) to a real PDF on disk. Save it somewhere predictable, e.g.
`<workdir>/pdf/<slug>.pdf`, where `<slug>` is a short kebab-case name for the paper.

Download robustly and then **verify it is the real article** — not an HTML error page,
a paywall splash, a cookie wall, an abstract-only page, or a book *review* standing in
for the book. See `references/fetching.md` for the download recipes, the open-access
fallbacks (Europe PMC, Unpaywall, repositories), and the verification checklist.

If after a reasonable effort the genuine full text is unreachable (hard paywall, no OA
copy), say so plainly, write the guide from the abstract + whatever you *can* verify,
and **label every such section as not-from-full-text**. A smaller honest guide beats a
confident fabricated one — never invent findings, page numbers, or figures.

### 2. Find and render the figure pages
A paper's figures, architecture diagrams, flowcharts, state machines, schemas,
matrices, and result plots often carry method that the prose only gestures at — so
*look at them*, don't skip them.

- Get the page count and locate captions cheaply first (e.g. `pdfinfo`, and
  `pdftotext` then grep for `^(Figure|Table|Fig\.) [0-9]`).
- Identify the pages that hold method-bearing figures/tables (skip pages that are only
  prose or references).
- **Render those pages as images** with the Read tool's `pages` parameter (it renders
  PDF pages visually; max 20 pages per call, so batch if needed) and actually read them.

Use judgement on depth: a framework/architecture paper rewards rendering every
diagram; a prose-only commentary may have nothing worth rendering — note that rather
than rendering filler.

### 3. Read the full text
Read the entire paper (every page), and integrate it with the figures you rendered.
`pdftotext` is a cheap way to read the body; render pages when layout or figures
matter. Don't write the guide from the abstract and intro alone.

### 4. Write the reading guide
Write the guide to `<workdir>/<slug>.md` following the template in
`references/output-template.md`. The non-negotiable spine is:

- a **reading map** — for each part, the section name + **exact page numbers** + any
  figure/table number + one line on what's there and why it matters. This is the
  deliverable that makes the guide trustworthy and reusable.
- **key figures** — what each rendered figure depicts and why it matters.
- **verbatim worth lifting** — directly reusable specifics (schemas, algorithms,
  templates, rubric items, exact phrasings) quoted *with page numbers*.

Tailor the framing to the user's purpose if they gave one ("I'm mining this for X") —
lead the *what to take* section with what serves that purpose. Otherwise write a
general-purpose guide.

## Integrity
- Page numbers, figure references, and quotes must be real — taken from the document
  you actually read. If you didn't see it, don't cite it.
- Confirm the artifact matches what the user asked for (right paper, right version) by
  checking the title/authors on page 1 before trusting it.
- Be honest about maturity and access: note sample sizes, venue, and any part of the
  guide that is inferred rather than read.

## Batch mode (many papers)
When given several papers, don't process them serially in one context. Spawn **one
subagent per paper**, each running this same pipeline on its assigned paper and writing
its own `<slug>.md`, so each has a clean context and they run in parallel. Give each
subagent the paper's identifiers/URLs, the target `<workdir>`, and any shared focus
("what we're mining these for"). A deterministic fan-out (e.g. a workflow that maps
papers → subagents) keeps this reliable at scale. Collect the guides, then optionally
write a short index that links them.
