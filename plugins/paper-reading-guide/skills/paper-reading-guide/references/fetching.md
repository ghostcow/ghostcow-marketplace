# Fetching & verifying a paper PDF

The goal: a real, complete PDF of the requested paper on disk. Publishers and preprint
hosts behave differently, so try in order and verify before trusting.

## Tools that help
- `pdfinfo file.pdf` — page count and metadata (also confirms it parses as a PDF).
- `pdftotext file.pdf out.txt` — cheap full-text extraction for reading + caption scan.
- `file file.pdf` — confirms it's actually a PDF, not HTML you saved with a `.pdf` name.
- The **Read tool with `pages`** — renders chosen PDF pages as images (figures!).

## Download recipes by source
Use a browser-like user agent and follow redirects; many hosts 403 a bare `curl`.

```
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
curl -L --fail -A "$UA" -o "<out>.pdf" "<url>"
```

- **arXiv**: `https://arxiv.org/pdf/<id>` (abstract page: `https://arxiv.org/abs/<id>`).
  arXiv ids encode date as `YYMM.NNNNN` — useful to confirm the year.
- **PMC / PubMed Central**: `https://europepmc.org/articles/<PMCID>?pdf=render` is the
  most reliable; also `https://www.ncbi.nlm.nih.gov/pmc/articles/<PMCID>/pdf/`. The PMC
  site itself often shows a CAPTCHA to scripts — prefer Europe PMC. If the PDF is gated,
  the **NCBI BioC API** returns the full text as structured text:
  `https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/<PMCID>/unicode`
  (use it to read the body when the PDF won't come, and say figures couldn't be rendered).
- **DOI**: `https://doi.org/<doi>` resolves to the publisher. Many are paywalled or
  Cloudflare-blocked (403/402) even when open-access — fall through to the OA fallbacks.
- **figshare / OSF / institutional repos**: often the OA home for paywalled-venue papers;
  figshare may hand back a ZIP — unzip and find the article PDF inside.

## Open-access fallbacks (when the primary URL fails)
1. **Unpaywall**: `https://api.unpaywall.org/v2/<doi>?email=you@example.com` → JSON with
   `best_oa_location.url_for_pdf` if a legal OA copy exists anywhere.
2. **Semantic Scholar**: the paper record's `openAccessPdf.url` field
   (`https://api.semanticscholar.org/graph/v1/paper/<id>?fields=openAccessPdf,externalIds,title,year,authors`).
3. **Europe PMC** `?pdf=render` for anything with a PMCID.
4. **WebSearch / WebFetch** for the title + "pdf" to find an author copy, a repository
   mirror (arXiv, ResearchGate, institutional ARROW/eprints), or a preprint.

## Verify it's the real article (before reading)
- `file` says PDF and `pdfinfo` reports a sensible page count (> 0, not 1-page splash).
- Read page 1: the **title and authors match** what was requested, and the **year** is
  what you expect.
- It's the *paper*, not a **book review** of it, a **table-of-contents**, a **supplement
  alone**, or an **abstract page**. Body sections (Methods/Results) are present.
- If verification fails, try the next URL / fallback before giving up.

## When the full text is genuinely unreachable
Hard paywall with no OA copy anywhere is a real outcome. Then: write the guide from the
verified abstract + any indexed snippets, **label every such part as not-from-full-text**,
note that figures could not be rendered, and record exactly what you tried. Do not
fabricate page numbers, figures, or findings to fill the template.
