# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "filelock==3.25.0",
#     "httpx[socks]==0.28.1",
#     "anyio==4.12.1",
#     "certifi==2026.2.25",
#     "h11==0.16.0",
#     "httpcore==1.0.9",
#     "idna==3.11",
#     "pymupdf==2.1",
#     "pymupdf4llm==2.1",
#     "pymupdf-layout==2.1",
#     "onnxruntime==1.31.1",
#     "numpy==2.5.4",
#     "networkx==3.7",
#     "flatbuffers==25.12.19",
#     "protobuf==7.36.2",
#     "packaging==26.3",
#     "psutil==7.2.2",
#     "pdfplumber==0.11.10",
#     "pdfminer.six==20260107",
#     "pypdfium2==5.10.1",
#     "pillow==12.2.0",
#     "cffi==2.0.0",
#     "cryptography==49.0.0",
#     "pycparser==3.0",
#     "charset-normalizer==3.4.7",
#     "tabulate==0.10.0",
#     "openpyxl==3.1.5",
#     "et_xmlfile==2.0.0",
#     "PyYAML==6.0.3",
#     "skia-python==144.1",
#     "pybind11==3.1.0",
#     "socksio==1.0.0",
#     "tenacity==9.1.4",
#     "truststore==0.10.5",
#     "typing_extensions==4.15.0",
# ]
# ///

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import partial
from html import escape
from html.parser import HTMLParser
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Any, Required, TypedDict

import httpx
import truststore
from filelock import AsyncFileLock
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
RETRY_ATTEMPTS = 10
_RATE_INTERVAL = 1.1
_RATE_DIR = os.environ.get("TMPDIR", "/tmp")
_RATE_LOCK = os.path.join(_RATE_DIR, "s2_rate.lock")
_RATE_TS = os.path.join(_RATE_DIR, "s2_rate.ts")

API_URL = "https://api.semanticscholar.org"
GRAPH_URL = f"{API_URL}/graph/v1"
RECOMMENDATIONS_URL = f"{API_URL}/recommendations/v1"
# Largest offset + limit each paged endpoint accepts: relevance search answers
# 400 above 1000; the other paged endpoints, author search included, answer 400
# at 10000 and above.
SEARCH_WINDOW = 1000
PAGED_WINDOW = 9999


# Shapes of the API responses this script reads fields from. Every other field
# passes through untouched, so these name only the keys the code uses; total=False
# because which keys are present depends on the requested fields.


class Paper(TypedDict, total=False):
    paperId: Required[str | None]  # always returned; null only for unresolved nested references
    title: str | None
    year: int | None
    externalIds: dict[str, str] | None
    openAccessPdf: dict | None
    citationCount: int | None


class CitationEdge(TypedDict, total=False):
    """An item of /paper/{id}/citations; citingPaper is missing or null for removed papers."""

    citingPaper: Paper | None


class ReferenceEdge(TypedDict, total=False):
    """An item of /paper/{id}/references; citedPaper is missing or null for removed papers."""

    citedPaper: Paper | None


class Page(TypedDict, total=False):
    """One page of an offset-paged endpoint. next is absent on the last page; data is
    absent on an empty search result."""

    offset: int
    next: int
    total: int
    data: list[dict]


class Recommendations(TypedDict, total=False):
    recommendedPapers: list[Paper]


class S2Error(Exception):
    """An S2 API response that is an error rather than data."""


class BadQueryParametersException(S2Error):
    """HTTP 400: the API rejected the request's parameters."""


class ObjectNotFoundException(S2Error):
    """HTTP 404: the paper, author or title match does not exist."""


class ServerErrorException(S2Error):
    """HTTP 5xx: a server-side failure, retried."""


class S2APIError(S2Error):
    """A status or body the API contract does not define."""


class RateLimitedError(ConnectionRefusedError):
    """HTTP 429. retry_after is the server's Retry-After delay in seconds, or None if not sent."""

    def __init__(self, retry_after):
        super().__init__("HTTP status 429 Too Many Requests.")
        self.retry_after = retry_after


RETRY_EXCEPTIONS = retry_if_exception_type((ConnectionRefusedError, ServerErrorException))


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


def _error_message(r):
    """The message of an error response: its "error" field (graph API) or "message" field (gateway)."""
    try:
        body = r.json()
    except ValueError:
        return r.text[:200] or f"HTTP status {r.status_code}."
    if isinstance(body, dict):
        return body.get("error") or body.get("message") or f"HTTP status {r.status_code}."
    return f"HTTP status {r.status_code}."


