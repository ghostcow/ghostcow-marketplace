---
description: "Build a structured reading guide for one or more papers (download, render figures, full read, map)."
argument-hint: "<arXiv id | DOI | PMC id | URL | path> [more papers...] [workdir: DIR] [focus: ...]"
---

Use the **paper-reading-guide** skill to produce a reading guide for each paper in:

$ARGUMENTS

How to proceed:

- Parse the arguments into a list of papers (arXiv ids, DOIs, PMC ids, URLs, or local
  PDF paths). If a `workdir:` or `→` target is given, write outputs there; otherwise
  default to `./reading-guides/` (PDFs under `./reading-guides/pdf/`). If a `focus:` note
  is given, let it steer each guide's *what to take* section.
- **One paper:** run the skill's pipeline directly (obtain full text → render figure
  pages → full read → write `<slug>.md`).
- **Several papers:** fan out **one subagent per paper**, each running the same pipeline
  on its assigned paper into the shared workdir, so they run in parallel with clean
  contexts. Then write a short `index.md` linking the guides.

Follow the skill's integrity rules: verify each PDF is the genuine full text, never
fabricate page numbers/figures/findings, and clearly flag anything written from an
abstract rather than the full text.
