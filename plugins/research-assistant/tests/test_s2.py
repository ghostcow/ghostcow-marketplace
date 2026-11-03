"""Tests for scripts/s2.py."""

import asyncio
import io
import json
import subprocess
import sys
import textwrap
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from conftest import async_iter, make_args, make_citation, make_paper
from s2 import (
    AUTHOR_SCAN_FIELDS,
    DETAIL_FIELDS,
    FIELDS_HELP,
    RETRY_ATTEMPTS,
    SCAN_FIELDS,
    RateLimitedError,
    S2Client,
    S2Requester,
    _describe_error,
    _fetch,
    _parse_retry_after,
    cmd_author_papers,
    cmd_citations,
    cmd_fields,
    cmd_get,
    cmd_read,
    cmd_recommend,
    cmd_references,
    cmd_search,
    cmd_search_author,
    fetch_full_text,
    find_figures,
    html_to_text,
    mark_captions,
    main,
    make_client,
    output,
    pdf_to_text,
    read_ids,
)
from semanticscholar.SemanticScholarException import (
    BadQueryParametersException,
    InternalServerErrorException,
    ObjectNotFoundException,
    ServerErrorException,
)
from tenacity import RetryError

# ---------------------------------------------------------------------------
# read_ids
# ---------------------------------------------------------------------------


class TestReadIds:
    def test_empty_args_and_tty_stdin(self):
        stdin = MagicMock()
        stdin.isatty.return_value = True
        assert read_ids([], stdin) == []

    def test_empty_args_and_none_stdin(self):
        assert read_ids([], None) == []

    def test_args_only(self):
        assert read_ids(["id1", "id2"], None) == ["id1", "id2"]

    def test_stdin_json_with_paper_id(self):
        lines = ['{"paperId": "abc123", "title": "Test"}\n']
        stdin = io.StringIO("".join(lines))
        assert read_ids([], stdin) == ["abc123"]

    def test_stdin_raw_ids(self):
        stdin = io.StringIO("DOI:10.1234/test\nArXiv:2301.00001\n")
        assert read_ids([], stdin) == ["DOI:10.1234/test", "ArXiv:2301.00001"]

    def test_stdin_blank_lines_skipped(self):
        stdin = io.StringIO("id1\n\n\nid2\n")
        assert read_ids([], stdin) == ["id1", "id2"]

    def test_stdin_json_without_paper_id_treated_as_raw(self):
        stdin = io.StringIO('{"title": "no id"}\n')
        result = read_ids([], stdin)
        assert result == ['{"title": "no id"}']

    def test_args_provided_stdin_not_read(self):
        stdin = io.StringIO("id_from_stdin\n")
        assert read_ids(["id_from_args"], stdin) == ["id_from_args"]

    def test_none_args_treated_as_empty(self):
        assert read_ids(None, None) == []


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------


class TestOutput:
    def test_prints_json_line(self, capsys):
        data = {"paperId": "abc", "title": "Test Paper"}
        output(data)
        captured = capsys.readouterr()
        assert json.loads(captured.out) == data

    def test_prints_nested_data(self, capsys):
        data = {"authors": [{"name": "Alice"}, {"name": "Bob"}]}
        output(data)
        assert json.loads(capsys.readouterr().out) == data


# ---------------------------------------------------------------------------
# make_client
# ---------------------------------------------------------------------------


class TestMakeClient:
    @patch.dict("os.environ", {"S2_API_KEY": "test-key"}, clear=False)
    def test_with_api_key(self):
        client = make_client()
        assert client.auth_header == {"x-api-key": "test-key"}

    @patch.dict("os.environ", {}, clear=True)
    def test_without_api_key(self, capsys):
        with patch("s2.Path.read_text", side_effect=FileNotFoundError):
            client = make_client()
        assert client.auth_header == {}
        assert "/research-assistant:setup" in capsys.readouterr().err

    @patch.dict("os.environ", {"S2_API_KEY": "test-key"}, clear=False)
    def test_with_api_key_no_warning(self, capsys):
        make_client()
        assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# cmd_search
# ---------------------------------------------------------------------------


