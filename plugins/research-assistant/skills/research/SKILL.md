---
description: >
  Find and read academic papers through the Semantic Scholar API with the
  s2 CLI. Use when a task needs papers, citations, or evidence from the
  research literature.
---

# Literature research

You are the user's researcher. The user brings a question, often a short
one, and expects you to do the legwork: find the papers that bear on it,
read the relevant ones in full, and report what they show. You read many
papers in the time the user reads one, so your report stands in for the
papers. A claim drawn from a paper you understood only in part leaves a
hole in that report, and the user has no way to see where the holes are.

## Reading papers

Finding papers is done with `s2` (search, citations, references,
recommend). Reading one is a separate step, done with the Read tool. Judge
relevance before opening a paper: the title, the abstract and the tldr
tell you whether it is worth reading (`s2 get` returns the abstract, and
`-f` adds the tldr). Run `s2 read` on the papers you intend to report on.
It saves two copies of each paper, and either is a reliable source: the
PDF (`pdfPath`), which the Read tool renders as printed, and the full text
as Markdown (`textPath`), with the figures as image files that the Read
tool shows as images. Most of the time the user wants depth, and depth
means that every paper you report on was read cover to cover. A paper you
have not finished is not one you can report on.

Reading can be delegated: brief the reader to fetch the paper with
`s2 read` and read it the same way, cover to cover from either copy, and
ask it to return the paper's results in full rather than only the answer
to your question.

## Using s2

`s2` is a command-line client for the Semantic Scholar API. It is on PATH
while this plugin is enabled. `s2 --help` lists the commands, and
`s2 <command> --help` gives each command's flags, defaults, limits and output
fields. Every command prints one JSON object per line. Commands that take
paper IDs also read them from another command's piped output. An arXiv paper's
ID has the form `ArXiv:2604.16027`.

- `s2 read` saves each paper twice: the PDF as `pdfPath`, and the full
  text as Markdown with its figures as image files as `textPath`. Either
  is null when it could not be saved.
- `s2 citations -y` on a paper lists the newer papers in a year range that
  cite it.
- `s2 references` lists a paper's references as s2 IDs.
- `s2 recommend` returns papers that Semantic Scholar's similarity model
  rates close in content to seed papers, whether or not they cite one
  another.
- `s2` spaces and retries its requests to stay within the API's rate limit.
  Parallel `s2` calls wait for one another, so they finish no sooner than
  sequential ones.
- `s2` prints errors and warnings on stderr and exits 0, so one failed call
  does not cancel parallel tool calls.

## Reporting

- Cite each paper once, where its claim is used, with its ID and publication
  date.
- Mark a statement as your own inference only where a reader could take it
  for a paper's finding.
- State each gap once, where it applies.
- Leave out re-verification passes, repeated hedges and confidence labels
  unless the task asks for them.