def _parse_response(r):
    """Map an S2 response to its JSON body, or raise the exception for its status."""
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, dict) and set(data) == {"error"}:
            raise S2APIError(data["error"])
        return data
    if r.status_code == 400:
        raise BadQueryParametersException(_error_message(r))
    if r.status_code in (401, 403):
        raise PermissionError(f"HTTP status {r.status_code} {_error_message(r)}")
    if r.status_code == 404:
        raise ObjectNotFoundException(_error_message(r))
    if r.status_code == 429:
        raise RateLimitedError(_parse_retry_after(r.headers.get("Retry-After")))
    if r.status_code >= 500:
        raise ServerErrorException(f"HTTP status {r.status_code}.")
    raise S2APIError(f"unexpected HTTP status {r.status_code}: {_error_message(r)}")


class S2Requester:
    """Sends S2 API requests through the cross-process rate limit, retrying 429 and 5xx."""

    def __init__(self, timeout, retry, auth_header=None):
        self.timeout = timeout
        self.retry = retry
        self.auth_header = auth_header or {}

    async def request(self, url, params, payload=None) -> Any:
        """GET url (POST when payload is given) with query params; returns the parsed JSON body."""
        retrying = AsyncRetrying(
            retry=RETRY_EXCEPTIONS,
            wait=_retry_wait,
            stop=stop_after_attempt(RETRY_ATTEMPTS if self.retry else 1),
        )
        async for attempt in retrying:
            with attempt:
                return await self._throttled_request(url, params, payload)
        raise AssertionError("unreachable: tenacity raises RetryError once attempts run out")

    async def _throttled_request(self, url, params, payload):
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
                        params=params,
                        timeout=self.timeout,
                        headers=self.auth_header,
                        json=payload,
                    )
            finally:
                Path(_RATE_TS).touch()
        return _parse_response(r)


class S2Client:
    """Client for the S2 Graph and Recommendations APIs; every result is the API's JSON object.

    Paged methods are coroutines returning an async iterator over all items the
    endpoint's window allows; callers stop iterating once they have enough.
    """

    def __init__(self, api_key=None, timeout=30, retry=True):
        self.auth_header = {"x-api-key": api_key} if api_key else {}
        self._requester = S2Requester(timeout, retry, self.auth_header)

    async def _request(self, url, params, payload=None) -> Any:
        return await self._requester.request(url, params, payload)

    async def _pages(self, url, params, page_size, window) -> AsyncIterator[Any]:
        """Yield the items of an offset-paged endpoint, requesting page_size items at a time.

        The API keeps offset + limit within window. Paging ends at the first page
        without items, without an integer "next", or whose "next" does not move past
        its offset, so no response can make the same page be requested twice.
        """
        offset = 0
        while offset < window:
            page: Page = await self._request(url, {**params, "offset": offset, "limit": min(page_size, window - offset)})
            items = page.get("data") if isinstance(page, dict) else None
            if not isinstance(items, list) or not items:
                return
            for item in items:
                yield item
            next_offset = page.get("next")
            if not isinstance(next_offset, int) or next_offset <= offset:
                return
            offset = next_offset

    async def search_paper(self, query, fields, limit, **filters) -> AsyncIterator[Paper]:
        """Relevance search over papers; filters are the keyword arguments of _search_params."""
        return self._pages(f"{GRAPH_URL}/paper/search", _search_params(query, fields, **filters), limit, SEARCH_WINDOW)

    async def match_paper_title(self, query, fields, **filters) -> Paper:
        """The paper whose title best matches query; raises ObjectNotFoundException when none does."""
        page = await self._request(f"{GRAPH_URL}/paper/search/match", _search_params(query, fields, **filters))
        data = page.get("data") if isinstance(page, dict) else None
        if not data:
            raise ObjectNotFoundException("Title match not found")
        return data[0]

    async def search_author(self, query, fields, limit) -> AsyncIterator[dict]:
        return self._pages(f"{GRAPH_URL}/author/search", {"query": query, "fields": ",".join(fields)}, limit, PAGED_WINDOW)

    async def get_paper_citations(
        self, paper_id, fields, limit, publication_date_or_year=None
    ) -> AsyncIterator[CitationEdge]:
        """Citation edges, each {"citingPaper": {...}, ...}."""
        params = {"fields": ",".join(fields)}
        if publication_date_or_year:
            params["publicationDateOrYear"] = publication_date_or_year
        return self._pages(f"{GRAPH_URL}/paper/{paper_id}/citations", params, limit, PAGED_WINDOW)

    async def get_paper_references(self, paper_id, fields, limit) -> AsyncIterator[ReferenceEdge]:
        """Reference edges, each {"citedPaper": {...}, ...}."""
        return self._pages(f"{GRAPH_URL}/paper/{paper_id}/references", {"fields": ",".join(fields)}, limit, PAGED_WINDOW)

    async def get_author_papers(self, author_id, fields, limit) -> AsyncIterator[Paper]:
        return self._pages(f"{GRAPH_URL}/author/{author_id}/papers", {"fields": ",".join(fields)}, limit, PAGED_WINDOW)

    async def get_papers(self, paper_ids, fields) -> tuple[list[Paper], list[str] | None]:
        """Papers for up to 500 IDs, and the IDs that did not resolve."""
        # The batch endpoint answers with one entry per input ID, in input order,
        # null for IDs it cannot resolve. Not-found IDs come from that position.
        # not_found is None when the response length does not match the input,
        # since positions then say nothing about which IDs resolved.
        if len(paper_ids) > 500 or len(paper_ids) == 0:
            raise ValueError("The paper_ids parameter must be a list of 1 to 500 IDs.")
        data = await self._request(f"{GRAPH_URL}/paper/batch", {"fields": ",".join(fields)}, {"ids": paper_ids})
        if not isinstance(data, list):
            raise S2APIError(f"paper batch answered {type(data).__name__}, expected a list")
        papers = [item for item in data if item is not None]
        if len(data) != len(paper_ids):
            return papers, None
        return papers, [pid for pid, item in zip(paper_ids, data) if item is None]

    async def get_recommended_papers(self, paper_id, fields, limit, pool_from="recent") -> list[Paper]:
        data = await self._request(
            f"{RECOMMENDATIONS_URL}/papers/forpaper/{paper_id}",
            {"fields": ",".join(fields), "limit": limit, "from": pool_from},
        )
        return _recommended(data)

    async def get_recommended_papers_from_lists(
        self, positive_paper_ids, fields, limit, negative_paper_ids=None
    ) -> list[Paper]:
        payload = {"positivePaperIds": positive_paper_ids, "negativePaperIds": negative_paper_ids or []}
        data = await self._request(
            f"{RECOMMENDATIONS_URL}/papers/", {"fields": ",".join(fields), "limit": limit}, payload
        )
        return _recommended(data)


