# Reading-guide template

Write the guide to `<workdir>/<slug>.md` with these sections. Keep it tight — a guide
is a map, not a re-print. Fill what the paper supports; drop a section only if it
genuinely doesn't apply (and say why).

```markdown
# <slug>

**Citation & venue:** Authors (note count + any notable institutions), title, venue,
year. **Access:** where the PDF is (path), N pages, how obtained / any access issue.

**What this is & maturity:** 1–2 lines — type (benchmark / system / RCT / review /
preprint) and scope (sample size, dataset, deployment).

## What to take
The concrete, reusable ideas from THIS paper, for the reader's purpose. Be specific
("the importance ruler: ask 0–10, then 'why not lower?'"), not vague ("it discusses
motivation"). If the user gave a purpose, lead with what serves it.

## Reading map (where to read to reconstruct the method)
A table: Section | Pages | Fig/Table | What's there & why it matters. Exact page
numbers — this is the core deliverable. A future reader should be able to jump
straight to the right pages.

## Key figures & diagrams
For each figure/table you rendered: number, page, what it depicts, why it matters
(especially architecture / state / schema / result diagrams). If the paper has no
method-bearing figures, say so.

## Verbatim worth lifting
Directly reusable specifics, quoted WITH page numbers: schemas, variable lists,
algorithms/pseudocode, decision rules, prompt/template text, rubric dimensions,
example phrasings, key numbers. If none, say so.

## Caveats / transfer limits
Maturity, sample size, threats to validity, and what does NOT transfer to the reader's
setting. Flag anything written from the abstract rather than the full text.
```

## Notes
- `<slug>` is a short kebab-case id for the paper (e.g. `smith-2026-belief-memory`).
- Prefer a real reading map (page-anchored) over prose; that is what makes the guide
  reusable months later.
- If a key artifact (matrix, full table, example set) lives only in a supplement or an
  external repo the PDF points to, note that explicitly so the reader knows where to go.