class TestCmdSearch:
    @pytest.mark.asyncio
    async def test_basic_search(self, mock_client, capsys):
        papers = [make_paper({"paperId": "p1"}), make_paper({"paperId": "p2"})]
        mock_client.search_paper.return_value = async_iter(papers)

        await cmd_search(make_args(query="transformers", limit=10))

        mock_client.search_paper.assert_called_once_with("transformers", fields=SCAN_FIELDS, limit=10)
        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["paperId"] == "p1"

    @pytest.mark.asyncio
    async def test_custom_fields(self, mock_client):
        mock_client.search_paper.return_value = async_iter([make_paper({"title": "X"})])

        await cmd_search(make_args(query="test", fields="title,year", limit=5))

        mock_client.search_paper.assert_called_once_with("test", fields=["title", "year"], limit=5)

    @pytest.mark.asyncio
    async def test_limit_caps_at_100(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test", limit=200))

        mock_client.search_paper.assert_called_once_with("test", fields=SCAN_FIELDS, limit=100)

    @pytest.mark.asyncio
    async def test_limit_stops_iteration(self, mock_client, capsys):
        papers = [make_paper({"paperId": f"p{i}"}) for i in range(10)]
        mock_client.search_paper.return_value = async_iter(papers)

        await cmd_search(make_args(query="test", limit=3))

        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 3

    @pytest.mark.asyncio
    async def test_year_filter_forwarded(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test", limit=10, year="2020-2023"))

        mock_client.search_paper.assert_called_once_with("test", fields=SCAN_FIELDS, limit=10, year="2020-2023")

    @pytest.mark.asyncio
    async def test_year_none_not_forwarded(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test", limit=10, year=None))

        mock_client.search_paper.assert_called_once_with("test", fields=SCAN_FIELDS, limit=10)


# ---------------------------------------------------------------------------
# cmd_get
# ---------------------------------------------------------------------------


class TestCmdGet:
    @pytest.mark.asyncio
    async def test_basic_get(self, mock_client, capsys):
        papers = [make_paper({"paperId": "p1", "title": "Paper 1"})]
        mock_client.get_papers.return_value = (papers, [])

        await cmd_get(make_args(ids=["p1"]))

        mock_client.get_papers.assert_called_once_with(["p1"], fields=DETAIL_FIELDS, return_not_found=True)
        out = json.loads(capsys.readouterr().out.strip())
        assert out["paperId"] == "p1"

    @pytest.mark.asyncio
    async def test_not_found_warning(self, mock_client, capsys):
        papers = [make_paper({"paperId": "p1"})]
        mock_client.get_papers.return_value = (papers, ["bad_id_1", "bad_id_2"])

        await cmd_get(make_args(ids=["p1", "bad_id_1", "bad_id_2"]))

        stderr = capsys.readouterr().err
        assert "error: not found: bad_id_1, bad_id_2" in stderr

    @pytest.mark.asyncio
    async def test_unknown_status_reported(self, mock_client, capsys):
        mock_client.get_papers.return_value = ([make_paper({"paperId": "p1"})], None)

        await cmd_get(make_args(ids=["DOI:10.1/x", "PMID:123"]))

        captured = capsys.readouterr()
        assert json.loads(captured.out.strip())["paperId"] == "p1"
        assert "error: status unknown" in captured.err
        assert "DOI:10.1/x, PMID:123" in captured.err
        assert "not found" not in captured.err

    @pytest.mark.asyncio
    async def test_no_warning_when_all_found(self, mock_client, capsys):
        mock_client.get_papers.return_value = ([make_paper({"paperId": "p1"})], [])

        await cmd_get(make_args(ids=["p1"]))

        assert "error" not in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_no_ids_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            await cmd_get(make_args(ids=None))
        assert exc_info.value.code == 0

    @pytest.mark.asyncio
    async def test_batching_over_500(self, mock_client, capsys):
        batch1_papers = [make_paper({"paperId": f"id{i}"}) for i in range(500)]
        batch2_papers = [make_paper({"paperId": f"id{i}"}) for i in range(500, 750)]
        mock_client.get_papers.side_effect = [
            (batch1_papers, []),
            (batch2_papers, []),
        ]

        ids = [f"id{i}" for i in range(750)]
        await cmd_get(make_args(ids=ids))

        assert mock_client.get_papers.call_count == 2
        first_call_ids = mock_client.get_papers.call_args_list[0][0][0]
        second_call_ids = mock_client.get_papers.call_args_list[1][0][0]
        assert len(first_call_ids) == 500
        assert len(second_call_ids) == 250
        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 750

    @pytest.mark.asyncio
    async def test_custom_fields(self, mock_client):
        mock_client.get_papers.return_value = ([make_paper({"title": "X"})], [])

        await cmd_get(make_args(ids=["p1"], fields="title,abstract"))

        mock_client.get_papers.assert_called_once_with(["p1"], fields=["title", "abstract"], return_not_found=True)


# ---------------------------------------------------------------------------
# cmd_citations
# ---------------------------------------------------------------------------


class TestCmdCitations:
    @pytest.mark.asyncio
    async def test_basic_citations(self, mock_client, capsys):
        citation = make_citation({"paperId": "c1", "title": "Citing"})
        mock_client.get_paper_citations.return_value = async_iter([citation])

        await cmd_citations(make_args(ids=["p1"], limit=10))

        out = json.loads(capsys.readouterr().out.strip())
        assert out["sourcePaperId"] == "p1"
        assert out["paperId"] == "c1"

    @pytest.mark.asyncio
    async def test_skips_null_papers(self, mock_client, capsys):
        citations = [
            make_citation({"paperId": "c1"}),
            make_citation({"paperId": "c2"}, has_paper=False),
            make_citation({"paperId": "c3"}),
        ]
        mock_client.get_paper_citations.return_value = async_iter(citations)

        await cmd_citations(make_args(ids=["p1"], limit=10))

        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 2
        paper_ids = [json.loads(line)["paperId"] for line in lines]
        assert paper_ids == ["c1", "c3"]

    @pytest.mark.asyncio
    async def test_limit_per_paper(self, mock_client, capsys):
        citations = [make_citation({"paperId": f"c{i}"}) for i in range(10)]
        mock_client.get_paper_citations.return_value = async_iter(citations)

        await cmd_citations(make_args(ids=["p1"], limit=3))

        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 3

    @pytest.mark.asyncio
    async def test_limit_caps_at_1000(self, mock_client):
        mock_client.get_paper_citations.return_value = async_iter([])

        await cmd_citations(make_args(ids=["p1"], limit=2000))

        mock_client.get_paper_citations.assert_called_once_with("p1", fields=SCAN_FIELDS, limit=1000)

    @pytest.mark.asyncio
    async def test_no_ids_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            await cmd_citations(make_args(ids=None, limit=10))
        assert exc_info.value.code == 0

    @pytest.mark.asyncio
    async def test_multiple_input_papers(self, mock_client, capsys):
        mock_client.get_paper_citations.side_effect = [
            async_iter([make_citation({"paperId": "c1"})]),
            async_iter([make_citation({"paperId": "c2"})]),
        ]

        await cmd_citations(make_args(ids=["p1", "p2"], limit=10))

        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["sourcePaperId"] == "p1"
        assert json.loads(lines[1])["sourcePaperId"] == "p2"

    @pytest.mark.asyncio
    async def test_year_forwarded_as_date_filter(self, mock_client):
        mock_client.get_paper_citations.return_value = async_iter([])

        await cmd_citations(make_args(ids=["p1"], limit=10, year="2026"))

        mock_client.get_paper_citations.assert_called_once_with(
            "p1", fields=SCAN_FIELDS, limit=10, publication_date_or_year="2026"
        )

    @pytest.mark.asyncio
    async def test_year_range_uses_colon_separator(self, mock_client):
        mock_client.get_paper_citations.return_value = async_iter([])

        await cmd_citations(make_args(ids=["p1"], limit=10, year="2018-2020"))

        mock_client.get_paper_citations.assert_called_once_with(
            "p1", fields=SCAN_FIELDS, limit=10, publication_date_or_year="2018:2020"
        )


class TestS2ClientCitations:
    @pytest.mark.asyncio
    async def test_date_filter_sent_on_every_page(self):
        client = S2Client(api_key=None)
        pages = [
            {"offset": 0, "next": 2, "data": [{"citingPaper": {"paperId": "c1"}}, {"citingPaper": {"paperId": "c2"}}]},
            {"offset": 2, "data": [{"citingPaper": {"paperId": "c3"}}]},
        ]
        client._requester.get_data_async = AsyncMock(side_effect=pages)

        results = await client.get_paper_citations(
            "p1", fields=["title"], limit=2, publication_date_or_year="2026"
        )
        ids = [item.paper.paperId async for item in results]

        assert ids == ["c1", "c2", "c3"]
        calls = client._requester.get_data_async.call_args_list
        assert len(calls) == 2
        for call in calls:
            url, params = call.args[0], call.args[1]
            assert url.endswith("/graph/v1/paper/p1/citations")
            assert "publicationDateOrYear=2026" in params

    @pytest.mark.asyncio
    async def test_no_filter_omits_parameter(self):
        client = S2Client(api_key=None)
        client._requester.get_data_async = AsyncMock(return_value={"offset": 0, "data": []})

        await client.get_paper_citations("p1", fields=["title"], limit=5)

        params = client._requester.get_data_async.call_args.args[1]
        assert "publicationDateOrYear" not in params


class TestS2ClientGetPapers:
    @pytest.mark.asyncio
    async def test_prefixed_ids_found_by_position(self):
        # The response has no externalIds, so ID matching cannot confirm these.
        client = S2Client(api_key=None)
        ids = ["DOI:10.1/x", "PMID:123", "URL:https://arxiv.org/abs/1706.03762", "CorpusId:42"]
        client._requester.get_data_async = AsyncMock(return_value=[{"paperId": f"p{i}"} for i in range(4)])

        papers, not_found = await client.get_papers(ids, fields=["title"], return_not_found=True)

        assert [p.paperId for p in papers] == ["p0", "p1", "p2", "p3"]
        assert not_found == []

    @pytest.mark.asyncio
    async def test_null_entries_are_not_found(self):
        client = S2Client(api_key=None)
        client._requester.get_data_async = AsyncMock(return_value=[{"paperId": "p0"}, None, None])

        papers, not_found = await client.get_papers(["DOI:a", "DOI:b", "ArXiv:c"], fields=["title"], return_not_found=True)

        assert [p.paperId for p in papers] == ["p0"]
        assert not_found == ["DOI:b", "ArXiv:c"]

    @pytest.mark.asyncio
    async def test_length_mismatch_gives_unknown(self):
        client = S2Client(api_key=None)
        client._requester.get_data_async = AsyncMock(return_value=[{"paperId": "p0"}])

        papers, not_found = await client.get_papers(["DOI:a", "DOI:b"], fields=["title"], return_not_found=True)

        assert [p.paperId for p in papers] == ["p0"]
        assert not_found is None

    @pytest.mark.asyncio
    async def test_batch_request_shape(self):
        client = S2Client(api_key=None)
        client._requester.get_data_async = AsyncMock(return_value=[{"paperId": "p0"}])

        papers = await client.get_papers(["p0"], fields=["title", "year"])

        url, params, _headers, payload = client._requester.get_data_async.call_args.args
        assert url.endswith("/graph/v1/paper/batch")
        assert params == "&fields=title,year"
        assert payload == {"ids": ["p0"]}
        assert [p.paperId for p in papers] == ["p0"]


# ---------------------------------------------------------------------------
# cmd_references
# ---------------------------------------------------------------------------


class TestCmdReferences:
    @pytest.mark.asyncio
    async def test_basic_references(self, mock_client, capsys):
        ref = make_citation({"paperId": "r1", "title": "Referenced"})
        mock_client.get_paper_references.return_value = async_iter([ref])

        await cmd_references(make_args(ids=["p1"], limit=10))

        out = json.loads(capsys.readouterr().out.strip())
        assert out["sourcePaperId"] == "p1"
        assert out["paperId"] == "r1"

    @pytest.mark.asyncio
    async def test_skips_null_papers(self, mock_client, capsys):
        refs = [
            make_citation({"paperId": "r1"}),
            make_citation({"paperId": "r2"}, has_paper=False),
        ]
        mock_client.get_paper_references.return_value = async_iter(refs)

        await cmd_references(make_args(ids=["p1"], limit=10))

        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_limit_caps_at_1000(self, mock_client):
        mock_client.get_paper_references.return_value = async_iter([])

        await cmd_references(make_args(ids=["p1"], limit=2000))

        mock_client.get_paper_references.assert_called_once_with("p1", fields=SCAN_FIELDS, limit=1000)

    @pytest.mark.asyncio
    async def test_no_ids_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            await cmd_references(make_args(ids=None, limit=10))
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# cmd_recommend
# ---------------------------------------------------------------------------


class TestCmdRecommend:
    @pytest.mark.asyncio
    async def test_single_seed(self, mock_client, capsys):
        mock_client.get_recommended_papers.return_value = [make_paper({"paperId": "rec1"})]

        await cmd_recommend(make_args(ids=["seed1"], limit=5))

        mock_client.get_recommended_papers.assert_called_once_with(
            "seed1", fields=SCAN_FIELDS, limit=5, pool_from="recent"
        )
        out = json.loads(capsys.readouterr().out.strip())
        assert out["paperId"] == "rec1"

    @pytest.mark.asyncio
    async def test_multiple_seeds(self, mock_client):
        mock_client.get_recommended_papers_from_lists.return_value = [make_paper({"paperId": "rec1"})]

        await cmd_recommend(make_args(ids=["s1", "s2"], limit=5))

        mock_client.get_recommended_papers_from_lists.assert_called_once_with(
            ["s1", "s2"], fields=SCAN_FIELDS, limit=5, negative_paper_ids=None
        )

    @pytest.mark.asyncio
    async def test_limit_caps_at_500(self, mock_client):
        mock_client.get_recommended_papers.return_value = []

        await cmd_recommend(make_args(ids=["seed1"], limit=1000))

        mock_client.get_recommended_papers.assert_called_once_with(
            "seed1", fields=SCAN_FIELDS, limit=500, pool_from="recent"
        )

    @pytest.mark.asyncio
    async def test_no_ids_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            await cmd_recommend(make_args(ids=None, limit=10))
        assert exc_info.value.code == 0

    @pytest.mark.asyncio
    async def test_empty_recent_pool_warns_with_pool_hint(self, mock_client, capsys):
        mock_client.get_recommended_papers.return_value = []

        await cmd_recommend(make_args(ids=["ArXiv:1706.03762"], limit=5))

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "no recommendations returned for ArXiv:1706.03762 from the recent pool" in captured.err
        assert "--pool all-cs" in captured.err

    @pytest.mark.asyncio
    async def test_empty_all_cs_pool_warns_without_pool_hint(self, mock_client, capsys):
        mock_client.get_recommended_papers.return_value = []

        await cmd_recommend(make_args(ids=["seed1"], limit=5, pool="all-cs"))

        err = capsys.readouterr().err
        assert "no recommendations returned for seed1; try different seeds" in err
        assert "--pool all-cs" not in err

    @pytest.mark.asyncio
    async def test_empty_list_based_warns_with_all_seeds(self, mock_client, capsys):
        mock_client.get_recommended_papers_from_lists.return_value = []

        await cmd_recommend(make_args(ids=["s1", "s2"], limit=5))

        err = capsys.readouterr().err
        assert "no recommendations returned for s1, s2; try different seeds" in err
        assert "pool" not in err

    @pytest.mark.asyncio
    async def test_nonempty_result_prints_no_warning(self, mock_client, capsys):
        mock_client.get_recommended_papers.return_value = [make_paper({"paperId": "rec1"})]

        await cmd_recommend(make_args(ids=["seed1"], limit=5))

        assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# cmd_fields
# ---------------------------------------------------------------------------


class TestCmdFields:
    @pytest.mark.asyncio
    async def test_prints_fields_help(self, capsys):
        await cmd_fields(make_args())
        assert capsys.readouterr().out.strip() == FIELDS_HELP


# ---------------------------------------------------------------------------
# S2Requester rate limiting
# ---------------------------------------------------------------------------


def _response(status, body=None, headers=None):
    """Build an httpx.Response as the S2 API would return it."""
    return httpx.Response(
        status, json={} if body is None else body, headers=headers, request=httpx.Request("GET", "http://test")
    )


@pytest.fixture
def http():
    """Patch httpx.AsyncClient.request; set return_value or side_effect to script the server."""
    with patch("s2.httpx.AsyncClient.request", new_callable=AsyncMock) as mock:
        mock.return_value = _response(200, {"data": "ok"})
        yield mock


@pytest.fixture
def unthrottled():
    """Patch out the file lock and timestamp file; yields the AsyncFileLock and touch mocks."""
    with (
        patch("s2.AsyncFileLock", return_value=AsyncMock()) as lock,
        patch("s2.os.path.getmtime", return_value=0.0),
        patch("s2.Path.touch") as touch,
    ):
        yield SimpleNamespace(lock=lock, touch=touch)


@pytest.fixture
def mock_sleep():
    """Patch asyncio.sleep, which both the throttle and the retry backoff call."""
    with patch("s2.asyncio.sleep", new_callable=AsyncMock) as mock:
        yield mock


class TestS2Requester:
    @pytest.mark.asyncio
    async def test_throttles_requests(self, http, mock_sleep):
        with (
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=time.time() - 0.3),
            patch("s2.Path.touch"),
        ):
            await S2Requester(timeout=10, retry=False).get_data_async("http://test", "", {})
        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        assert 0.0 < delay <= 1.1

    @pytest.mark.asyncio
    async def test_no_sleep_when_enough_time_passed(self, http, mock_sleep):
        with (
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=time.time() - 2.0),
            patch("s2.Path.touch"),
        ):
            await S2Requester(timeout=10, retry=False).get_data_async("http://test", "", {})
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_timestamp_marked_after_response(self, http, unthrottled):
        """The rate timestamp records when the response arrived, not when the request left."""
        order = []
        http.side_effect = lambda *a, **kw: order.append("request") or _response(200)
        unthrottled.touch.side_effect = lambda: order.append("touch")
        await S2Requester(timeout=10, retry=False).get_data_async("http://test", "", {})
        assert order == ["request", "touch"]

    @pytest.mark.asyncio
    async def test_timestamp_marked_when_request_fails(self, http, unthrottled):
        http.side_effect = httpx.ConnectTimeout("timed out")
        with pytest.raises(httpx.ConnectTimeout):
            await S2Requester(timeout=10, retry=True).get_data_async("http://test", "", {})
        unthrottled.touch.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_key_added_when_headers_missing(self, http, unthrottled):
        """Paginated SDK calls pass headers=None; the requester still sends the key."""
        requester = S2Requester(timeout=10, retry=False, auth_header={"x-api-key": "k"})
        await requester.get_data_async("http://test", "", None)
        assert http.call_args.kwargs["headers"] == {"x-api-key": "k"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("call", "body"),
        [
            (lambda c: c.get_paper_citations("p1", limit=5), {"data": []}),
            (lambda c: c.get_paper_references("p1", limit=5), {"data": []}),
            (lambda c: c.get_author_papers("a1", limit=5), {"data": []}),
            (lambda c: c.search_paper("q", limit=5), {"data": []}),
            (lambda c: c.get_papers(["p1"]), []),
            (lambda c: c.get_recommended_papers("p1"), {"recommendedPapers": []}),
        ],
        ids=["citations", "references", "author-papers", "search", "batch", "recommend"],
    )
    async def test_client_sends_api_key_on_every_endpoint(self, http, unthrottled, call, body):
        http.return_value = _response(200, body)
        await call(S2Client(api_key="k"))
        assert http.call_args.kwargs["headers"]["x-api-key"] == "k"

    @pytest.mark.asyncio
    async def test_rate_limited_retries_go_through_throttle(self, http, unthrottled, mock_sleep):
        http.side_effect = [_response(429), _response(429), _response(200, {"data": "ok"})]
        result = await S2Requester(timeout=10, retry=True).get_data_async("http://test", "", {})
        assert result == {"data": "ok"}
        assert unthrottled.lock.call_count == 3
        assert unthrottled.touch.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_after_header_sets_wait(self, http, unthrottled, mock_sleep):
        http.side_effect = [_response(429, headers={"Retry-After": "7"}), _response(200)]
        await S2Requester(timeout=10, retry=True).get_data_async("http://test", "", {})
        mock_sleep.assert_called_once_with(7.0)

    @pytest.mark.asyncio
    async def test_backoff_without_retry_after_has_jitter(self, http, unthrottled, mock_sleep):
        http.side_effect = [_response(429), _response(200)]
        await S2Requester(timeout=10, retry=True).get_data_async("http://test", "", {})
        delay = mock_sleep.call_args[0][0]
        assert 1.0 <= delay <= 2.0

    @pytest.mark.asyncio
    async def test_rate_limited_exhausted(self, http, unthrottled, mock_sleep):
        http.return_value = _response(429)
        with pytest.raises(RetryError) as exc_info:
            await S2Requester(timeout=10, retry=True).get_data_async("http://test", "", {})
        assert isinstance(exc_info.value.last_attempt.exception(), RateLimitedError)
        assert http.await_count == RETRY_ATTEMPTS

    @pytest.mark.asyncio
    async def test_retry_false_makes_one_attempt(self, http, unthrottled, mock_sleep):
        http.return_value = _response(429)
        with pytest.raises(RetryError):
            await S2Requester(timeout=10, retry=False).get_data_async("http://test", "", {})
        assert http.await_count == 1

    @pytest.mark.asyncio
    async def test_server_error_retried(self, http, unthrottled, mock_sleep):
        http.side_effect = [_response(500, {"message": "boom"}), _response(200, {"data": "ok"})]
        result = await S2Requester(timeout=10, retry=True).get_data_async("http://test", "", {})
        assert result == {"data": "ok"}
        assert http.await_count == 2

    @pytest.mark.asyncio
    async def test_server_error_exhausted(self, http, unthrottled, mock_sleep):
        http.return_value = _response(503)
        with pytest.raises(RetryError) as exc_info:
            await S2Requester(timeout=10, retry=True).get_data_async("http://test", "", {})
        assert isinstance(exc_info.value.last_attempt.exception(), ServerErrorException)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "exc_type"),
        [(400, BadQueryParametersException), (403, PermissionError), (404, ObjectNotFoundException)],
    )
    async def test_client_errors_not_retried(self, http, unthrottled, status, exc_type):
        http.return_value = _response(status, {"error": "bad"})
        with pytest.raises(exc_type):
            await S2Requester(timeout=10, retry=True).get_data_async("http://test", "", {})
        assert http.await_count == 1

    @pytest.mark.asyncio
    async def test_error_only_body_returns_empty(self, http, unthrottled):
        http.return_value = _response(200, {"error": "no match"})
        assert await S2Requester(timeout=10, retry=False).get_data_async("http://test", "", {}) == {}

    @pytest.mark.asyncio
    async def test_payload_sent_as_post(self, http, unthrottled):
        await S2Requester(timeout=10, retry=False).get_data_async("http://test", "&fields=title", {}, {"ids": ["p1"]})
        args, kwargs = http.call_args
        assert args[0] == "POST"
        assert kwargs["params"] == "fields=title"
        assert kwargs["json"] == {"ids": ["p1"]}

    @pytest.mark.asyncio
    async def test_concurrent_requests_are_serialized(self, tmp_path, http):
        """asyncio.gather through the real file lock: each request starts _RATE_INTERVAL after the previous response."""
        spans = []

        async def slow_server(*a, **kw):
            start = time.time()
            await asyncio.sleep(0.05)
            spans.append((start, time.time()))
            return _response(200)

        http.side_effect = slow_server
        requester = S2Requester(timeout=10, retry=False)
        with (
            patch("s2._RATE_LOCK", str(tmp_path / "s2_rate.lock")),
            patch("s2._RATE_TS", str(tmp_path / "s2_rate.ts")),
            patch("s2._RATE_INTERVAL", 0.3),
        ):
            await asyncio.gather(*[requester.get_data_async("http://test", "", {}) for _ in range(3)])

        spans.sort()
        assert len(spans) == 3
        for (_, prev_end), (start, _) in zip(spans, spans[1:]):
            assert start - prev_end >= 0.29, f"request started {start - prev_end:.3f}s after the previous response"

    def test_processes_are_serialized(self, tmp_path):
        """Three s2 processes sharing the lock never overlap and keep _RATE_INTERVAL between requests."""
        child = textwrap.dedent(
            """
            import asyncio, json, sys, time
            from unittest.mock import patch
            sys.path.insert(0, sys.argv[1])
            import httpx, s2
            s2._RATE_LOCK, s2._RATE_TS, s2._RATE_INTERVAL = sys.argv[2], sys.argv[3], 0.3

            async def slow_server(self, method, url, **kw):
                start = time.time()
                await asyncio.sleep(0.05)
                print(json.dumps([start, time.time()]), flush=True)
                return httpx.Response(200, json={}, request=httpx.Request(method, url))

            async def main():
                with patch.object(httpx.AsyncClient, "request", slow_server):
                    for _ in range(2):
                        await s2.S2Requester(10, False).get_data_async("http://test", "", {})

            asyncio.run(main())
            """
        )
        scripts = str(Path(__file__).resolve().parent.parent / "scripts")
        argv = [sys.executable, "-c", child, scripts, str(tmp_path / "s2_rate.lock"), str(tmp_path / "s2_rate.ts")]
        procs = [subprocess.Popen(argv, stdout=subprocess.PIPE, text=True) for _ in range(3)]
        spans = sorted(json.loads(line) for p in procs for line in p.communicate(timeout=30)[0].splitlines())

        assert len(spans) == 6
        for (_, prev_end), (start, _) in zip(spans, spans[1:]):
            assert start - prev_end >= 0.29, f"request started {start - prev_end:.3f}s after the previous response"