def _search_params(
    query,
    fields,
    year=None,
    publication_date_or_year=None,
    publication_types=None,
    open_access_pdf=False,
    venue=None,
    fields_of_study=None,
    min_citation_count=None,
):
    """Query parameters shared by /paper/search and /paper/search/match."""
    params = {"query": query, "fields": ",".join(fields)}
    if year:
        params["year"] = year
    if publication_date_or_year:
        params["publicationDateOrYear"] = publication_date_or_year
    if publication_types:
        params["publicationTypes"] = ",".join(publication_types)
    if open_access_pdf:
        params["openAccessPdf"] = ""
    if venue:
        params["venue"] = ",".join(venue)
    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)
    if min_citation_count:
        params["minCitationCount"] = min_citation_count
    return params


def _recommended(data: Recommendations) -> list[Paper]:
    """The recommendedPapers list of a recommendations response."""
    papers = data.get("recommendedPapers") if isinstance(data, dict) else None
    if not isinstance(papers, list):
        raise S2APIError("recommendations response has no recommendedPapers list")
    return papers


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


RECOMMEND_MAX = 500  # the recommendations endpoints return at most 500 papers


def _page_size(limit, page_max):
    """Items to request per page: the whole limit when it fits in one page, else the endpoint's page maximum."""
    return page_max if limit is None else min(limit, page_max)


async def _output_up_to(results, limit):
    """Print items from results, stopping after limit of them; limit None prints every item."""
    count = 0
    async for item in results:
        output(item)
        count += 1
        if limit is not None and count >= limit:
            break


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
        # No match raises ObjectNotFoundException, which main reports.
        output(await client.match_paper_title(args.query, fields=fields, **kwargs))
        return
    results = await client.search_paper(args.query, fields=fields, limit=_page_size(limit, 100), **kwargs)
    await _output_up_to(results, limit)


async def cmd_get(args):
    client = make_client()
    fields = args.fields.split(",") if args.fields else DETAIL_FIELDS
    ids = read_ids(args.ids, sys.stdin)
    if not ids:
        print("error: no paper IDs provided", file=sys.stderr)
        sys.exit(0)
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        papers, not_found = await client.get_papers(chunk, fields=fields)
        for paper in papers:
            output(paper)
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
    if isinstance(exc, PermissionError):
        return "Forbidden. Check your S2_API_KEY."
    if isinstance(exc, httpx.TimeoutException):
        return "S2 API request timed out, server didn't respond."
    return str(exc)


