# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "semanticscholar==0.11.0",
#     "filelock==3.25.0",
#     "httpx[socks]==0.28.1",
#     "anyio==4.12.1",
#     "certifi==2026.2.25",
#     "h11==0.16.0",
#     "httpcore==1.0.9",
#     "idna==3.11",
#     "nest-asyncio==1.6.0",
#     "pypdf==6.21.4",
#     "socksio==1.0.0",
#     "tenacity==9.1.4",
#     "typing_extensions==4.15.0",
# ]
# ///

import argparse
import asyncio
import io
import json
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import partial
from html.parser import HTMLParser
from pathlib import Path

import httpx
from filelock import AsyncFileLock
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from semanticscholar import AsyncSemanticScholar
from semanticscholar.ApiRequester import ApiRequester
from semanticscholar.Citation import Citation
from semanticscholar.Paper import Paper
from semanticscholar.PaginatedResults import PaginatedResults
from semanticscholar.SemanticScholarException import (
    BadQueryParametersException,
    ObjectNotFoundException,
    ServerErrorException,
)
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

SCAN_FIELDS = ["title", "paperId", "year", "authors", "citationCount"]
DETAIL_FIELDS = ["title", "paperId", "year", "authors", "abstract", "url", "openAccessPdf"]
AUTHOR_SCAN_FIELDS = ["authorId", "name", "paperCount", "citationCount", "hIndex"]

FIELDS_HELP = """\
paper fields
  paperId           str   unique S2 identifier (always returned)
  corpusId          int   secondary numeric identifier
  externalIds       obj   DOI, ArXiv, PubMed, DBLP, etc.
  url               str   link to the paper on semanticscholar.org
  title             str   paper title (always returned)
  abstract          str   paper abstract (null if unavailable for legal reasons)
  tldr              obj   auto-generated one-sentence summary (.text, .model)
  textAvailability  str   "fulltext", "abstract", or "none"
  venue             str   publication venue name
  publicationVenue  obj   structured venue with id, name, type, issn, url
  journal           obj   journal name, volume, and pages
  year              int   publication year
  publicationDate   str   full date as YYYY-MM-DD
  publicationTypes  arr   e.g. JournalArticle, Conference, Review
  citationStyles    obj   contains .bibtex citation string
  referenceCount    int   number of papers this paper cites
  citationCount     int   number of papers that cite this one
  influentialCitationCount
                    int   citations with significant impact
  isOpenAccess      bool  whether an open-access PDF exists
  openAccessPdf     obj   .url to PDF, .status, .license
  fieldsOfStudy     arr   high-level categories (e.g. Computer Science)
  s2FieldsOfStudy   arr   S2-assigned categories with .category and .source
  authors           arr   list of {authorId, name} objects
  citations         arr   papers that cite this one (nested paper objects)
  references        arr   papers this one cites (nested paper objects)
  embedding         obj   vector embedding (.model, .vector)

author fields (for search-author and author-papers)
  authorId          str   unique S2 author identifier
  name              str   author name
  affiliations      arr   list of affiliations
  paperCount        int   number of papers authored
  citationCount     int   total citations across all papers
  hIndex            int   h-index
  homepage          str   author's homepage URL
  url               str   link to the author on semanticscholar.org
  externalIds       obj   DBLP and other external IDs

citation/reference extras (for citations and references commands)
  contexts          arr   sentences of the citing paper where the citation appears
  intents           arr   why the paper was cited: background, methodology, result
  isInfluential     bool  S2's flag for citations that build substantially on the cited paper

publication types (for -t on search)
  JournalArticle, Conference, Review, CaseReport, ClinicalTrial,
  Dataset, Editorial, LettersAndComments, MetaAnalysis, News,
  Study, Book, BookSection

fields of study (for --fields-of-study on search)
  Computer Science, Medicine, Chemistry, Biology, Materials Science,
  Physics, Geology, Psychology, Art, History, Geography, Sociology,
  Business, Political Science, Economics, Philosophy, Mathematics,
  Engineering, Environmental Science, Agricultural and Food Sciences,
  Education, Law, Linguistics"""

FIELDS_HINT = "fields:  run 's2 fields' for all available field names"
ID_FORMS = (
    "S2 paperId, CorpusId:<n>, DOI:<doi>, ArXiv:<id>, MAG:<id>, ACL:<id>,\n"
    "        PMID:<id>, PMCID:<id>, URL:<url> (the URL: prefix is required;\n"
    "        arXiv DOIs 10.48550/... do not resolve, use ArXiv:<id>)"
)
CITATION_EXTRAS = (
    "add contexts,intents,isInfluential to -f to see how the citation is used:\n"
    "        contexts = citing sentences, intents = background/methodology/result,\n"
    "        isInfluential = S2's flag for substantial use"
)

# S2 answers 429 to 40-60% of keyed requests even at one request per 4 s
# (measured 2026-11-01), so a request gets many attempts with a short backoff.
RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=10) + wait_random(0, 1)
RETRY_EXCEPTIONS = retry_if_exception_type((ConnectionRefusedError, ServerErrorException))
RETRY_ATTEMPTS = 10
_RATE_INTERVAL = 1.1
_RATE_DIR = os.environ.get("TMPDIR", "/tmp")
_RATE_LOCK = os.path.join(_RATE_DIR, "s2_rate.lock")
_RATE_TS = os.path.join(_RATE_DIR, "s2_rate.ts")