class TestParseRetryAfter:
    def test_seconds(self):
        assert _parse_retry_after("5") == 5.0

    def test_http_date(self):
        future = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
        assert 28.0 <= _parse_retry_after(future) <= 30.0

    def test_past_date_is_zero(self):
        assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0

    @pytest.mark.parametrize("value", [None, "", "soon"])
    def test_missing_or_invalid(self, value):
        assert _parse_retry_after(value) is None


# ---------------------------------------------------------------------------
# main() error handling
#
# All errors exit 0 — stderr message is sufficient for the model.
# Claude Code aborts sibling parallel tool calls on non-zero exit.
# ---------------------------------------------------------------------------


class TestMainErrorHandling:
    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_bad_query_parameters_prints_stderr(self, mock_cmd, capsys):
        from semanticscholar.SemanticScholarException import BadQueryParametersException

        mock_cmd.side_effect = BadQueryParametersException("Invalid field: bogus")

        with patch("sys.argv", ["s2", "search", "test"]):
            main()  # should NOT raise SystemExit

        stderr = capsys.readouterr().err
        assert "Invalid field: bogus" in stderr
        assert "s2 fields" in stderr

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_object_not_found_prints_stderr(self, mock_cmd, capsys):
        mock_cmd.side_effect = ObjectNotFoundException("Paper not found")

        with patch("sys.argv", ["s2", "search", "test"]):
            main()  # should NOT raise SystemExit

        stderr = capsys.readouterr().err
        assert "error: Paper not found" in stderr

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_permission_error_prints_stderr(self, mock_cmd, capsys):
        mock_cmd.side_effect = PermissionError()

        with patch("sys.argv", ["s2", "search", "test"]):
            main()  # should NOT raise SystemExit

        assert "S2_API_KEY" in capsys.readouterr().err

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_generic_exception_prints_stderr(self, mock_cmd, capsys):
        """Unhandled exceptions (anything not caught earlier) print to stderr and exit 0."""
        mock_cmd.side_effect = RuntimeError("something broke")

        with patch("sys.argv", ["s2", "search", "test"]):
            main()  # should NOT raise SystemExit

        stderr = capsys.readouterr().err
        assert "error: something broke" in stderr

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_retry_error_rate_limit_prints_stderr(self, mock_cmd, capsys):
        """RetryError wrapping rate limit → stderr contains 'rate limited', exits 0."""
        attempt = MagicMock()
        attempt.exception.return_value = ConnectionRefusedError("429")
        mock_cmd.side_effect = RetryError(attempt)

        with patch("sys.argv", ["s2", "search", "test"]):
            main()  # should NOT raise SystemExit

        stderr = capsys.readouterr().err
        assert "rate limited" in stderr

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_retry_error_server_error_prints_stderr(self, mock_cmd, capsys):
        """RetryError wrapping ServerErrorException → stderr contains 'server error', exits 0."""
        attempt = MagicMock()
        attempt.exception.return_value = InternalServerErrorException("500")
        mock_cmd.side_effect = RetryError(attempt)

        with patch("sys.argv", ["s2", "search", "test"]):
            main()  # should NOT raise SystemExit

        stderr = capsys.readouterr().err
        assert "server error" in stderr
        assert "transient" in stderr

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_httpx_timeout_prints_stderr(self, mock_cmd, capsys):
        """httpx.TimeoutException → stderr contains 'timed out', exits 0."""
        mock_cmd.side_effect = httpx.ReadTimeout("read timed out")

        with patch("sys.argv", ["s2", "search", "test"]):
            main()  # should NOT raise SystemExit

        stderr = capsys.readouterr().err
        assert "timed out" in stderr
        assert "server didn't respond" in stderr

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_connection_refused_prints_stderr(self, mock_cmd, capsys):
        """ConnectionRefusedError falls through to generic handler (stderr, exit 0)."""
        mock_cmd.side_effect = ConnectionRefusedError("connection refused")

        with patch("sys.argv", ["s2", "search", "test"]):
            main()  # should NOT raise SystemExit

        stderr = capsys.readouterr().err
        assert "error: connection refused" in stderr