def _extract_citation(item: CitationEdge | ReferenceEdge) -> CitationEdge | ReferenceEdge | None:
    """A citation or reference edge, or None when it has no nested paper.

    The S2 API can return edges whose citingPaper/citedPaper is missing or null
    because the paper was removed or is unavailable.
    """
    paper = item.get("citingPaper", item.get("citedPaper"))
    return item if paper is not None else None


def _extract_paper(item: Paper) -> Paper:
    """A paper item, which is the paper itself rather than an edge around one."""
    return item


async def gather_paginated(client_method, ids, fields, limit, source_key, extract):
    """Fetch paginated results for multiple IDs concurrently, skipping failures."""

    async def fetch(source_id):
        results = await client_method(source_id, fields=fields, limit=_page_size(limit, 1000))
        items = []
        async for item in results:
            raw = extract(item)
            if raw is not None:
                items.append({**raw, source_key: source_id})
                if limit is not None and len(items) >= limit:
                    break
        return items

    outcomes = await asyncio.gather(*[fetch(sid) for sid in ids], return_exceptions=True)
    for source_id, outcome in zip(ids, outcomes, strict=True):
        if isinstance(outcome, BaseException):
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
    limit = _page_size(args.limit, RECOMMEND_MAX)
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
        output(paper)


async def cmd_search_author(args):
    client = make_client()
    fields = args.fields.split(",") if args.fields else AUTHOR_SCAN_FIELDS
    limit = args.limit
    results = await client.search_author(args.query, fields=fields, limit=_page_size(limit, 1000))
    await _output_up_to(results, limit)


async def cmd_author_papers(args):
    client = make_client()
    fields = args.fields.split(",") if args.fields else SCAN_FIELDS
    ids = read_ids(args.ids, sys.stdin)
    if not ids:
        print("error: no author IDs provided", file=sys.stderr)
        sys.exit(0)
    await gather_paginated(client.get_author_papers, ids, fields, args.limit, "sourceAuthorId", _extract_paper)


READ_FIELDS = ["paperId", "title", "year", "externalIds", "openAccessPdf", "citationCount"]
# Printed with every saved PDF so the reminder travels with the paper it applies to.
READ_NOTE = (
    "To report on this paper, read it cover to cover from either copy: "
    "pdfPath with the Read tool, or textPath with its linked figure images."
)
FETCH_HEADERS = {"User-Agent": "s2-cli/1.0 (research-assistant plugin; full-text reader)"}
FETCH_TIMEOUT = 60
FETCH_ATTEMPTS = 3
# A read's output (metadata and citation counts included) is reused for this long.
READ_CACHE_SECONDS = 24 * 60 * 60
# Figure files of one paper are fetched together, the way a browser loads the page.
IMAGE_CONNECTIONS = 8
# SVG figures draw their text as glyph outlines, so they are rendered to PNG at this scale.
SVG_SCALE = 2
_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "button", "noscript"}
_BLOCK_TAGS = {"p", "div", "section", "figure", "figcaption", "blockquote", "pre", "dd", "dt", "br"}
_HEADING_TAGS = {f"h{i}": i for i in range(1, 7)}
_TABLE_TAGS = {"table", "thead", "tbody", "tfoot", "tr", "td", "th"}
_EQUATION_TABLE_CLASSES = {"ltx_equation", "ltx_equationgroup", "ltx_eqn_table", "ltx_eqn_align"}
# Image formats the Read tool shows to the model as images.
_RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _cache_dir():
    if os.environ.get("S2_CACHE_DIR"):
        return Path(os.environ["S2_CACHE_DIR"])
    # The Claude Code sandbox allows writes under TMPDIR, not the home directory.
    return Path(os.environ.get("TMPDIR", "/tmp")) / "s2-papers"