class RateLimitedError(ConnectionRefusedError):
    """HTTP 429. retry_after is the server's Retry-After delay in seconds, or None if not sent."""

    def __init__(self, retry_after):
        super().__init__("HTTP status 429 Too Many Requests.")
        self.retry_after = retry_after


def _parse_retry_after(value):
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP-date), or None."""
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return None


def _retry_wait(retry_state):
    """Wait the server's Retry-After when given, else exponential backoff with jitter."""
    retry_after = getattr(retry_state.outcome.exception(), "retry_after", None)
    return retry_after if retry_after is not None else RETRY_WAIT(retry_state)


def _parse_response(r):
    """Map an S2 response to data or an exception, as the SDK's ApiRequester does."""
    if r.status_code == 200:
        data = r.json()
        return {} if len(data) == 1 and "error" in data else data
    if r.status_code == 400:
        raise BadQueryParametersException(r.json()["error"])
    if r.status_code == 403:
        raise PermissionError("HTTP status 403 Forbidden.")
    if r.status_code == 404:
        raise ObjectNotFoundException(r.json()["error"])
    if r.status_code == 429:
        raise RateLimitedError(_parse_retry_after(r.headers.get("Retry-After")))
    if r.status_code >= 500:
        raise ServerErrorException(f"HTTP status {r.status_code}.")
    return {}


class S2Requester(ApiRequester):
    def __init__(self, timeout, retry, auth_header=None):
        super().__init__(timeout, retry)
        self.auth_header = auth_header or {}

    async def get_data_async(self, url, parameters, headers, payload=None):
        # The SDK passes no headers for citations, references and author papers,
        # so the API key is merged in here for every request.
        headers = {**self.auth_header, **(headers or {})}
        retrying = AsyncRetrying(
            retry=RETRY_EXCEPTIONS,
            wait=_retry_wait,
            stop=stop_after_attempt(RETRY_ATTEMPTS if self.retry else 1),
        )
        async for attempt in retrying:
            with attempt:
                return await self._throttled_request(url, parameters, headers, payload)

    async def _throttled_request(self, url, parameters, headers, payload):
        # Cross-process rate limit: the file lock serializes every request of
        # every s2 process, retries included, and is held until the response
        # arrives. The timestamp file's mtime marks the last response, so the
        # server sees requests at least _RATE_INTERVAL apart.
        async with AsyncFileLock(_RATE_LOCK):
            try:
                last = os.path.getmtime(_RATE_TS)
            except FileNotFoundError:
                last = 0.0
            elapsed = time.time() - last
            if elapsed < _RATE_INTERVAL:
                await asyncio.sleep(_RATE_INTERVAL - elapsed)
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.request(
                        "POST" if payload else "GET",
                        url,
                        params=parameters.lstrip("&"),
                        timeout=self.timeout,
                        headers=headers,
                        json=payload,
                    )
            finally:
                Path(_RATE_TS).touch()
        return _parse_response(r)


class _ParamResults(PaginatedResults):
    """PaginatedResults that appends fixed query parameters to every page request."""

    def __init__(self, *args, extra_params, **kwargs):
        super().__init__(*args, **kwargs)
        self._extra_params = extra_params

    def _build_params(self):
        super()._build_params()
        self._parameters += self._extra_params


class S2Client(AsyncSemanticScholar):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._requester = S2Requester(self._timeout, self._retry, self.auth_header)

    async def get_paper_citations(self, paper_id, fields=None, limit=100, publication_date_or_year=None):
        # The citations endpoint filters citing papers by publicationDateOrYear;
        # the SDK method exposes no parameter for it.
        if publication_date_or_year is None:
            return await super().get_paper_citations(paper_id, fields=fields, limit=limit)
        return await _ParamResults.create(
            requester=self._requester,
            data_type=Citation,
            url=f"{self.api_url}{self.BASE_PATH_GRAPH}/paper/{paper_id}/citations",
            fields=fields,
            limit=limit,
            extra_params=f"&publicationDateOrYear={publication_date_or_year}",
        )

    async def get_papers(self, paper_ids, fields=None, return_not_found=False):
        # The batch endpoint answers with one entry per input ID, in input order,
        # null for IDs it cannot resolve. Not-found IDs come from that position.
        # not_found is None when the response length does not match the input,
        # since positions then say nothing about which IDs resolved.
        if len(paper_ids) > 500 or len(paper_ids) == 0:
            raise ValueError("The paper_ids parameter must be a list of 1 to 500 IDs.")
        data = await self._requester.get_data_async(
            f"{self.api_url}{self.BASE_PATH_GRAPH}/paper/batch",
            f"&fields={','.join(fields or Paper.SEARCH_FIELDS)}",
            self.auth_header,
            {"ids": paper_ids},
        )
        papers = [Paper(item) for item in data if item is not None]
        if not return_not_found:
            return papers
        if len(data) != len(paper_ids):
            return papers, None
        return papers, [pid for pid, item in zip(paper_ids, data) if item is None]


YEAR_RANGE = re.compile(r"\d{4}|\d{4}-\d{4}|\d{4}-|-\d{4}")


def year_range(value):
    """argparse type for -y: a year or year range, never a date."""
    if not YEAR_RANGE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"invalid year or range {value!r}: use 2020, 2018-2020, 2018- or -2015 "
            "(years only; for dates use search -d)"
        )
    return value