# ---------------------------------------------------------------------------
# _describe_error
# ---------------------------------------------------------------------------


class TestDescribeError:
    @staticmethod
    def _make_retry_error(last_exception):
        """Build a RetryError whose last_attempt wraps the given exception."""
        attempt = MagicMock()
        attempt.exception.return_value = last_exception
        return RetryError(attempt)

    def test_retry_error_rate_limit(self):
        exc = self._make_retry_error(ConnectionRefusedError("429"))
        result = _describe_error(exc)
        assert "rate limited" in result
        assert "cannot be completed" in result

    def test_retry_error_server_error(self):
        exc = self._make_retry_error(InternalServerErrorException("500"))
        result = _describe_error(exc)
        assert "server error" in result
        assert "transient" in result

    def test_object_not_found(self):
        exc = ObjectNotFoundException("Paper not found")
        assert "Not found" in _describe_error(exc)
        assert "Verify" in _describe_error(exc)

    def test_httpx_timeout(self):
        exc = httpx.ReadTimeout("read timed out")
        result = _describe_error(exc)
        assert "timed out" in result
        assert "server didn't respond" in result

    def test_fallback_str(self):
        exc = RuntimeError("something unexpected")
        assert _describe_error(exc) == "something unexpected"


# ---------------------------------------------------------------------------
# main() argparse integration
# ---------------------------------------------------------------------------