class _HtmlMarkdown(HTMLParser):
    """Markdown of an arXiv (LaTeXML) HTML paper that keeps all of its content.

    Headings become '#' lines, math becomes its LaTeX source between $ or $$,
    data tables stay HTML tables (cells, colspan and rowspan kept), links keep
    their URL, and each figure image becomes a Markdown image of a file in
    figures_dir. The images the page references are collected in `images` as
    (file name, URL or inline SVG markup) for the caller to save. Only files
    under the paper's own address count; others (arXiv's /static/ icons) are
    page decoration. An SVG that holds HTML text in foreignObject elements (a
    boxed prompt or example) contributes that text instead of an image.
    """

    def __init__(self, base_url, figures_dir, images=None, svg_as_text=False):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.figures_dir = figures_dir
        self._svg_as_text = svg_as_text
        self._paper_prefix = base_url.rstrip("/")
        self.parts = {False: [], True: []}
        self.images = [] if images is None else images
        self._article = 0
        self._skip = 0
        self._math = 0
        self._figure = 0
        self._svg = None
        self._svg_depth = 0
        self._svg_ignored = 0
        self._tables = []
        self._links = []

    def _emit(self, text):
        self.parts[self._article > 0].append(text)

    def _image(self, source, suffix):
        name = f"fig{len(self.images) + 1:03d}{suffix}"
        self.images.append((name, source))
        shown = name if suffix in _RASTER_SUFFIXES else name + ".png"
        self._emit(f"\n\n![]({self.figures_dir / shown})\n\n")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self._svg is not None:
            self._svg.append(self.get_starttag_text() or "")
            self._svg_depth += tag == "svg"
            return
        if self._svg_ignored:
            self._svg_ignored += tag == "svg"
            return
        if self._skip or tag in _SKIP_TAGS:
            self._skip += tag in _SKIP_TAGS
            return
        if self._math:
            self._math += tag == "math"
            return
        classes = set((a.get("class") or "").split())
        if tag == "article":
            self._article += 1
        elif tag == "math":
            latex = a.get("alttext", "")
            self._emit(f"\n$$\n{latex}\n$$\n" if a.get("display") == "block" else f"${latex}$")
            self._math = 1
        elif tag == "svg":
            # SVG in a figure is figure content; elsewhere it is an icon (ORCID, logos).
            if self._svg_as_text:
                pass
            elif self._figure:
                self._svg, self._svg_depth = [self.get_starttag_text() or ""], 1
            else:
                self._svg_ignored = 1
        elif tag == "img":
            src = a.get("src") or ""
            if src.startswith("data:"):
                if self._figure:
                    self._image(src, ".png")
            else:
                self._paper_file(src)
        elif tag == "object" and a.get("data"):
            self._paper_file(a.get("data") or "")
        elif tag == "figure":
            self._figure += 1
            self._emit("\n\n")
        elif tag in _TABLE_TAGS:
            if tag == "table":
                self._tables.append(not (classes & _EQUATION_TABLE_CLASSES))
            if self._tables and self._tables[-1]:
                span = "".join(f' {k}="{escape(v)}"' for k, v in attrs if k in ("colspan", "rowspan") and v)
                self._emit(f"\n<{tag}{span}>" if tag in ("table", "tr") else f"<{tag}{span}>")
            elif tag == "tr":
                self._emit("\n")
        elif tag in _HEADING_TAGS:
            self._emit("\n\n" + "#" * _HEADING_TAGS[tag] + " ")
        elif tag == "li":
            self._emit("\n- ")
        elif tag == "a":
            href = a.get("href") or ""
            external = urlparse(href).scheme in ("http", "https", "mailto")
            self._links.append(href if external else None)
            if external:
                self._emit("[")
        elif tag in _BLOCK_TAGS:
            self._emit("\n")

    def _paper_file(self, ref):
        url = urljoin(self.base_url, ref)
        if url.startswith(self._paper_prefix):
            self._image(url, Path(urlparse(url).path).suffix.lower())

    def handle_startendtag(self, tag, attrs):
        if self._svg is not None:
            self._svg.append(self.get_starttag_text() or "")
            return
        self.handle_starttag(tag, attrs)
        if tag in ("svg", "math"):
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self._svg is not None:
            self._svg.append(f"</{tag}>")
            self._svg_depth -= tag == "svg"
            if self._svg_depth == 0:
                markup = "".join(self._svg)
                self._svg = None
                if "<foreignObject" in markup:
                    self._emit(self._svg_text(markup))
                else:
                    self._image(markup, ".svg")
            return
        if self._svg_ignored:
            self._svg_ignored -= tag == "svg"
            return
        if self._skip:
            self._skip -= tag in _SKIP_TAGS
            return
        if self._math:
            self._math -= tag == "math"
            return
        if tag == "article":
            self._article -= 1
        elif tag == "figure":
            self._figure -= 1
            self._emit("\n\n")
        elif tag in _TABLE_TAGS:
            if self._tables and self._tables[-1]:
                self._emit(f"</{tag}>" + ("\n" if tag == "table" else ""))
            if tag == "table" and self._tables:
                self._tables.pop()
        elif tag in _HEADING_TAGS:
            self._emit("\n")
        elif tag == "a" and self._links:
            href = self._links.pop()
            if href:
                self._emit(f"]({href})")
        elif tag in _BLOCK_TAGS or tag == "li":
            self._emit("\n")

    def _svg_text(self, markup):
        """The text of an SVG's foreignObject HTML, as Markdown; its images join this paper's images."""
        inner = _HtmlMarkdown(self.base_url, self.figures_dir, images=self.images, svg_as_text=True)
        inner._article = 1
        inner.feed(markup)
        inner.close()
        return "\n\n" + "".join(inner.parts[True]) + "\n\n"

    def handle_data(self, data):
        if self._svg is not None:
            self._svg.append(escape(data, quote=False))
        elif not self._skip and not self._math:
            self._emit(escape(data, quote=False) if self._tables and self._tables[-1] else data)

    def result(self):
        in_article = bool(self.parts[True])
        text = "".join(self.parts[in_article])
        lines = [
            line.strip() if line.lstrip().startswith(("#", "<", "$$", "!")) else " ".join(line.split())
            for line in text.splitlines()
        ]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def html_to_markdown(html, base_url, figures_dir):
    """(markdown, images) for an arXiv HTML paper; see _HtmlMarkdown."""
    parser = _HtmlMarkdown(base_url, figures_dir)
    parser.feed(html)
    parser.close()
    return parser.result(), parser.images