def read_ids(args_ids, stdin):
    ids = list(args_ids) if args_ids else []
    if not ids and stdin and not stdin.isatty():
        for raw_line in stdin:
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                pid = None
                if isinstance(obj, dict):
                    if "paperId" in obj:
                        pid = obj["paperId"]
                    elif "authorId" in obj:
                        pid = obj["authorId"]
                    elif "citingPaper" in obj:
                        pid = obj["citingPaper"].get("paperId")
                    elif "citedPaper" in obj:
                        pid = obj["citedPaper"].get("paperId")
                ids.append(pid if pid else stripped)
            except json.JSONDecodeError:
                ids.append(stripped)
    return ids


def output(data):
    print(json.dumps(data))


def make_client():
    api_key = os.environ.get("S2_API_KEY")
    if not api_key:
        env_file = Path.home() / ".s2.env"
        try:
            for line in env_file.read_text().splitlines():
                if line.startswith("S2_API_KEY="):
                    api_key = line.removeprefix("S2_API_KEY=").strip()
                    break
            else:
                print(f"warning: {env_file} exists but contains no S2_API_KEY=... line", file=sys.stderr)
        except FileNotFoundError:
            pass
    if not api_key:
        print(
            "warning: no Semantic Scholar API key; requests use the anonymous rate-limit pool "
            "and often fail with 429 (/research-assistant:setup configures a key)",
            file=sys.stderr,
        )
    return S2Client(api_key=api_key)


async def cmd_search(args):
    client = make_client()
    fields = args.fields.split(",") if args.fields else SCAN_FIELDS
    limit = args.limit
    kwargs = {}
    if args.year:
        kwargs["year"] = args.year
    if args.publication_date:
        kwargs["publication_date_or_year"] = args.publication_date
    if args.publication_types:
        kwargs["publication_types"] = args.publication_types.split(",")
    if args.open_access:
        kwargs["open_access_pdf"] = True
    if args.venue:
        kwargs["venue"] = args.venue.split(",")
    if args.fields_of_study:
        kwargs["fields_of_study"] = args.fields_of_study.split(",")
    if args.min_citations:
        kwargs["min_citation_count"] = args.min_citations
    if args.match_title:
        kwargs["match_title"] = True
    results = await client.search_paper(args.query, fields=fields, limit=min(limit, 100), **kwargs)
    if args.match_title:
        # SDK raises ObjectNotFoundException (caught in main) if no match.
        output(results.raw_data)
        return
    if results is None:
        return
    count = 0
    async for paper in results:
        output(paper.raw_data)
        count += 1
        if count >= limit:
            break


async def cmd_get(args):
    client = make_client()
    fields = args.fields.split(",") if args.fields else DETAIL_FIELDS
    ids = read_ids(args.ids, sys.stdin)
    if not ids:
        print("error: no paper IDs provided", file=sys.stderr)
        sys.exit(0)
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        papers, not_found = await client.get_papers(chunk, fields=fields, return_not_found=True)
        for paper in papers:
            output(paper.raw_data)
        if not_found is None:
            print(
                f"error: status unknown (API returned {len(papers)} results for {len(chunk)} IDs, "
                f"cannot tell which resolved): {', '.join(chunk)}",
                file=sys.stderr,
            )
        elif not_found:
            print(f"error: not found: {', '.join(not_found)}", file=sys.stderr)


def _describe_error(exc):
    """Translate per-ID exceptions into actionable model-readable strings."""
    if isinstance(exc, RetryError):
        last = exc.last_attempt.exception()
        if isinstance(last, ServerErrorException):
            return "S2 API server error after retries. This is transient — retry the same command."
        return "S2 API rate limited after retries. The request cannot be completed right now."
    if isinstance(exc, ObjectNotFoundException):
        return "Not found on Semantic Scholar. Verify the paper ID is correct."
    if isinstance(exc, httpx.TimeoutException):
        return "S2 API request timed out, server didn't respond."
    return str(exc)


def _extract_citation(item):
    """Extract raw_data from a citation/reference, or None if the nested paper is missing.

    The S2 API can return citation edges where the cited/citing paper has been
    removed or is unavailable — the SDK leaves item.paper as None in that case.
    """
    return item.raw_data if item.paper else None


def _extract_paper(item):
    """Extract raw_data from a paper object.

    No guard needed — unlike citations, paper items are the paper itself,
    not a wrapper with an optional nested field.
    """
    return item.raw_data


async def gather_paginated(client_method, ids, fields, limit, source_key, extract):
    """Fetch paginated results for multiple IDs concurrently, skipping failures."""

    async def fetch(source_id):
        results = await client_method(source_id, fields=fields, limit=min(limit, 1000))
        if results is None:
            return []
        items = []
        count = 0
        async for item in results:
            raw = extract(item)
            if raw is not None:
                items.append({**raw, source_key: source_id})
                count += 1
                if count >= limit:
                    break
        return items

    outcomes = await asyncio.gather(*[fetch(sid) for sid in ids], return_exceptions=True)
    for source_id, outcome in zip(ids, outcomes, strict=True):
        if isinstance(outcome, Exception):
            print(f"error: {source_id}: {_describe_error(outcome)}", file=sys.stderr)
        else:
            for item in outcome:
                output(item)


