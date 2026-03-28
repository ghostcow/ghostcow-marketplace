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
#     "socksio==1.0.0",
#     "tenacity==9.1.4",
#     "typing_extensions==4.15.0",
# ]
# ///

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from filelock import AsyncFileLock
from semanticscholar import AsyncSemanticScholar
from semanticscholar.ApiRequester import ApiRequester
from semanticscholar.SemanticScholarException import (
    BadQueryParametersException,
    ObjectNotFoundException,
    ServerErrorException,
)
from tenacity import (
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
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
  contexts          arr   text snippets showing where the citation appears
  intents           arr   why the paper was cited (e.g. background, method)
  isInfluential     bool  whether the citation had significant impact

publication types (for -t on search)
  JournalArticle, Conference, Review, CaseReport, ClinicalTrial,
  Dataset, Editorial, LettersAndComments, MetaAnalysis, News,
  Study, Book, BookSection"""

FIELDS_HINT = "fields:  run 's2 fields' for all available field names"

RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=30)
RETRY_EXCEPTIONS = retry_if_exception_type((ConnectionRefusedError, ServerErrorException))
_RATE_DIR = os.environ.get("TMPDIR", "/tmp")
_RATE_LOCK = os.path.join(_RATE_DIR, "s2_rate.lock")
_RATE_TS = os.path.join(_RATE_DIR, "s2_rate.ts")


class S2Requester(ApiRequester):
    def __init__(self, timeout, retry):
        super().__init__(timeout, retry)

    async def get_data_async(self, url, parameters, headers, payload=None):
        # Cross-process rate limit: file lock serializes all s2 invocations,
        # mtime of the timestamp file tracks when the last request was made.
        async with AsyncFileLock(_RATE_LOCK):
            try:
                last = os.path.getmtime(_RATE_TS)
            except FileNotFoundError:
                last = 0.0
            elapsed = time.time() - last
            if elapsed < 1.1:
                await asyncio.sleep(1.1 - elapsed)
            Path(_RATE_TS).touch()
        if self.retry:
            return await self._get_data_async.retry_with(
                retry=RETRY_EXCEPTIONS, wait=RETRY_WAIT, stop=stop_after_attempt(4)
            )(self, url, parameters, headers, payload)
        return await self._get_data_async.retry_with(stop=stop_after_attempt(1))(
            self, url, parameters, headers, payload
        )


class S2Client(AsyncSemanticScholar):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._requester = S2Requester(self._timeout, self._retry)


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
            pass  # API key is optional; unauthenticated requests use lower rate limits.
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
        if not_found:
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
            "output: every command prints one JSON object per line\n"
            "piping: ID-accepting commands read IDs from stdin when -i is not used —\n"
            "        each line is a JSON object with a paperId or authorId field, or a raw ID\n"
            '        e.g. s2 search "transformers" | s2 get'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "search",
        help="Search papers by keyword",
        description="Search Semantic Scholar by keyword.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"output: JSON lines with requested fields\n{FIELDS_HINT}",
    )
    p.add_argument("query", help="search query string")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max results, capped at 100 (default: 10)")
    p.add_argument("-y", "--year", help="year or range, e.g. 2020 or 2018-2020")
    p.add_argument("-d", "--publication-date", help="date range, e.g. 2020-06-01:2021-01-31 or 2020-01:2021-06")
    p.add_argument("-t", "--publication-types", help="comma-separated types, e.g. JournalArticle,Conference,Review")
    p.add_argument("--open-access", action="store_true", help="only papers with open-access PDFs")
    p.add_argument("--venue", help="comma-separated venue names")
    p.add_argument("--fields-of-study", help="comma-separated, e.g. Computer Science,Medicine")
    p.add_argument("--min-citations", type=int, help="minimum citation count")
    p.add_argument("--match-title", action="store_true", help="return single paper best matching the query as title")

    p = sub.add_parser(
        "get",
        help="Fetch paper details by ID(s)",
        description="Fetch details for one or more papers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"output: JSON lines, one object per paper\nstdin:  reads IDs from piped input when -i is omitted\n{FIELDS_HINT}",
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="paper IDs (S2, DOI:..., ArXiv:..., CorpusId:...)")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {detail_default})")

    p = sub.add_parser(
        "citations",
        help="Get papers that cite the given paper(s)",
        description="Fetch papers that cite the given paper(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines with requested fields + sourcePaperId\n"
            "        (sourcePaperId = which input paper was queried)\n"
            "stdin:  reads IDs from piped input when -i is omitted\n"
            f"limit:  applied per input paper, not globally\n{FIELDS_HINT}"
        ),
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="paper IDs to get citations for")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max citations per input paper (default: 10)")

    p = sub.add_parser(
        "references",
        help="Get papers cited by the given paper(s)",
        description="Fetch papers cited by (referenced by) the given paper(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines with requested fields + sourcePaperId\n"
            "        (sourcePaperId = which input paper was queried)\n"
            "stdin:  reads IDs from piped input when -i is omitted\n"
            f"limit:  applied per input paper, not globally\n{FIELDS_HINT}"
        ),
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="paper IDs to get references for")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max references per input paper (default: 10)")

    p = sub.add_parser(
        "recommend",
        help="Recommend papers from seed paper(s)",
        description=(
            "Get paper recommendations.\n"
            "One seed uses single-paper recommendations;\n"
            "multiple seeds or --negative-ids uses list-based recommendations."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"output: JSON lines with requested fields\nstdin:  reads IDs from piped input when -i is omitted\n{FIELDS_HINT}",
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="seed paper IDs")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max recommendations, capped at 500 (default: 10)")
    p.add_argument(
        "-x",
        "--negative-ids",
        nargs="+",
        metavar="ID",
        help="paper IDs to use as negative examples (forces list-based mode)",
    )
    p.add_argument(
        "--pool",
        default="recent",
        choices=["recent", "all-cs"],
        help="recommendation pool (default: recent). Only available for single-seed; the list-based endpoint does not support pool selection",
    )

    p = sub.add_parser(
        "search-author",
        help="Search authors by name",
        description="Search Semantic Scholar for authors by name.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="output: JSON lines with author fields",
    )
    p.add_argument("query", help="author name search string")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {author_scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max results (default: 10)")

    p = sub.add_parser(
        "author-papers",
        help="Get papers by author ID(s)",
        description="Fetch papers written by the given author(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "output: JSON lines with requested paper fields + sourceAuthorId\n"
            "stdin:  reads author IDs from piped input when -i is omitted\n"
            f"{FIELDS_HINT}"
        ),
    )
    p.add_argument("-i", "--ids", nargs="+", metavar="ID", help="author IDs")
    p.add_argument("-f", "--fields", help=f"comma-separated fields (default: {scan_default})")
    p.add_argument("-n", "--limit", type=int, default=10, help="max papers per author (default: 10)")

    sub.add_parser(
        "fields",
        help="List all available field names",
        description="Show all paper, author, and citation/reference fields accepted by -f.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    args = parser.parse_args()

    handlers = {
        "search": cmd_search,
        "get": cmd_get,
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
