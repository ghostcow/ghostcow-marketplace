# paper-reading-guide

A Claude Code plugin that turns a paper into a **structured reading guide** — a faithful
map of what the paper contains, *where* each part lives (sections, pages, figures), and
what's worth taking.

It captures a specific four-step flow that beats "summarize this PDF":

1. **Obtain** the genuine full text from an arXiv id, DOI, PMC id, URL, title, or local
   PDF — with open-access fallbacks (Europe PMC, Unpaywall, Semantic Scholar, repos) and
   a verification check that it's the real article, not an abstract or paywall page.
2. **Render the figure pages** as images and actually look at the diagrams, schemas, and
   plots — where method often hides.
3. **Read the full text**, integrated with the figures.
4. **Write a reading guide**: a page-anchored *reading map*, the key figures, and the
   *verbatim worth lifting* (schemas, algorithms, templates, exact phrasings, quoted with
   page numbers).

## Usage

It triggers automatically when you ask to deeply read, map, or build a reading guide
from a paper or PDF. Or invoke the command explicitly:

```
/reading-guide 2604.17283
/reading-guide 10.1145/3772318.3791123 → ./guides focus: behavior-change coaching
/reading-guide 2602.14643 2603.00774 PMC13215495    # batch: one subagent per paper
```

Given several papers, it fans out **one subagent per paper** so they run in parallel
with clean contexts, then writes an index linking the guides.

## Output

One `<slug>.md` per paper (default under `./reading-guides/`), each with: citation &
maturity · what to take · a page-anchored reading map · key figures · verbatim worth
lifting · caveats. PDFs are kept under `pdf/`.

## Integrity

Page numbers, figures, and quotes are taken from the document actually read. If the full
text is genuinely unreachable (hard paywall, no OA copy), the guide is written from the
abstract and **every such part is labelled as not-from-full-text** — it never fabricates
findings to fill the template.

## Helpful local tools

`pdfinfo`, `pdftotext`, and `file` (from poppler) make fetching and reading cheaper;
PDF figure pages are rendered via Claude's Read tool. None are strictly required.

License: MIT.