async def _citation_graph(client_method, args):
    """Shared implementation for citations and references commands."""
    client = make_client()
    fields = args.fields.split(",") if args.fields else SCAN_FIELDS
    ids = read_ids(args.ids, sys.stdin)
    if not ids:
        print("error: no paper IDs provided", file=sys.stderr)
        sys.exit(0)
    await gather_paginated(client_method(client), ids, fields, args.limit, "sourcePaperId", _extract_citation)


async def cmd_citations(args):
    if args.year:
        # publicationDateOrYear separates a range with ":"; -y uses "-" to match search.
        date_range = args.year.replace("-", ":")
        await _citation_graph(lambda c: partial(c.get_paper_citations, publication_date_or_year=date_range), args)
    else:
        await _citation_graph(lambda c: c.get_paper_citations, args)


async def cmd_references(args):
    await _citation_graph(lambda c: c.get_paper_references, args)


async def cmd_recommend(args):
    client = make_client()
    fields = args.fields.split(",") if args.fields else SCAN_FIELDS
    ids = read_ids(args.ids, sys.stdin)
    if not ids:
        print("error: no paper IDs provided", file=sys.stderr)
        sys.exit(0)
    limit = min(args.limit, 500)
    negative_ids = list(args.negative_ids) if args.negative_ids else None
    if len(ids) == 1 and not negative_ids:
        papers = await client.get_recommended_papers(ids[0], fields=fields, limit=limit, pool_from=args.pool)
    else:
        if args.pool != "recent":
            print(
                "warning: --pool is only available for single-seed recommendations; the list-based endpoint does not support pool selection",
                file=sys.stderr,
            )
        papers = await client.get_recommended_papers_from_lists(
            ids, fields=fields, limit=limit, negative_paper_ids=negative_ids
        )
    if papers is None:
        return
    if not papers:
        # The API answers 200 with an empty list when the pool holds nothing
        # similar; single-seed "recent" is often empty for older or non-CS seeds.
        if len(ids) == 1 and not negative_ids and args.pool == "recent":
            hint = " from the recent pool; try --pool all-cs, or list-based mode with more seeds"
        else:
            hint = "; try different seeds"
        print(f"warning: no recommendations returned for {', '.join(ids)}{hint}", file=sys.stderr)
        return
    for paper in papers:
        output(paper.raw_data)


async def cmd_search_author(args):
    client = make_client()
    fields = args.fields.split(",") if args.fields else AUTHOR_SCAN_FIELDS
    limit = args.limit
    results = await client.search_author(args.query, fields=fields, limit=min(limit, 1000))
    if results is None:
        return
    count = 0
    async for author in results:
        output(author.raw_data)
        count += 1
        if count >= limit:
            break


async def cmd_author_papers(args):
    client = make_client()
    fields = args.fields.split(",") if args.fields else SCAN_FIELDS
    ids = read_ids(args.ids, sys.stdin)
    if not ids:
        print("error: no author IDs provided", file=sys.stderr)
        sys.exit(0)
    await gather_paginated(client.get_author_papers, ids, fields, args.limit, "sourceAuthorId", _extract_paper)


READ_FIELDS = ["paperId", "title", "year", "externalIds", "openAccessPdf", "citationCount"]
REF_FIELDS = ["paperId", "title", "year"]
FETCH_HEADERS = {"User-Agent": "s2-cli/1.0 (research-assistant plugin; full-text reader)"}
FETCH_TIMEOUT = 60
FETCH_ATTEMPTS = 3
# pypdf logs recoverable PDF-structure problems as warnings; they are noise on stderr.
logging.getLogger("pypdf").setLevel(logging.ERROR)
_HEADING_TAGS = {f"h{i}": i for i in range(1, 7)}
_BLOCK_TAGS = {"p", "div", "section", "li", "tr", "table", "figure", "figcaption", "br", "blockquote", "pre", "dd", "dt"}
_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "button", "noscript", "svg"}
_PDF_HEADING = re.compile(
    r"(?:\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z\-:,&' ]{1,60}"
    r"|(?:Abstract|Introduction|Related Work|Background|Method|Methods|Experiments|Results|Discussion"
    r"|Conclusion|Conclusions|Limitations|References|Appendix|Acknowledgements|Acknowledgments))"
)
# A caption line starts with its label: "Figure 3: ...", "Fig. 3. ...", "Table 2 | ...", "FIGURE 3",
# "Figure 3 Flow diagram". Lines where a lowercase word follows the label ("Figure 3 shows") are
# in-text mentions and do not match.
_CAPTION = re.compile(r"(FIGURE|Figure|Fig\.|TABLE|Table)\s*(\d+)(?![\d.]\d)(.*)")
_CAPTION_MARK = re.compile(r"\[((?:Figure|Table) \d+), PDF page \d+\] ")


def _cache_dir():
    if os.environ.get("S2_CACHE_DIR"):
        return Path(os.environ["S2_CACHE_DIR"])
    # The Claude Code sandbox allows writes under TMPDIR, not the home directory.
    return Path(os.environ.get("TMPDIR", "/tmp")) / "s2-papers"