class TestMainArgparse:
    def test_no_args_exits(self):
        with patch("sys.argv", ["s2"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_query_and_limit(self, mock_cmd):
        with patch("sys.argv", ["s2", "search", "attention", "-n", "5"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.query == "attention"
        assert args.limit == 5
        assert args.fields is None

    @patch("s2.cmd_get", new_callable=AsyncMock)
    def test_get_parses_ids_and_fields(self, mock_cmd):
        with patch("sys.argv", ["s2", "get", "-i", "id1", "id2", "-f", "title"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.ids == ["id1", "id2"]
        assert args.fields == "title"

    @patch("s2.cmd_citations", new_callable=AsyncMock)
    def test_citations_parses_year(self, mock_cmd):
        with patch("sys.argv", ["s2", "citations", "-i", "p1", "-y", "2018-2020"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.year == "2018-2020"

    @pytest.mark.parametrize("value", ["2026", "2018-2020", "2018-", "-2015"])
    @pytest.mark.parametrize("command", [["search", "q"], ["citations", "-i", "p1"]])
    @patch("s2.cmd_citations", new_callable=AsyncMock)
    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_year_accepts_years_and_ranges(self, mock_search, mock_citations, command, value):
        with patch("sys.argv", ["s2", *command, "-y", value]):
            main()

        mock_cmd = mock_search if command[0] == "search" else mock_citations
        assert mock_cmd.call_args[0][0].year == value

    @pytest.mark.parametrize("value", ["2026-06-01", "2026-06", "2020:2021", "26", "2018-2020-2022", "abcd"])
    @pytest.mark.parametrize("command", [["search", "q"], ["citations", "-i", "p1"]])
    @patch("s2.cmd_citations", new_callable=AsyncMock)
    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_year_rejects_dates_and_junk(self, mock_search, mock_citations, command, value, capsys):
        with patch("sys.argv", ["s2", *command, "-y", value]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 2
        assert "invalid year or range" in capsys.readouterr().err
        mock_search.assert_not_called()
        mock_citations.assert_not_called()

    @patch("s2.cmd_fields", new_callable=AsyncMock)
    def test_fields_command(self, mock_cmd):
        with patch("sys.argv", ["s2", "fields"]):
            main()
        mock_cmd.assert_called_once()

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_year_filter(self, mock_cmd):
        with patch("sys.argv", ["s2", "search", "test", "-y", "2020-2023"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.year == "2020-2023"

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_publication_date(self, mock_cmd):
        with patch("sys.argv", ["s2", "search", "test", "-d", "2020-06-01:2021-01-31"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.publication_date == "2020-06-01:2021-01-31"

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_publication_types(self, mock_cmd):
        with patch("sys.argv", ["s2", "search", "test", "-t", "JournalArticle,Conference"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.publication_types == "JournalArticle,Conference"

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_open_access(self, mock_cmd):
        with patch("sys.argv", ["s2", "search", "test", "--open-access"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.open_access is True

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_venue(self, mock_cmd):
        with patch("sys.argv", ["s2", "search", "test", "--venue", "NeurIPS,ICML"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.venue == "NeurIPS,ICML"

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_fields_of_study(self, mock_cmd):
        with patch("sys.argv", ["s2", "search", "test", "--fields-of-study", "Computer Science"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.fields_of_study == "Computer Science"

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_min_citations(self, mock_cmd):
        with patch("sys.argv", ["s2", "search", "test", "--min-citations", "50"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.min_citations == 50

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_match_title(self, mock_cmd):
        with patch("sys.argv", ["s2", "search", "attention is all you need", "--match-title"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.match_title is True

    @patch("s2.cmd_recommend", new_callable=AsyncMock)
    def test_recommend_parses_negative_ids(self, mock_cmd):
        with patch("sys.argv", ["s2", "recommend", "-i", "s1", "-x", "neg1", "neg2"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.ids == ["s1"]
        assert args.negative_ids == ["neg1", "neg2"]

    @patch("s2.cmd_recommend", new_callable=AsyncMock)
    def test_recommend_parses_pool(self, mock_cmd):
        with patch("sys.argv", ["s2", "recommend", "-i", "s1", "--pool", "all-cs"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.pool == "all-cs"

    def test_recommend_pool_rejects_invalid(self):
        with patch("sys.argv", ["s2", "recommend", "-i", "s1", "--pool", "invalid"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    @patch("s2.cmd_search_author", new_callable=AsyncMock)
    def test_search_author_parses_query(self, mock_cmd):
        with patch("sys.argv", ["s2", "search-author", "Yoshua Bengio", "-n", "5"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.query == "Yoshua Bengio"
        assert args.limit == 5

    @patch("s2.cmd_author_papers", new_callable=AsyncMock)
    def test_author_papers_parses_ids(self, mock_cmd):
        with patch("sys.argv", ["s2", "author-papers", "-i", "auth1", "auth2"]):
            main()

        args = mock_cmd.call_args[0][0]
        assert args.ids == ["auth1", "auth2"]


# ---------------------------------------------------------------------------
# read_ids — authorId extraction
# ---------------------------------------------------------------------------


class TestReadIdsAuthorId:
    def test_stdin_json_with_author_id(self):
        lines = ['{"authorId": "12345", "name": "Alice"}\n']
        stdin = io.StringIO("".join(lines))
        assert read_ids([], stdin) == ["12345"]

    def test_stdin_prefers_paper_id_over_author_id(self):
        """When both paperId and authorId exist, paperId wins."""
        lines = ['{"paperId": "p1", "authorId": "a1"}\n']
        stdin = io.StringIO("".join(lines))
        assert read_ids([], stdin) == ["p1"]

    def test_stdin_mixed_paper_and_author_ids(self):
        lines = [
            '{"paperId": "p1"}\n',
            '{"authorId": "a1"}\n',
            "DOI:10.1234/raw\n",
        ]
        stdin = io.StringIO("".join(lines))
        assert read_ids([], stdin) == ["p1", "a1", "DOI:10.1234/raw"]


# ---------------------------------------------------------------------------
# cmd_search — new filters
# ---------------------------------------------------------------------------


class TestCmdSearchFilters:
    @pytest.mark.asyncio
    async def test_publication_date_forwarded(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test", publication_date="2020-06-01:2021-01-31"))

        mock_client.search_paper.assert_called_once_with(
            "test",
            fields=SCAN_FIELDS,
            limit=10,
            publication_date_or_year="2020-06-01:2021-01-31",
        )

    @pytest.mark.asyncio
    async def test_publication_types_split_and_forwarded(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test", publication_types="JournalArticle,Conference"))

        call_kwargs = mock_client.search_paper.call_args
        assert call_kwargs[1]["publication_types"] == ["JournalArticle", "Conference"]

    @pytest.mark.asyncio
    async def test_open_access_forwarded(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test", open_access=True))

        call_kwargs = mock_client.search_paper.call_args
        assert call_kwargs[1]["open_access_pdf"] is True

    @pytest.mark.asyncio
    async def test_venue_split_and_forwarded(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test", venue="NeurIPS,ICML"))

        call_kwargs = mock_client.search_paper.call_args
        assert call_kwargs[1]["venue"] == ["NeurIPS", "ICML"]

    @pytest.mark.asyncio
    async def test_fields_of_study_split_and_forwarded(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test", fields_of_study="Computer Science,Medicine"))

        call_kwargs = mock_client.search_paper.call_args
        assert call_kwargs[1]["fields_of_study"] == ["Computer Science", "Medicine"]

    @pytest.mark.asyncio
    async def test_min_citations_forwarded(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test", min_citations=100))

        call_kwargs = mock_client.search_paper.call_args
        assert call_kwargs[1]["min_citation_count"] == 100

    @pytest.mark.asyncio
    async def test_match_title_returns_single_paper(self, mock_client, capsys):
        mock_client.search_paper.return_value = make_paper({"paperId": "p1", "title": "Attention Is All You Need"})

        await cmd_search(make_args(query="attention is all you need", match_title=True))

        call_kwargs = mock_client.search_paper.call_args
        assert call_kwargs[1]["match_title"] is True
        out = json.loads(capsys.readouterr().out.strip())
        assert out["paperId"] == "p1"

    @pytest.mark.asyncio
    async def test_none_filters_not_forwarded(self, mock_client):
        """Filters set to None/False should not appear in the API call kwargs."""
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(make_args(query="test"))

        mock_client.search_paper.assert_called_once_with("test", fields=SCAN_FIELDS, limit=10)

    @pytest.mark.asyncio
    async def test_multiple_filters_combined(self, mock_client):
        mock_client.search_paper.return_value = async_iter([])

        await cmd_search(
            make_args(
                query="federated learning",
                year="2020-2024",
                fields_of_study="Computer Science",
                min_citations=10,
                open_access=True,
            )
        )

        call_kwargs = mock_client.search_paper.call_args[1]
        assert call_kwargs["year"] == "2020-2024"
        assert call_kwargs["fields_of_study"] == ["Computer Science"]
        assert call_kwargs["min_citation_count"] == 10
        assert call_kwargs["open_access_pdf"] is True


# ---------------------------------------------------------------------------
# cmd_recommend — negative IDs and pool
# ---------------------------------------------------------------------------


class TestCmdRecommendNewFeatures:
    @pytest.mark.asyncio
    async def test_negative_ids_forces_list_mode(self, mock_client, capsys):
        """Even with a single seed, negative IDs trigger list-based recommendations."""
        mock_client.get_recommended_papers_from_lists.return_value = [make_paper({"paperId": "rec1"})]

        await cmd_recommend(make_args(ids=["seed1"], negative_ids=["neg1", "neg2"], limit=5))

        mock_client.get_recommended_papers_from_lists.assert_called_once_with(
            ["seed1"], fields=SCAN_FIELDS, limit=5, negative_paper_ids=["neg1", "neg2"]
        )
        mock_client.get_recommended_papers.assert_not_called()
        out = json.loads(capsys.readouterr().out.strip())
        assert out["paperId"] == "rec1"

    @pytest.mark.asyncio
    async def test_pool_forwarded_to_single_seed(self, mock_client):
        mock_client.get_recommended_papers.return_value = []

        await cmd_recommend(make_args(ids=["seed1"], pool="all-cs", limit=5))

        mock_client.get_recommended_papers.assert_called_once_with(
            "seed1", fields=SCAN_FIELDS, limit=5, pool_from="all-cs"
        )

    @pytest.mark.asyncio
    async def test_multiple_seeds_with_negative_ids(self, mock_client):
        mock_client.get_recommended_papers_from_lists.return_value = []

        await cmd_recommend(make_args(ids=["s1", "s2"], negative_ids=["neg1"], limit=10))

        mock_client.get_recommended_papers_from_lists.assert_called_once_with(
            ["s1", "s2"], fields=SCAN_FIELDS, limit=10, negative_paper_ids=["neg1"]
        )

    @pytest.mark.asyncio
    async def test_none_result(self, mock_client, capsys):
        mock_client.get_recommended_papers.return_value = None

        await cmd_recommend(make_args(ids=["seed1"], limit=5))

        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# cmd_search_author
# ---------------------------------------------------------------------------


class TestCmdSearchAuthor:
    @pytest.mark.asyncio
    async def test_basic_search(self, mock_client, capsys):
        authors = [
            make_paper({"authorId": "a1", "name": "Alice"}),
            make_paper({"authorId": "a2", "name": "Bob"}),
        ]
        mock_client.search_author.return_value = async_iter(authors)

        await cmd_search_author(make_args(query="Alice", limit=10))

        mock_client.search_author.assert_called_once_with("Alice", fields=AUTHOR_SCAN_FIELDS, limit=10)
        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["authorId"] == "a1"
        assert json.loads(lines[1])["authorId"] == "a2"

    @pytest.mark.asyncio
    async def test_custom_fields(self, mock_client):
        mock_client.search_author.return_value = async_iter([make_paper({"name": "X"})])

        await cmd_search_author(make_args(query="test", fields="name,hIndex", limit=5))

        mock_client.search_author.assert_called_once_with("test", fields=["name", "hIndex"], limit=5)

    @pytest.mark.asyncio
    async def test_limit_stops_iteration(self, mock_client, capsys):
        authors = [make_paper({"authorId": f"a{i}"}) for i in range(10)]
        mock_client.search_author.return_value = async_iter(authors)

        await cmd_search_author(make_args(query="test", limit=3))

        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 3

    @pytest.mark.asyncio
    async def test_limit_caps_at_1000(self, mock_client):
        mock_client.search_author.return_value = async_iter([])

        await cmd_search_author(make_args(query="test", limit=2000))

        mock_client.search_author.assert_called_once_with("test", fields=AUTHOR_SCAN_FIELDS, limit=1000)

    @pytest.mark.asyncio
    async def test_none_result(self, mock_client, capsys):
        mock_client.search_author.return_value = None

        await cmd_search_author(make_args(query="nobody", limit=5))

        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# cmd_author_papers
# ---------------------------------------------------------------------------


class TestCmdAuthorPapers:
    @pytest.mark.asyncio
    async def test_basic_author_papers(self, mock_client, capsys):
        papers = [
            make_paper({"paperId": "p1", "title": "Paper 1"}),
            make_paper({"paperId": "p2", "title": "Paper 2"}),
        ]
        mock_client.get_author_papers.return_value = async_iter(papers)

        await cmd_author_papers(make_args(ids=["auth1"], limit=10))

        mock_client.get_author_papers.assert_called_once_with("auth1", fields=SCAN_FIELDS, limit=10)
        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["paperId"] == "p1"
        assert first["sourceAuthorId"] == "auth1"

    @pytest.mark.asyncio
    async def test_multiple_authors_tracked(self, mock_client, capsys):
        mock_client.get_author_papers.side_effect = [
            async_iter([make_paper({"paperId": "p1"})]),
            async_iter([make_paper({"paperId": "p2"})]),
        ]

        await cmd_author_papers(make_args(ids=["auth1", "auth2"], limit=10))

        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["sourceAuthorId"] == "auth1"
        assert json.loads(lines[1])["sourceAuthorId"] == "auth2"

    @pytest.mark.asyncio
    async def test_error_continues_other_authors(self, mock_client, capsys):
        """If one author fails, the others still return results."""
        mock_client.get_author_papers.side_effect = [
            ObjectNotFoundException("Author not found"),
            async_iter([make_paper({"paperId": "p2"})]),
        ]

        await cmd_author_papers(make_args(ids=["bad_auth", "good_auth"], limit=10))

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["sourceAuthorId"] == "good_auth"
        assert "bad_auth" in captured.err

    @pytest.mark.asyncio
    async def test_limit_stops_iteration(self, mock_client, capsys):
        papers = [make_paper({"paperId": f"p{i}"}) for i in range(10)]
        mock_client.get_author_papers.return_value = async_iter(papers)

        await cmd_author_papers(make_args(ids=["auth1"], limit=3))

        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 3

    @pytest.mark.asyncio
    async def test_limit_caps_at_1000(self, mock_client):
        mock_client.get_author_papers.return_value = async_iter([])

        await cmd_author_papers(make_args(ids=["auth1"], limit=2000))

        mock_client.get_author_papers.assert_called_once_with("auth1", fields=SCAN_FIELDS, limit=1000)

    @pytest.mark.asyncio
    async def test_no_ids_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            await cmd_author_papers(make_args(ids=None))
        assert exc_info.value.code == 0

    @pytest.mark.asyncio
    async def test_none_result_skipped(self, mock_client, capsys):
        mock_client.get_author_papers.return_value = None

        await cmd_author_papers(make_args(ids=["auth1"], limit=5))

        assert capsys.readouterr().out == ""

    @pytest.mark.asyncio
    async def test_custom_fields(self, mock_client):
        mock_client.get_author_papers.return_value = async_iter([make_paper({"title": "X"})])

        await cmd_author_papers(make_args(ids=["auth1"], fields="title,year", limit=5))

        mock_client.get_author_papers.assert_called_once_with("auth1", fields=["title", "year"], limit=5)


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

ARXIV_HTML = """<html><head><title>T</title><script>var x = 1;</script></head><body>
<nav>Back to arXiv</nav><h5 class="modal-title">Report issue</h5>
<article class="ltx_document">
<h1 class="ltx_title ltx_title_document">A Paper</h1>
<h6 class="ltx_title ltx_title_abstract">Abstract</h6><p>We study <math alttext="k" display="inline"><mi>k</mi></math> things.</p>
<section><h2 class="ltx_title ltx_title_section"><span class="ltx_tag">1 </span>Introduction</h2>
<p>Context   collapse is   common.</p></section>
<button>Copy</button>
</article></body></html>"""


def _transport(routes, calls=None):
    """httpx MockTransport answering URL -> (status, content); unknown URLs get 404."""

    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        status, content = routes.get(str(request.url), (404, b""))
        return httpx.Response(status, content=content)

    return httpx.MockTransport(handler)


def _http(routes, calls=None):
    return lambda: httpx.AsyncClient(transport=_transport(routes, calls))


ARXIV_PAPER = {"paperId": "p1", "title": "A Paper", "year": 2026, "citationCount": 3, "externalIds": {"ArXiv": "2604.00001"}}


class TestHtmlToText:
    def test_article_text_sections_and_math(self):
        text, sections = html_to_text(ARXIV_HTML)
        assert sections == ["A Paper", "Abstract", "1 Introduction"]
        assert "# A Paper" in text
        assert "## 1 Introduction" in text
        assert "We study k things." in text
        assert "Context collapse is common." in text
        for noise in ("Back to arXiv", "Report issue", "var x", "Copy"):
            assert noise not in text

    def test_page_without_article_uses_whole_body(self):
        text, sections = html_to_text("<body><h2>Intro</h2><p>Body text</p></body>")
        assert sections == ["Intro"]
        assert "Body text" in text


class TestPdfToText:
    def test_extracts_pages_and_heading_lines(self):
        pages = [SimpleNamespace(extract_text=lambda: "Abstract\nWe do things.\n1 Introduction\nText 2 more."),
                 SimpleNamespace(extract_text=lambda: "References\n[1] Someone. 2020.")]
        with patch("s2.PdfReader", return_value=SimpleNamespace(pages=pages)):
            text, sections = pdf_to_text(b"%PDF-1.7")
        assert sections == ["Abstract", "1 Introduction", "References"]
        assert "We do things." in text and "[1] Someone" in text


class TestFigures:
    PAGES = [
        "1 Introduction\nAs shown in Figure 2, results improve.\nFigure 1 shows the setup.",
        "Figure 1: Overview of the pipeline.\nIt has three stages.\nTable 1. Main results on four benchmarks.",
        "Fig. 2. Accuracy versus model size.\nWe see in Figure 1: nothing new.",
        "Figure 3.5 is a subfigure label, not a caption",
    ]
    # Publisher styles: a wrapped mention ("Figure 4.") before the real caption, an all-caps label
    # alone on its line, and a label followed directly by a capitalized caption.
    PUBLISHER_PAGES = [
        "the results are shown in\nFigure 4. Detailed strategies are listed.",
        "FIGURE 4\nForest plot of effects.\nTABLE 2 Characteristics of studies.",
        "Figure 5 Flow diagram of the study selection.",
    ]

    def test_captions_not_mentions(self):
        figures = find_figures(self.PAGES)
        assert [(f["label"], f["page"]) for f in figures] == [("Figure 1", 2), ("Table 1", 2), ("Figure 2", 3)]
        assert figures[0]["caption"].startswith("Figure 1: Overview of the pipeline.")
        assert len(figures[0]["caption"]) <= 200

    def test_publisher_caption_styles(self):
        figures = find_figures(self.PUBLISHER_PAGES)
        assert [(f["label"], f["page"]) for f in figures] == [("Figure 4", 2), ("Table 2", 2), ("Figure 5", 3)]

    def test_mark_captions_best_occurrence_only(self):
        figures = [{"label": "Figure 1", "caption": "", "page": 4}, {"label": "Table 1", "caption": "", "page": 5}]
        text = "Intro\nFigure 1. wrapped mention\nFigure 1: Overview.\nTable 1: Results.\nFigure 9: unknown.\n"
        marked = mark_captions(text, figures)
        assert "[Figure 1, PDF page 4] Figure 1: Overview." in marked
        assert "[Table 1, PDF page 5] Table 1: Results." in marked
        assert "\nFigure 1. wrapped mention" in marked
        assert "\nFigure 9: unknown." in marked
        assert mark_captions(marked, figures) == marked

    def test_html_figcaption_gets_marker(self):
        html = ARXIV_HTML.replace(
            "<button>", '<figure><img src="x.png"><figcaption>Figure 1: The pipeline.</figcaption></figure><button>'
        )
        text, _ = html_to_text(html)
        marked = mark_captions(text, [{"label": "Figure 1", "caption": "", "page": 3}])
        assert "[Figure 1, PDF page 3] Figure 1: The pipeline." in marked


class TestFetchFullText:
    @pytest.mark.asyncio
    async def test_arxiv_html_first(self):
        routes = {"https://arxiv.org/html/2604.00001": (200, ARXIV_HTML.encode())}
        async with _http(routes)() as http:
            text, sections, source, pdf = await fetch_full_text(http, ARXIV_PAPER)
        assert source == "arxiv-html"
        assert "1 Introduction" in sections
        assert pdf is None

    @pytest.mark.asyncio
    async def test_arxiv_html_text_and_arxiv_pdf(self):
        routes = {
            "https://arxiv.org/html/2604.00001": (200, ARXIV_HTML.encode()),
            "https://arxiv.org/pdf/2604.00001": (200, b"%PDF-1.7 body"),
        }
        with patch("s2.pdf_to_text") as conv:
            async with _http(routes)() as http:
                text, sections, source, pdf = await fetch_full_text(http, ARXIV_PAPER)
        assert source == "arxiv-html"
        assert pdf == b"%PDF-1.7 body"
        conv.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_arxiv_pdf(self):
        routes = {"https://arxiv.org/pdf/2604.00001": (200, b"%PDF-1.7 body")}
        with patch("s2.pdf_to_text", return_value=("pdf text\n", [])) as conv:
            async with _http(routes)() as http:
                text, sections, source, pdf = await fetch_full_text(http, ARXIV_PAPER)
        assert (text, sections, source, pdf) == ("pdf text\n", [], "arxiv-pdf", b"%PDF-1.7 body")
        conv.assert_called_once_with(b"%PDF-1.7 body")

    @pytest.mark.asyncio
    async def test_html_without_document_falls_back(self):
        routes = {
            "https://arxiv.org/html/2604.00001": (200, b"<html>HTML is not available</html>"),
            "https://arxiv.org/pdf/2604.00001": (200, b"%PDF-1.7"),
        }
        with patch("s2.pdf_to_text", return_value=("t\n", [])):
            async with _http(routes)() as http:
                assert (await fetch_full_text(http, ARXIV_PAPER))[2] == "arxiv-pdf"

    @pytest.mark.asyncio
    async def test_open_access_pdf_for_non_arxiv(self):
        paper = {"paperId": "p2", "openAccessPdf": {"url": "https://example.org/a.pdf"}}
        routes = {"https://example.org/a.pdf": (200, b"%PDF-1.4")}
        with patch("s2.pdf_to_text", return_value=("t\n", [])):
            async with _http(routes)() as http:
                assert (await fetch_full_text(http, paper))[2] == "open-access-pdf"

    @pytest.mark.asyncio
    async def test_open_access_landing_page_is_not_a_pdf(self):
        paper = {"paperId": "p2", "openAccessPdf": {"url": "https://example.org/landing"}}
        routes = {"https://example.org/landing": (200, b"<html>landing</html>")}
        async with _http(routes)() as http:
            assert await fetch_full_text(http, paper) == (None, [], None, None)

    @pytest.mark.asyncio
    async def test_retries_server_errors(self):
        answers = iter([503, 429, 200])

        def handler(request):
            return httpx.Response(next(answers), content=b"%PDF-1.7")

        with patch("s2.asyncio.sleep", new_callable=AsyncMock) as sleep:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                r = await _fetch(http, "https://example.org/a.pdf")
        assert r.status_code == 200
        assert sleep.await_count == 2


class TestCmdRead:
    @pytest.fixture(autouse=True)
    def _cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("S2_CACHE_DIR", str(tmp_path))
        self.cache = tmp_path

    def _setup(self, mock_client, paper=ARXIV_PAPER, refs=()):
        mock_client.get_papers.return_value = ([make_paper(paper)], [])
        mock_client.get_paper_references.return_value = async_iter(list(refs))
        mock_client.get_paper_citations.return_value = async_iter([])

    @pytest.mark.asyncio
    async def test_outputs_full_text_path_sections_and_refs(self, mock_client, capsys):
        refs = [
            make_citation({"citedPaper": {"paperId": "r1", "title": "Ref", "year": 2020}}),
            make_citation({"citedPaper": {"paperId": None, "title": "Unresolved", "year": None}}),
            make_citation({"citedPaper": {}}, has_paper=False),
        ]
        self._setup(mock_client, refs=refs)
        routes = {"https://arxiv.org/html/2604.00001": (200, ARXIV_HTML.encode())}
        with patch("s2._http_client", _http(routes)):
            await cmd_read(make_args(ids=["ArXiv:2604.00001"], refs=50))

        out = json.loads(capsys.readouterr().out)
        assert out["fullTextSource"] == "arxiv-html"
        assert Path(out["fullTextPath"]) == self.cache / "p1.txt"
        assert "Context collapse is common." in Path(out["fullTextPath"]).read_text()
        assert out["sections"] == ["A Paper", "Abstract", "1 Introduction"]
        assert out["references"] == [{"paperId": "r1", "title": "Ref", "year": 2020}]
        assert out["citationCount"] == 3
        assert out["citationsInRange"] is None
        assert out["pdfPath"] is None and out["figures"] == []
        mock_client.get_paper_citations.assert_not_called()

    @pytest.mark.asyncio
    async def test_year_counts_citations_in_range(self, mock_client, capsys):
        self._setup(mock_client)
        mock_client.get_paper_citations.return_value = async_iter([make_citation({}) for _ in range(4)])
        with patch("s2._http_client", _http({})):
            await cmd_read(make_args(ids=["p1"], refs=0, year="2018-2020"))

        out = json.loads(capsys.readouterr().out)
        assert out["citationsInRange"] == 4
        mock_client.get_paper_citations.assert_called_once_with(
            "p1", fields=["paperId"], limit=1000, publication_date_or_year="2018:2020"
        )
        mock_client.get_paper_references.assert_not_called()

    @pytest.mark.asyncio
    async def test_refs_limit(self, mock_client, capsys):
        refs = [make_citation({"citedPaper": {"paperId": f"r{i}", "title": "t", "year": 2020}}) for i in range(5)]
        self._setup(mock_client, refs=refs)
        with patch("s2._http_client", _http({})):
            await cmd_read(make_args(ids=["p1"], refs=2))
        assert [r["paperId"] for r in json.loads(capsys.readouterr().out)["references"]] == ["r0", "r1"]

    @pytest.mark.asyncio
    async def test_no_full_text_warns_loudly(self, mock_client, capsys):
        self._setup(mock_client, paper={"paperId": "p9", "title": "Lost Paper", "externalIds": {}})
        with patch("s2._http_client", _http({})):
            await cmd_read(make_args(ids=["p9"], refs=0))

        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["fullTextSource"] is None and out["fullTextPath"] is None
        assert "p9: no full text found" in captured.err
        assert "'Lost Paper'" in captured.err
        assert out["pdfPath"] is None and out["figures"] == []

    @pytest.mark.asyncio
    async def test_saves_pdf_and_lists_figures(self, mock_client, capsys):
        self._setup(mock_client)
        html = ARXIV_HTML.replace("<button>", "<figure><figcaption>Figure 1: The pipeline.</figcaption></figure><button>")
        routes = {
            "https://arxiv.org/html/2604.00001": (200, html.encode()),
            "https://arxiv.org/pdf/2604.00001": (200, b"%PDF-1.7 body"),
        }
        with patch("s2.pdf_pages", return_value=["Intro", "Figure 1: The pipeline."]), \
                patch("s2._http_client", _http(routes)):
            await cmd_read(make_args(ids=["p1"], refs=0))

        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert Path(out["pdfPath"]) == self.cache / "p1.pdf"
        assert Path(out["pdfPath"]).read_bytes() == b"%PDF-1.7 body"
        assert out["figures"] == [{"label": "Figure 1", "caption": "Figure 1: The pipeline.", "page": 2}]
        assert "[Figure 1, PDF page 2] Figure 1: The pipeline." in Path(out["fullTextPath"]).read_text()
        assert "warning" not in captured.err

    @pytest.mark.asyncio
    async def test_text_without_pdf_warns(self, mock_client, capsys):
        self._setup(mock_client)
        routes = {"https://arxiv.org/html/2604.00001": (200, ARXIV_HTML.encode())}
        with patch("s2._http_client", _http(routes)):
            await cmd_read(make_args(ids=["p1"], refs=0))
        captured = capsys.readouterr()
        assert json.loads(captured.out)["pdfPath"] is None
        assert "p1: no PDF found, so figures are unavailable" in captured.err

    @pytest.mark.asyncio
    async def test_unreadable_pdf_keeps_text(self, mock_client, capsys):
        from pypdf.errors import PdfReadError

        self._setup(mock_client)
        routes = {
            "https://arxiv.org/html/2604.00001": (200, ARXIV_HTML.encode()),
            "https://arxiv.org/pdf/2604.00001": (200, b"%PDF-broken"),
        }
        with patch("s2.pdf_pages", side_effect=PdfReadError("bad")), patch("s2._http_client", _http(routes)):
            await cmd_read(make_args(ids=["p1"], refs=0))
        out = json.loads(capsys.readouterr().out)
        assert out["fullTextSource"] == "arxiv-html" and out["figures"] == []
        assert out["pdfPath"] is not None

    @pytest.mark.asyncio
    async def test_cache_reused(self, mock_client, capsys):
        calls = []
        routes = {"https://arxiv.org/html/2604.00001": (200, ARXIV_HTML.encode())}
        for _ in range(2):
            self._setup(mock_client)
            with patch("s2._http_client", _http(routes, calls)):
                await cmd_read(make_args(ids=["p1"], refs=0))

        first, second = (json.loads(line) for line in capsys.readouterr().out.splitlines())
        assert calls == ["https://arxiv.org/html/2604.00001", "https://arxiv.org/pdf/2604.00001"]
        assert first == second

    @pytest.mark.asyncio
    async def test_cache_reuses_pdf_and_figures(self, mock_client, capsys):
        calls = []
        routes = {
            "https://arxiv.org/html/2604.00001": (200, ARXIV_HTML.encode()),
            "https://arxiv.org/pdf/2604.00001": (200, b"%PDF-1.7"),
        }
        with patch("s2.pdf_pages", return_value=["Table 1: Results."]) as pages:
            for _ in range(2):
                self._setup(mock_client)
                with patch("s2._http_client", _http(routes, calls)):
                    await cmd_read(make_args(ids=["p1"], refs=0))
        first, second = (json.loads(line) for line in capsys.readouterr().out.splitlines())
        assert len(calls) == 2 and pages.call_count == 1
        assert first == second and second["figures"][0]["label"] == "Table 1"

    @pytest.mark.asyncio
    async def test_cache_without_figures_is_refetched(self, mock_client, capsys):
        (self.cache / "p1.txt").write_text("old text\n")
        (self.cache / "p1.json").write_text(json.dumps({"sections": [], "source": "arxiv-html"}))
        self._setup(mock_client)
        routes = {"https://arxiv.org/html/2604.00001": (200, ARXIV_HTML.encode())}
        with patch("s2._http_client", _http(routes)):
            await cmd_read(make_args(ids=["p1"], refs=0))
        out = json.loads(capsys.readouterr().out)
        assert "Context collapse is common." in Path(out["fullTextPath"]).read_text()

    @pytest.mark.asyncio
    async def test_reads_ids_from_piped_search_output(self, mock_client):
        self._setup(mock_client)
        piped = io.StringIO('{"paperId": "p1", "title": "A"}\n{"paperId": "p2", "title": "B"}\n')
        with patch("sys.stdin", piped), patch("s2._http_client", _http({})):
            await cmd_read(make_args(ids=None, refs=0))
        assert mock_client.get_papers.call_args.args[0] == ["p1", "p2"]

    @pytest.mark.asyncio
    async def test_not_found_ids_reported(self, mock_client, capsys):
        mock_client.get_papers.return_value = ([], ["ArXiv:9999.99999"])
        with patch("s2._http_client", _http({})):
            await cmd_read(make_args(ids=["ArXiv:9999.99999"], refs=0))
        assert "error: not found: ArXiv:9999.99999" in capsys.readouterr().err

    def test_rejects_date_for_year(self, capsys):
        with patch("sys.argv", ["s2", "read", "-i", "p1", "-y", "2026-06-01"]), pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