def svg_to_png(svg):
    """PNG bytes of SVG markup, rendered at SVG_SCALE on white."""
    import skia

    data = svg.encode() if isinstance(svg, str) else svg
    # SVG inlined in HTML may omit the namespace, which a standalone SVG requires.
    if b"xmlns=" not in data[: data.find(b">") + 1]:
        data = data.replace(b"<svg", b'<svg xmlns="http://www.w3.org/2000/svg"', 1)
    dom = skia.SVGDOM.MakeFromStream(skia.MemoryStream(data))
    if dom is None:
        raise ValueError("unreadable SVG")
    size = dom.containerSize()
    if size.width() <= 0 or size.height() <= 0:
        raise ValueError("SVG has no size")
    surface = skia.Surface(round(size.width() * SVG_SCALE), round(size.height() * SVG_SCALE))
    with surface as canvas:
        canvas.clear(skia.ColorWHITE)
        canvas.scale(SVG_SCALE, SVG_SCALE)
        dom.render(canvas)
    return bytes(surface.makeImageSnapshot().encodeToData())


def pdf_to_markdown(pdf_path, figures_dir):
    """Markdown of a PDF, with page-end markers and its figures and formulas as image files in figures_dir."""
    import pymupdf
    import pymupdf4llm

    figures_dir.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf_path) as doc:
        markdown = pymupdf4llm.to_markdown(
            doc,
            write_images=True,
            image_path=str(figures_dir),
            page_separators=True,
            use_ocr=False,
            header=False,
            footer=False,
        )
    if not isinstance(markdown, str):
        raise TypeError("the converter returned page chunks instead of Markdown")
    return markdown


async def _fetch_response(http, url):
    """The final response for url after retrying 429/5xx with backoff; None if no response arrived."""
    r = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            r = await http.get(url)
        except httpx.HTTPError:
            r = None
        if r is not None and r.status_code != 429 and r.status_code < 500:
            return r
        if attempt < FETCH_ATTEMPTS - 1:
            await asyncio.sleep(2**attempt)
    return r


async def _fetch(http, url):
    """GET a non-S2 URL politely: retries on 429/5xx with backoff, None on failure."""
    r = await _fetch_response(http, url)
    return r if r is not None and r.status_code == 200 else None