class _HtmlText(HTMLParser):
    """Plain text of an arXiv (LaTeXML) HTML paper, headings marked with '#'.

    Text inside <article> is kept when the page has one; math is replaced by
    its LaTeX alttext.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = {False: [], True: []}
        self.sections = {False: [], True: []}
        self._article = 0
        self._skip = 0
        self._heading = None
        self._heading_text = []

    def _emit(self, text):
        self.parts[self._article > 0].append(text)
        if self._heading is not None:
            self._heading_text.append(text)

    def handle_starttag(self, tag, attrs):
        if self._skip or tag in _SKIP_TAGS:
            if tag in _SKIP_TAGS or tag == "math":
                self._skip += 1
            return
        if tag == "article":
            self._article += 1
        elif tag == "math":
            self._emit(f" {dict(attrs).get('alttext', '')} ")
            self._skip += 1
        elif tag in _HEADING_TAGS:
            self._emit("\n\n" + "#" * _HEADING_TAGS[tag] + " ")
            self._heading, self._heading_text = tag, []
        elif tag in _BLOCK_TAGS:
            self._emit("\n")

    def handle_endtag(self, tag):
        if self._skip:
            if tag in _SKIP_TAGS or tag == "math":
                self._skip -= 1
            return
        if tag == "article":
            self._article -= 1
        elif tag == self._heading:
            heading = " ".join("".join(self._heading_text).split())
            if heading:
                self.sections[self._article > 0].append(heading)
            self._heading = None
            self._emit("\n")
        elif tag in _BLOCK_TAGS:
            self._emit("\n")

    def handle_data(self, data):
        if not self._skip:
            self._emit(data)

    def result(self):
        in_article = bool(self.parts[True])
        text = "".join(self.parts[in_article])
        lines = [" ".join(line.split()) if not line.startswith("#") else line.strip() for line in text.splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n", self.sections[in_article]


def html_to_text(html):
    """Return (text, sections) for an arXiv HTML paper."""
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    return parser.result()


def pdf_pages(data):
    """Text of each page of PDF bytes."""
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]


def pdf_to_text(data):
    """Return (text, sections) for PDF bytes; sections are best-effort heading lines."""
    text = "\n\n".join(pdf_pages(data))
    sections = [line.strip() for line in text.splitlines() if _PDF_HEADING.fullmatch(line.strip())]
    return text.strip() + "\n", sections


async def _fetch(http, url):
    """GET a non-S2 URL politely: retries on 429/5xx with backoff, None on failure."""
    for attempt in range(FETCH_ATTEMPTS):
        try:
            r = await http.get(url)
        except httpx.HTTPError:
            r = None
        if r is not None and r.status_code == 200:
            return r
        if r is not None and r.status_code != 429 and r.status_code < 500:
            return None
        if attempt < FETCH_ATTEMPTS - 1:
            await asyncio.sleep(2**attempt)
    return None


def _caption(line):
    """(label, score) when the line can start a caption, else None.

    Score 3: a ':' or '|' separator, or an all-caps label ("FIGURE 2"); 2: a '.' separator or the
    label alone on its line; 1: a capitalized word after the label ("Figure 1 Flow diagram").
    """
    m = _CAPTION.match(line.strip())
    if m is None:
        return None
    word, rest = m.group(1), m.group(3)
    label = f"{'Table' if word.upper() == 'TABLE' else 'Figure'} {m.group(2)}"
    if rest[:1] in (":", "|") or (word.isupper() and rest[:1] in ("", " ", ".", ":", "|")):
        return label, 3
    if rest[:1] == "." or not rest.strip():
        return label, 2
    if rest[:1] == " " and rest.strip()[:1].isupper():
        return label, 1
    return None


def _best_captions(lines):
    """For each label, the index of its highest-scoring caption line (earliest on ties)."""
    best = {}
    for i, line in enumerate(lines):
        found = _caption(line)
        if found and found[1] > best.get(found[0], (0, None))[0]:
            best[found[0]] = (found[1], i)
    return best


def find_figures(pages):
    """Figure and table captions in PDF page texts as [{label, caption, page}], in page order."""
    lines = [(number, line) for number, text in enumerate(pages, 1) for line in text.splitlines()]
    figures = []
    for label, (_, i) in sorted(_best_captions([line for _, line in lines]).items(), key=lambda kv: kv[1][1]):
        caption = " ".join(" ".join(line for _, line in lines[i : i + 6]).split())[:200]
        figures.append({"label": label, "caption": caption, "page": lines[i][0]})
    return figures


def mark_captions(text, figures):
    """Prefix each figure's best caption line in text with '[Figure N, PDF page P]'.

    Labels that already carry a marker are left as they are.
    """
    lines = text.splitlines()
    pages = {f["label"]: f["page"] for f in figures}
    for line in lines:
        marked = _CAPTION_MARK.match(line)
        if marked:
            pages.pop(marked.group(1), None)
    for label, (_, i) in _best_captions(lines).items():
        if label in pages:
            lines[i] = f"[{label}, PDF page {pages[label]}] {lines[i]}"
    return "\n".join(lines) + "\n"


async def _fetch_pdf(http, url):
    r = await _fetch(http, url)
    return r.content if r is not None and r.content.startswith(b"%PDF") else None


async def fetch_full_text(http, paper):
    """Return (text, sections, source, pdf).

    Text comes from arXiv HTML, else the arXiv PDF, else the open-access PDF.
    pdf is the paper's PDF bytes (arXiv first, then open access), or None.
    """
    text, sections, source, pdf = None, [], None, None
    arxiv_id = (paper.get("externalIds") or {}).get("ArXiv")
    if arxiv_id:
        r = await _fetch(http, f"https://arxiv.org/html/{arxiv_id}")
        if r is not None and 'class="ltx_document' in r.text:
            text, sections = html_to_text(r.text)
            source = "arxiv-html"
        pdf = await _fetch_pdf(http, f"https://arxiv.org/pdf/{arxiv_id}")
        if text is None and pdf is not None:
            text, sections = pdf_to_text(pdf)
            source = "arxiv-pdf"
    oa_url = (paper.get("openAccessPdf") or {}).get("url")
    if pdf is None and oa_url:
        pdf = await _fetch_pdf(http, oa_url)
        if text is None and pdf is not None:
            text, sections = pdf_to_text(pdf)
            source = "open-access-pdf"
    return text, sections, source, pdf


async def cached_full_text(http, paper):
    """fetch_full_text through the per-user cache: <paperId>.txt, .pdf and a .json sidecar.

    Returns a dict with path, sections, source, pdfPath and figures.
    """
    cache = _cache_dir()
    text_path, pdf_path, meta_path = (cache / f"{paper['paperId']}{ext}" for ext in (".txt", ".pdf", ".json"))
    if text_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if "figures" in meta:
            return {
                "path": str(text_path),
                "sections": meta["sections"],
                "source": meta["source"],
                "pdfPath": str(pdf_path) if pdf_path.exists() else None,
                "figures": meta["figures"],
            }
    text, sections, source, pdf = await fetch_full_text(http, paper)
    if text is None:
        return {"path": None, "sections": [], "source": None, "pdfPath": None, "figures": []}
    figures = []
    if pdf is not None:
        try:
            figures = find_figures(pdf_pages(pdf))
        except PyPdfError:
            pass
    cache.mkdir(parents=True, exist_ok=True)
    text_path.write_text(mark_captions(text, figures))
    if pdf is not None:
        pdf_path.write_bytes(pdf)
    meta_path.write_text(json.dumps({"sections": sections, "source": source, "figures": figures}))
    return {
        "path": str(text_path),
        "sections": sections,
        "source": source,
        "pdfPath": str(pdf_path) if pdf is not None else None,
        "figures": figures,
    }


async def _count(results, cap):
    count = 0
    if results is not None:
        async for _ in results:
            count += 1
            if count >= cap:
                break
    return count


async def read_paper(client, http, paper, refs, year):
    full = await cached_full_text(http, paper)
    if full["source"] is None:
        print(
            f"error: {paper['paperId']}: no full text found (no arXiv HTML/PDF or open-access PDF); "
            f"try a web search for the title: {paper.get('title')!r}",
            file=sys.stderr,
        )
    elif full["pdfPath"] is None:
        print(f"warning: {paper['paperId']}: no PDF found, so figures are unavailable", file=sys.stderr)
    references = []
    if refs:
        results = await client.get_paper_references(paper["paperId"], fields=REF_FIELDS, limit=min(refs, 1000))
        if results is not None:
            async for item in results:
                cited = (_extract_citation(item) or {}).get("citedPaper") or {}
                if cited.get("paperId"):
                    references.append({k: cited.get(k) for k in REF_FIELDS})
                if len(references) >= refs:
                    break
    in_range = None
    if year:
        results = await client.get_paper_citations(
            paper["paperId"], fields=["paperId"], limit=1000, publication_date_or_year=year.replace("-", ":")
        )
        # limit is the page size; pages continue until the API's 9999-result window ends.
        in_range = await _count(results, 9999)
    return {
        "paperId": paper["paperId"],
        "title": paper.get("title"),
        "year": paper.get("year"),
        "fullTextPath": full["path"],
        "fullTextSource": full["source"],
        "sections": full["sections"],
        "pdfPath": full["pdfPath"],
        "figures": full["figures"],
        "references": references,
        "citationCount": paper.get("citationCount"),
        "citationsInRange": in_range,
    }


def _http_client():
    return httpx.AsyncClient(headers=FETCH_HEADERS, timeout=FETCH_TIMEOUT, follow_redirects=True)


async def cmd_read(args):
    client = make_client()
    ids = read_ids(args.ids, sys.stdin)
    if not ids:
        print("error: no paper IDs provided", file=sys.stderr)
        sys.exit(0)
    async with _http_client() as http:
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            papers, not_found = await client.get_papers(chunk, fields=READ_FIELDS, return_not_found=True)
            if not_found:
                print(f"error: not found: {', '.join(not_found)}", file=sys.stderr)
            elif not_found is None:
                print(
                    f"error: status unknown (API returned {len(papers)} results for {len(chunk)} IDs, "
                    f"cannot tell which resolved): {', '.join(chunk)}",
                    file=sys.stderr,
                )
            for paper in papers:
                try:
                    output(await read_paper(client, http, paper.raw_data, args.refs, args.year))
                except Exception as exc:
                    print(f"error: {paper.raw_data.get('paperId')}: {_describe_error(exc)}", file=sys.stderr)


async def cmd_fields(_args):
    print(FIELDS_HELP)


def main():
    scan_default = ",".join(SCAN_FIELDS)
    detail_default = ",".join(DETAIL_FIELDS)
    author_scan_default = ",".join(AUTHOR_SCAN_FIELDS)

    parser = argparse.ArgumentParser(
        prog="s2",
        description="Semantic Scholar CLI",
        epilog=(
            "output: every command prints one JSON object per line to stdout\n"
            "errors: printed to stderr as 'error: ...'; the exit code is 0 even on error\n"
            "        (invalid arguments exit 2)\n"
            f"ids:    {ID_FORMS}\n"
            "piping: get, read, citations, references, recommend and author-papers read IDs\n"
            "        from stdin when -i is not used — one per line, either a raw ID or a\n"
            "        JSON object with paperId, authorId, citingPaper or citedPaper,\n"
            "        so the output of any command can be piped in\n"
            '        e.g. s2 search "transformers" | s2 get\n'
            "             s2 citations -i ArXiv:1706.03762 -y 2026 | s2 get\n"
            '             s2 search-author "Yoshua Bengio" -n 1 | s2 author-papers\n'
            '             s2 search "context compaction agents" -y 2026 -n 5 | s2 read -y 2026\n'
            "fields: -f overrides output fields on every command; run 's2 fields' for names\n"
            "help:   s2 <command> --help"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "search",
        help="Search papers by keyword",
        description="Search Semantic Scholar papers by relevance to a keyword query.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines, one object per paper with the requested fields\n"
            "filters combine with AND\n"
            f"{FIELDS_HINT}"
        ),
    )
    p.add_argument("query", help="search query string")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max results (default: 10, max: 1000)")
    p.add_argument("-y", "--year", type=year_range, help="publication year or range: 2020, 2018-2020, 2018- (from), -2015 (until)")
    p.add_argument(
        "-d",
        "--publication-date",
        help="publication date or range, dates as YYYY, YYYY-MM or YYYY-MM-DD, ends joined by ':', "
        "either end optional: 2020-06-01:2021-01-31, 2020-01:, :2015",
    )
    p.add_argument(
        "-t",
        "--publication-types",
        help="comma-separated types, e.g. JournalArticle,Conference,Review (all: 's2 fields')",
    )
    p.add_argument("--open-access", action="store_true", help="only papers with open-access PDFs")
    p.add_argument("--venue", help="comma-separated venue names, e.g. Nature,ICLR")
    p.add_argument(
        "--fields-of-study", help="comma-separated, e.g. Computer Science,Medicine (all: 's2 fields')"
    )
    p.add_argument("--min-citations", type=int, help="minimum citation count")
    p.add_argument(
        "--match-title",
        action="store_true",
        help="return only the single paper whose title best matches the query; ignores -n; "
        "prints 'error: Title match not found' when nothing matches",
    )

    p = sub.add_parser(
        "get",
        help="Fetch paper details by ID(s)",
        description="Fetch details for one or more papers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines, one object per paper found\n"
            "batch:  any number of IDs; sent 500 per request\n"
            "missing: IDs not found are listed on stderr as 'error: not found: ...';\n"
            "        papers that were found still print\n"
            "detail: add tldr, externalIds, citationStyles (BibTeX), publicationDate, venue\n"
            "        and other fields with -f\n"
            f"ids:    {ID_FORMS}\n"
            "stdin:  reads IDs from piped input when -i is omitted\n"
            f"{FIELDS_HINT}"
        ),
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="paper IDs")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {detail_default})")

    p = sub.add_parser(
        "read",
        help="Save a paper's full text and PDF, with its figures and references",
        description=(
            "Save each paper's full text as a plain-text file and its PDF, and describe the\n"
            "paper: section headings, figures and tables with their PDF pages, references as\n"
            "S2 IDs, and with -y how many papers cite it in a year range."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines, one object per paper:\n"
            "          paperId, title, year, citationCount\n"
            "          fullTextPath     the plain-text paper; each figure or table caption starts\n"
            "                           with '[Figure N, PDF page P]'\n"
            "          fullTextSource   arxiv-html, arxiv-pdf, open-access-pdf, or null\n"
            "          sections         section headings (complete from HTML, partial or empty\n"
            "                           from a PDF)\n"
            "          pdfPath          the saved PDF, or null\n"
            "          figures          {label, caption, page} per figure and table; page is the\n"
            "                           1-indexed PDF page\n"
            "          references       {paperId, title, year} per cited paper\n"
            "          citationsInRange citing papers in the -y range (null without -y; counted\n"
            "                           up to 9999)\n"
            "reading: the text file holds the words, tables as text and math as LaTeX. Plots and\n"
            "        diagrams exist only as images in the PDF: reading pdfPath with pages=P shows\n"
            "        page P as an image\n"
            "sources: text from arXiv HTML, else the arXiv PDF, else the S2 open-access PDF; the\n"
            "        PDF from arXiv, else the open-access PDF. Without full text, fullTextSource is\n"
            "        null and stderr names the title to search the web for; without a PDF, stderr\n"
            "        says figures are unavailable\n"
            "cache:  files are kept in $TMPDIR/s2-papers/ (or $S2_CACHE_DIR) and reused; delete a\n"
            "        paper's .txt/.pdf/.json there to refetch it\n"
            f"ids:    {ID_FORMS}\n"
            "stdin:  reads IDs from piped input when -i is omitted, e.g. from search or citations"
        ),
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="paper IDs to read")
    p.add_argument(
        "-y",
        "--year",
        type=year_range,
        help="count citing papers in this year or range: 2026, 2018-2020, 2018-, -2015 "
        "(same filter as citations -y)",
    )
    p.add_argument(
        "--refs", type=int, default=50, help="max references listed per paper (default: 50, 0 = none)"
    )

    p = sub.add_parser(
        "citations",
        help="Get papers that cite the given paper(s)",
        description="Fetch papers that cite the given paper(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'output: JSON lines, {"citingPaper": {<requested fields>}, "sourcePaperId": ...}\n'
            "        (sourcePaperId = which input paper was queried)\n"
            f"extras: {CITATION_EXTRAS}\n"
            "stdin:  reads IDs from piped input when -i is omitted\n"
            "limit:  applied per input paper, not globally\n"
            f"{FIELDS_HINT}"
        ),
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="paper IDs to get citations for")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {scan_default})")
    p.add_argument(
        "-n", "--limit", type=int, default=10, help="max citations per input paper (default: 10, max: 9999)"
    )
    p.add_argument(
        "-y",
        "--year",
        type=year_range,
        help="citing papers' publication year or range: 2026, 2018-2020, 2018- (from), -2015 (until); "
        "years only, not dates. Filtered by the API, which skips citing papers that have "
        "no publicationDate",
    )

    p = sub.add_parser(
        "references",
        help="Get papers cited by the given paper(s)",
        description="Fetch papers cited by (referenced by) the given paper(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'output: JSON lines, {"citedPaper": {<requested fields>}, "sourcePaperId": ...}\n'
            "        (sourcePaperId = which input paper was queried)\n"
            f"extras: {CITATION_EXTRAS}\n"
            "stdin:  reads IDs from piped input when -i is omitted\n"
            "limit:  applied per input paper, not globally\n"
            f"{FIELDS_HINT}"
        ),
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="paper IDs to get references for")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {scan_default})")
    p.add_argument(
        "-n", "--limit", type=int, default=10, help="max references per input paper (default: 10, max: 9999)"
    )

    p = sub.add_parser(
        "recommend",
        help="Recommend papers from seed paper(s)",
        description=(
            "Get paper recommendations similar to the seed papers.\n"
            "One seed uses single-paper recommendations;\n"
            "multiple seeds or --negative-ids uses list-based recommendations."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines, one object per paper with the requested fields (no sourcePaperId)\n"
            "stdin:  reads IDs from piped input when -i is omitted\n"
            f"{FIELDS_HINT}"
        ),
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="seed paper IDs (positive examples)")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max recommendations (default: 10, max: 500)")
    p.add_argument(
        "-x",
        "--negative-ids",
        nargs="+",
        metavar="ID",
        help="paper IDs the results should not resemble (forces list-based mode)",
    )
    p.add_argument(
        "--pool",
        default="recent",
        choices=["recent", "all-cs"],
        help="single-seed only: recent (default) = recently published papers, "
        "all-cs = all computer-science papers; recent is often empty for older or "
        "non-CS seeds (a warning names the seed); ignored with a warning in list-based mode",
    )

    p = sub.add_parser(
        "search-author",
        help="Search authors by name",
        description="Search Semantic Scholar for authors by name.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines, one object per author with the requested author fields\n"
            '        pipe into author-papers: s2 search-author "NAME" -n 1 | s2 author-papers\n'
            f"{FIELDS_HINT}"
        ),
    )
    p.add_argument("query", help="author name search string")
    p.add_argument("-f", "--fields", help=f"comma-separated author fields (default: {author_scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max results (default: 10, max: 1000)")

    p = sub.add_parser(
        "author-papers",
        help="Get papers by author ID(s)",
        description="Fetch papers written by the given author(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines with requested paper fields + sourceAuthorId\n"
            "        (sourceAuthorId = which input author was queried)\n"
            "stdin:  reads author IDs from piped input when -i is omitted,\n"
            "        e.g. from search-author output\n"
            "limit:  applied per input author, not globally\n"
            f"{FIELDS_HINT}"
        ),
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="S2 author IDs (authorId)")
    p.add_argument("-f", "--fields", help=f"comma-separated paper fields (default: {scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max papers per author (default: 10, max: 9999)")

    sub.add_parser(
        "fields",
        help="List all available field names",
        description=(
            "Show all paper, author, and citation/reference fields accepted by -f,\n"
            "plus the values accepted by search -t and --fields-of-study."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    args = parser.parse_args()

    handlers = {
        "search": cmd_search,
        "get": cmd_get,
        "read": cmd_read,
        "citations": cmd_citations,
        "references": cmd_references,
        "recommend": cmd_recommend,
        "search-author": cmd_search_author,
        "author-papers": cmd_author_papers,
        "fields": cmd_fields,
    }

    # Error strategy: all diagnostics go to stderr, stdout is exclusively JSONL.
    # All errors exit 0 — Claude Code treats a non-zero exit in one parallel
    # tool call as "sibling tool call errored" and aborts all concurrent calls.
    # Exiting 0 lets sibling calls complete normally; the stderr message is
    # sufficient for the model to understand and act on the error.
    try:
        asyncio.run(handlers[args.command](args))
    except BadQueryParametersException as e:
        print(f"error: {e} (run 's2 fields' for valid field names)", file=sys.stderr)
    except ObjectNotFoundException as e:
        print(f"error: {e}", file=sys.stderr)
    except PermissionError:
        print("error: forbidden — check your S2_API_KEY", file=sys.stderr)
    except RetryError as e:
        last = e.last_attempt.exception()
        if isinstance(last, ServerErrorException):
            print(
                "error: S2 API server error after retries — this is transient, retry the same command", file=sys.stderr
            )
        else:
            print(
                "error: S2 API rate limited after retries — the request cannot be completed right now", file=sys.stderr
            )
    except httpx.TimeoutException:
        print("error: S2 API request timed out, server didn't respond", file=sys.stderr)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
