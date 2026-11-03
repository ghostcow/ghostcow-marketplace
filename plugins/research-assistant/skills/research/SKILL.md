---
description: >
  Find and read academic papers through the Semantic Scholar API with the
  s2 CLI. Use when a task needs papers, citations, or evidence from the
  research literature.
---

# Research with s2

`s2` is a command-line client for the Semantic Scholar API. It is on PATH
while this plugin is enabled. `s2 --help` lists the commands, and
`s2 <command> --help` gives each command's flags, defaults, limits and output
fields. Every command prints one JSON object per line. Commands that take
paper IDs also read them from another command's piped output. An arXiv paper's
ID has the form `ArXiv:2604.16027`.

## Task instructions come first

The prompt that starts the research sets its question, constraints, method and
report format. This skill applies where the prompt is silent.

## How the literature behaves

- A paper is its text and its figures. The abstract states the claim; the
  numbers, setup, baselines and limitations are in the body, and plots and
  diagrams exist only as images in the PDF. `s2 read` saves a paper's text
  and PDF, and lists each figure and table with its caption and PDF page.
  Reading the PDF with `pages` shows only those pages, as images.
- Keyword search finds papers that share the query's vocabulary. Work on the
  same problem under other names is reached through the citation graph, or
  through terms learned while reading.
- Newer work cites the papers it builds on. `s2 citations -y` on a central
  paper lists the newer papers in a year range that engage with it.
- A paper's references lead to older and foundational work. `s2 read` lists
  them as s2 IDs.
- `s2 recommend` returns papers that Semantic Scholar's similarity model
  rates close in content to seed papers, whether or not they cite one
  another.
- `s2` spaces and retries its requests to stay within the API's rate limit.
  Parallel `s2` calls wait for one another, so they finish no sooner than
  sequential ones.
- `s2` prints errors and warnings on stderr and exits 0, so one failed call
  does not cancel parallel tool calls.

## Citing

- Cite each paper once, where its claim is used, with its ID and publication
  date.
- Mark a statement as your own inference only where a reader could take it
  for a paper's finding.
- State each gap once, where it applies.
- Leave out re-verification passes, repeated hedges and confidence labels
  unless the task asks for them.