async def save_pdf(http, paper: Paper):
    """Path of the paper's saved PDF (arXiv first, then open access), or None when neither exists."""
    path = _cache_dir() / str(paper["paperId"]) / "paper.pdf"
    if path.exists():
        return path
    arxiv_id = (paper.get("externalIds") or {}).get("ArXiv")
    oa_url = (paper.get("openAccessPdf") or {}).get("url")
    for url in ([f"https://arxiv.org/pdf/{arxiv_id}"] if arxiv_id else []) + ([oa_url] if oa_url else []):
        r = await _fetch(http, url)
        if r is not None and r.content.startswith(b"%PDF"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            return path
    return None


async def _save_images(http, images, figures_dir):
    """Save every image of the page as a file the Read tool shows as an image; True when all were saved."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(IMAGE_CONNECTIONS)

    async def load(source):
        if source.lstrip().startswith("<svg"):
            return source.encode()
        if source.startswith("data:"):
            return base64.b64decode(source.split(",", 1)[1])
        async with semaphore:
            r = await _fetch(http, source)
        return r.content if r is not None else None

    async def save(name, source):
        content = await load(source)
        if content is None:
            return False
        if Path(name).suffix in _RASTER_SUFFIXES:
            (figures_dir / name).write_bytes(content)
            return True
        try:
            (figures_dir / f"{name}.png").write_bytes(await asyncio.to_thread(svg_to_png, content))
        except ValueError:
            return False
        return True

    return all(await asyncio.gather(*(save(name, source) for name, source in images)))


async def _arxiv_markdown(http, arxiv_id, figures_dir):
    """Markdown of the paper's arXiv HTML with its figures saved, or None when that HTML is missing or incomplete.

    HTML that LaTeXML marks with conversion errors, or whose images cannot all
    be saved, counts as incomplete.
    """
    r = await _fetch(http, f"https://arxiv.org/html/{arxiv_id}")
    if r is None or 'class="ltx_document' not in r.text or "ltx_ERROR" in r.text:
        return None
    markdown, images = html_to_markdown(r.text, str(r.url), figures_dir)
    return markdown if await _save_images(http, images, figures_dir) else None


async def save_text(http, paper: Paper, pdf_task):
    """Path of the paper as Markdown with its figures as image files, or None.

    The text comes from the arXiv HTML version when it is complete, else from
    the PDF that pdf_task saves.
    """
    paper_dir = _cache_dir() / str(paper["paperId"])
    path = paper_dir / "paper.md"
    if path.exists():
        return path
    figures_dir = paper_dir / "figures"
    arxiv_id = (paper.get("externalIds") or {}).get("ArXiv")
    markdown = await _arxiv_markdown(http, arxiv_id, figures_dir) if arxiv_id else None
    pdf = await pdf_task if markdown is None else None
    if markdown is None and pdf is not None:
        shutil.rmtree(figures_dir, ignore_errors=True)
        try:
            markdown = await asyncio.to_thread(pdf_to_markdown, pdf, figures_dir)
        except Exception as exc:
            print(f"error: {paper['paperId']}: the PDF could not be converted to text: {exc}", file=sys.stderr)
    if markdown is None:
        shutil.rmtree(figures_dir, ignore_errors=True)
        return None
    paper_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown)
    return path


async def _count(results, cap):
    count = 0
    async for _ in results:
        count += 1
        if count >= cap:
            break
    return count


async def read_paper(client, http, paper: Paper, year):
    # The PDF downloads while the text is prepared, which needs the PDF only when there is no arXiv HTML.
    pdf_task = asyncio.ensure_future(save_pdf(http, paper))
    try:
        text = await save_text(http, paper, pdf_task)
    finally:
        pdf = await pdf_task
    if pdf is None:
        print(
            f"error: {paper['paperId']}: no PDF found (no arXiv or open-access PDF); "
            f"try a web search for the title: {paper.get('title')!r}",
            file=sys.stderr,
        )
    in_range = None
    if year:
        results = await client.get_paper_citations(
            paper["paperId"], fields=["paperId"], limit=1000, publication_date_or_year=year.replace("-", ":")
        )
        # limit is the page size; pages continue until the endpoint's 9999-result window ends.
        in_range = await _count(results, 9999)
    return {
        "paperId": paper["paperId"],
        "title": paper.get("title"),
        "year": paper.get("year"),
        "pdfPath": str(pdf) if pdf else None,
        "textPath": str(text) if text else None,
        "citationCount": paper.get("citationCount"),
        "citationsInRange": in_range,
    }


def _with_note(result):
    """The read result with its reading note: the reminder when a copy was saved, else None."""
    return {**result, "note": READ_NOTE if result.get("pdfPath") or result.get("textPath") else None}


def _read_cache_path(paper_id, year):
    """Cache file of a read of paper_id (as given on the command line) with year."""
    key = hashlib.sha256(f"{paper_id}\n{year or ''}".encode()).hexdigest()
    return _cache_dir() / "reads" / f"{key}.json"


def _cached_read(paper_id, year):
    """The saved output of a read made within READ_CACHE_SECONDS whose files still exist, or None."""
    path = _read_cache_path(paper_id, year)
    try:
        saved = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return None
    result = saved.get("result") or {}
    if time.time() - saved.get("savedAt", 0) > READ_CACHE_SECONDS or "textPath" not in result:
        return None
    if not all(Path(result[key]).exists() for key in ("pdfPath", "textPath") if result[key]):
        return None
    return result


def _save_read(paper_id, year, result):
    path = _read_cache_path(paper_id, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"savedAt": time.time(), "result": result}))


def _http_client():
    return httpx.AsyncClient(headers=FETCH_HEADERS, timeout=FETCH_TIMEOUT, follow_redirects=True)


async def cmd_read(args):
    ids = read_ids(args.ids, sys.stdin)
    if not ids:
        print("error: no paper IDs provided", file=sys.stderr)
        sys.exit(0)
    pending = []
    for paper_id in ids:
        cached = _cached_read(paper_id, args.year)
        if cached is not None:
            output(_with_note(cached))
        else:
            pending.append(paper_id)
    if not pending:
        return
    client = make_client()
    async with _http_client() as http:
        for i in range(0, len(pending), 500):
            chunk = pending[i : i + 500]
            papers, not_found = await client.get_papers(chunk, fields=READ_FIELDS)
            if not_found:
                print(f"error: not found: {', '.join(not_found)}", file=sys.stderr)
            elif not_found is None:
                print(
                    f"error: status unknown (API returned {len(papers)} results for {len(chunk)} IDs, "
                    f"cannot tell which resolved): {', '.join(chunk)}",
                    file=sys.stderr,
                )
            # The batch answers in input order, so found IDs pair with papers when the counts agree;
            # otherwise results are output but not cached.
            found = [pid for pid in chunk if not_found is not None and pid not in not_found]
            if len(found) != len(papers):
                found = [None] * len(papers)
            for paper_id, paper in zip(found, papers, strict=True):
                try:
                    result = await read_paper(client, http, paper, args.year)
                except Exception as exc:
                    print(f"error: {paper.get('paperId')}: {_describe_error(exc)}", file=sys.stderr)
                    continue
                output(_with_note(result))
                if paper_id is not None and result["pdfPath"] is not None:
                    _save_read(paper_id, args.year, result)


async def cmd_fields(_args):
    print(FIELDS_HELP)


def main():
    # TLS verification uses the operating system's trust store, which holds
    # the root CAs of VPNs and proxies that re-sign HTTPS traffic.
    truststore.inject_into_ssl()

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
    p.add_argument("-n", "--limit", type=int, help="max results (default: all, up to 1000)")
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
        help="Save a paper as PDF and Markdown, to read in full",
        description=(
            "Save each paper twice, for reading cover to cover before reporting on it: the\n"
            "PDF, printed as pdfPath, which the Read tool renders page by page, and the full\n"
            "text as Markdown, printed as textPath, with figures as image files the Read tool\n"
            "shows as images. With -y, also count the papers that cite it in a year range."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines, one object per paper:\n"
            "          paperId, title, year, citationCount\n"
            "          pdfPath          the saved PDF, or null when the paper has no PDF\n"
            "          textPath         the paper's full text as Markdown, from arXiv HTML when\n"
            "                           it converts cleanly, else from the PDF; figures (and,\n"
            "                           from the PDF, formulas) are image files linked in the\n"
            "                           text; null when there is neither\n"
            "          citationsInRange citing papers in the -y range (null without -y; counted\n"
            "                           up to 9999)\n"
            "          note             reminder to read the paper cover to cover from either copy\n"
            "                           before reporting on it (null when neither was saved)\n"
            "reading: a paper counts as read once one copy has been read from the first page to\n"
            "        the last: pdfPath with the Read tool, or textPath with its figure images\n"
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
        "-n", "--limit", type=int, help="max citations per input paper (default: all, up to 9999)"
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
        "-n", "--limit", type=int, help="max references per input paper (default: all, up to 9999)"
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
    p.add_argument("-n", "--limit", type=int, help="max recommendations (default: all, up to 500)")
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
    p.add_argument("-n", "--limit", type=int, help="max results (default: all, up to 9999)")

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
    p.add_argument("-n", "--limit", type=int, help="max papers per author (default: all, up to 9999)")

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
        tip = " (run 's2 fields' for valid field names)" if "field" in str(e).lower() else ""
        print(f"error: {e}{tip}", file=sys.stderr)
    except ObjectNotFoundException as e:
        print(f"error: {e}", file=sys.stderr)
    except PermissionError as e:
        print(f"error: forbidden ({e}) — check your S2_API_KEY", file=sys.stderr)
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
