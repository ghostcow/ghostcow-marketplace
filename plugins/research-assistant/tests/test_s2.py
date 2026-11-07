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
    RETRY_ATTEMPTS,
    SCAN_FIELDS,
    BadQueryParametersException,
    ObjectNotFoundException,
    PAGED_WINDOW,
    SEARCH_WINDOW,
    READ_CACHE_SECONDS,
    READ_NOTE,
    RateLimitedError,
    S2APIError,
    S2Client,
    ServerErrorException,
    S2Requester,
    _describe_error,
    _fetch,
    _parse_retry_after,
    cmd_author_papers,
    cmd_citations,
    cmd_get,
    cmd_read,
    cmd_recommend,
    cmd_references,
    cmd_search,
    cmd_search_author,
    main,
    make_client,
    read_ids,
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

    @pytest.mark.asyncio
    async def test_match_title_returns_single_paper(self, mock_client, capsys):
        mock_client.match_paper_title.return_value = make_paper({"paperId": "p1", "title": "Attention Is All You Need"})

        await cmd_search(make_args(query="attention is all you need", match_title=True))

        mock_client.match_paper_title.assert_called_once_with("attention is all you need", fields=SCAN_FIELDS)
        mock_client.search_paper.assert_not_called()
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
# cmd_get
# ---------------------------------------------------------------------------


class TestCmdGet:
    @pytest.mark.asyncio
    async def test_basic_get(self, mock_client, capsys):
        papers = [make_paper({"paperId": "p1", "title": "Paper 1"})]
        mock_client.get_papers.return_value = (papers, [])

        await cmd_get(make_args(ids=["p1"]))

        mock_client.get_papers.assert_called_once_with(["p1"], fields=DETAIL_FIELDS)
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

        mock_client.get_papers.assert_called_once_with(["p1"], fields=["title", "abstract"])


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
        client._requester.request = AsyncMock(side_effect=pages)

        results = await client.get_paper_citations("p1", fields=["title"], limit=2, publication_date_or_year="2026")
        ids = [item["citingPaper"]["paperId"] async for item in results]

        assert ids == ["c1", "c2", "c3"]
        calls = client._requester.request.call_args_list
        assert len(calls) == 2
        for call in calls:
            url, params = call.args[0], call.args[1]
            assert url.endswith("/graph/v1/paper/p1/citations")
            assert params["publicationDateOrYear"] == "2026"
        assert [call.args[1]["offset"] for call in calls] == [0, 2]

    @pytest.mark.asyncio
    async def test_no_filter_omits_parameter(self):
        client = S2Client(api_key=None)
        client._requester.request = AsyncMock(return_value={"offset": 0, "data": []})

        results = await client.get_paper_citations("p1", fields=["title"], limit=5)
        assert [item async for item in results] == []

        params = client._requester.request.call_args.args[1]
        assert "publicationDateOrYear" not in params


class TestS2ClientGetPapers:
    @pytest.mark.asyncio
    async def test_prefixed_ids_found_by_position(self):
        # The response has no externalIds, so ID matching cannot confirm these.
        client = S2Client(api_key=None)
        ids = ["DOI:10.1/x", "PMID:123", "URL:https://arxiv.org/abs/1706.03762", "CorpusId:42"]
        client._requester.request = AsyncMock(return_value=[{"paperId": f"p{i}"} for i in range(4)])

        papers, not_found = await client.get_papers(ids, fields=["title"])

        assert [p["paperId"] for p in papers] == ["p0", "p1", "p2", "p3"]
        assert not_found == []

    @pytest.mark.asyncio
    async def test_null_entries_are_not_found(self):
        client = S2Client(api_key=None)
        client._requester.request = AsyncMock(return_value=[{"paperId": "p0"}, None, None])

        papers, not_found = await client.get_papers(["DOI:a", "DOI:b", "ArXiv:c"], fields=["title"])

        assert [p["paperId"] for p in papers] == ["p0"]
        assert not_found == ["DOI:b", "ArXiv:c"]

    @pytest.mark.asyncio
    async def test_length_mismatch_gives_unknown(self):
        client = S2Client(api_key=None)
        client._requester.request = AsyncMock(return_value=[{"paperId": "p0"}])

        papers, not_found = await client.get_papers(["DOI:a", "DOI:b"], fields=["title"])

        assert [p["paperId"] for p in papers] == ["p0"]
        assert not_found is None

    @pytest.mark.asyncio
    async def test_batch_request_shape(self):
        client = S2Client(api_key=None)
        client._requester.request = AsyncMock(return_value=[{"paperId": "p0"}])

        papers, not_found = await client.get_papers(["p0"], fields=["title", "year"])

        url, params, payload = client._requester.request.call_args.args
        assert url.endswith("/graph/v1/paper/batch")
        assert params == {"fields": "title,year"}
        assert payload == {"ids": ["p0"]}
        assert [p["paperId"] for p in papers] == ["p0"]
        assert not_found == []


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


def _server(mock, answer, max_calls=20):
    """Script the mocked HTTP server: answer(params) builds each response from the request's query params.

    Fails instead of hanging when the client keeps requesting.
    """

    def respond(*_args, **kwargs):
        if mock.call_count > max_calls:
            raise AssertionError(f"client did not stop: {mock.call_count} requests")
        return answer(kwargs.get("params") or {})

    mock.side_effect = respond


def _requested(mock):
    """(offset, limit) of every request the client sent."""
    return [(c.kwargs["params"].get("offset"), c.kwargs["params"].get("limit")) for c in mock.call_args_list]


async def _drain(results):
    return [item async for item in results]


class TestUnlimitedByDefault:
    """With no -n, commands print every item and request full pages."""

    @pytest.mark.asyncio
    async def test_search_prints_all(self, mock_client, capsys):
        mock_client.search_paper.return_value = async_iter([make_paper({"paperId": f"p{i}"}) for i in range(250)])
        await cmd_search(make_args(query="q", limit=None))
        assert len(capsys.readouterr().out.splitlines()) == 250
        assert mock_client.search_paper.call_args.kwargs["limit"] == 100

    @pytest.mark.asyncio
    async def test_search_author_prints_all(self, mock_client, capsys):
        mock_client.search_author.return_value = async_iter([{"authorId": f"a{i}"} for i in range(1200)])
        await cmd_search_author(make_args(query="q", limit=None))
        assert len(capsys.readouterr().out.splitlines()) == 1200
        assert mock_client.search_author.call_args.kwargs["limit"] == 1000

    @pytest.mark.asyncio
    async def test_citations_print_all_per_input(self, mock_client, capsys):
        mock_client.get_paper_citations.side_effect = [
            async_iter([make_citation({"paperId": f"c{i}"}) for i in range(1100)]),
            async_iter([make_citation({"paperId": "d0"})]),
        ]
        await cmd_citations(make_args(ids=["p1", "p2"], limit=None))
        assert len(capsys.readouterr().out.splitlines()) == 1101
        assert mock_client.get_paper_citations.call_args.kwargs["limit"] == 1000

    @pytest.mark.asyncio
    async def test_author_papers_print_all(self, mock_client, capsys):
        mock_client.get_author_papers.return_value = async_iter([make_paper({"paperId": f"p{i}"}) for i in range(30)])
        await cmd_author_papers(make_args(ids=["a1"], limit=None))
        assert len(capsys.readouterr().out.splitlines()) == 30

    @pytest.mark.asyncio
    async def test_recommend_requests_endpoint_maximum(self, mock_client):
        mock_client.get_recommended_papers.return_value = [make_paper({"paperId": "r1"})]
        await cmd_recommend(make_args(ids=["p1"], limit=None))
        assert mock_client.get_recommended_papers.call_args.kwargs["limit"] == 500

    @pytest.mark.asyncio
    async def test_explicit_limit_still_caps(self, mock_client, capsys):
        mock_client.search_paper.return_value = async_iter([make_paper({"paperId": f"p{i}"}) for i in range(50)])
        await cmd_search(make_args(query="q", limit=7))
        assert len(capsys.readouterr().out.splitlines()) == 7
        assert mock_client.search_paper.call_args.kwargs["limit"] == 7


class TestPaging:
    """S2Client._pages against every response shape a page can take.

    Every shape that cannot advance must end paging; none may re-request a page.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            {"total": 0, "offset": 0},  # the API's answer to a search with no matches: no "data" key
            {"total": 0, "offset": 0, "data": []},  # the documented empty answer
            {},
            {"offset": 0, "next": 10, "data": []},  # empty page that still claims a next page
            {"offset": 0, "data": None},
            [],  # a list where the API defines an object
        ],
        ids=["no-data-key", "empty-data", "empty-object", "empty-data-with-next", "null-data", "list-body"],
    )
    async def test_page_without_items_ends_paging(self, http, unthrottled, body):
        _server(http, lambda _p: _response(200, body))
        results = await S2Client(api_key="k").search_paper("no such paper", fields=["title"], limit=10)
        assert await _drain(results) == []
        assert http.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("next_value", [0, -5, "10", None], ids=["same-offset", "backwards", "string", "null"])
    async def test_next_that_does_not_advance_ends_paging(self, http, unthrottled, next_value):
        _server(http, lambda _p: _response(200, {"offset": 0, "next": next_value, "data": [{"paperId": "p"}]}))
        results = await S2Client(api_key="k").get_paper_references("p1", fields=["title"], limit=10)
        assert await _drain(results) == [{"paperId": "p"}]
        assert http.call_count == 1

    @pytest.mark.asyncio
    async def test_follows_next_until_absent(self, http, unthrottled):
        def answer(params):
            offset = params["offset"]
            page = {"offset": offset, "data": [{"paperId": f"p{offset + i}"} for i in range(2)]}
            if offset < 4:
                page["next"] = offset + 2
            return _response(200, page)

        _server(http, answer)
        results = await S2Client(api_key="k").get_author_papers("a1", fields=["title"], limit=2)
        assert [p["paperId"] for p in await _drain(results)] == [f"p{i}" for i in range(6)]
        assert _requested(http) == [(0, 2), (2, 2), (4, 2)]

    @staticmethod
    def _full_pages(params):
        """A server that always has more: a full page and the next offset (the API's next=9999 at the window edge)."""
        offset, limit = params["offset"], params["limit"]
        return _response(200, {"offset": offset, "next": offset + limit, "data": [{"i": offset + i} for i in range(limit)]})

    @pytest.mark.asyncio
    async def test_search_stays_within_relevance_window(self, http, unthrottled):
        _server(http, self._full_pages)
        results = await S2Client(api_key="k").search_paper("q", fields=["title"], limit=100)
        assert len(await _drain(results)) == 1000
        requested = _requested(http)
        assert requested[-1] == (900, 100)
        assert all(offset + limit <= SEARCH_WINDOW for offset, limit in requested)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "call",
        [
            lambda c: c.get_paper_citations("p1", fields=["title"], limit=1000),
            lambda c: c.search_author("q", fields=["name"], limit=1000),
        ],
        ids=["citations", "search-author"],
    )
    async def test_paged_endpoints_stay_below_ten_thousand(self, http, unthrottled, call):
        _server(http, self._full_pages)
        assert len(await _drain(await call(S2Client(api_key="k")))) == PAGED_WINDOW
        requested = _requested(http)
        assert requested[-1] == (9000, 999)
        assert all(offset + limit < 10000 for offset, limit in requested)

    @pytest.mark.asyncio
    async def test_cmd_search_with_no_matches_exits(self, http, unthrottled, capsys):
        _server(http, lambda _p: _response(200, {"total": 0, "offset": 0}))
        with patch("s2.make_client", return_value=S2Client(api_key="k")):
            await cmd_search(make_args(query="no such paper"))
        assert capsys.readouterr().out == ""
        assert http.call_count == 1

    @pytest.mark.asyncio
    async def test_error_while_paging_raises(self, http, unthrottled):
        _server(http, lambda _p: _response(200, {"error": "something broke"}))
        results = await S2Client(api_key="k").search_paper("q", fields=["title"], limit=10)
        with pytest.raises(S2APIError, match="something broke"):
            await _drain(results)


class TestResponseContract:
    """Statuses and bodies outside the success contract raise instead of reading as empty data."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "body", "exc_type", "message"),
        [
            (401, {"message": "Unauthorized"}, PermissionError, "Unauthorized"),
            (403, {"message": "Forbidden"}, PermissionError, "Forbidden"),  # the API's answer to an invalid key
            (404, {"message": "Not Found"}, ObjectNotFoundException, "Not Found"),  # no "error" key
            (400, {"error": "offset + limit must be < 10000"}, BadQueryParametersException, "offset \\+ limit"),
            (422, {"error": "nope"}, S2APIError, "422"),
            (302, None, S2APIError, "302"),
        ],
        ids=["401", "403-gateway", "404-message", "400", "422", "302"],
    )
    async def test_error_statuses_raise(self, http, unthrottled, status, body, exc_type, message):
        http.return_value = _response(status, body)
        with pytest.raises(exc_type, match=message):
            await S2Requester(timeout=10, retry=True).request("http://test", {})
        assert http.await_count == 1

    @pytest.mark.asyncio
    async def test_non_json_error_body(self, http, unthrottled):
        http.return_value = httpx.Response(418, content=b"teapot", request=httpx.Request("GET", "http://test"))
        with pytest.raises(S2APIError, match="teapot"):
            await S2Requester(timeout=10, retry=False).request("http://test", {})

    @pytest.mark.asyncio
    async def test_non_paginated_response_unchanged(self, http, unthrottled):
        http.return_value = _response(200, {"paperId": "abc", "title": "T"})
        data = await S2Requester(timeout=10, retry=False).request("http://test", {})
        assert data == {"paperId": "abc", "title": "T"}

    @pytest.mark.asyncio
    async def test_recommendations_without_list_raise(self, http, unthrottled):
        http.return_value = _response(200, {"unexpected": True})
        with pytest.raises(S2APIError, match="recommendedPapers"):
            await S2Client(api_key="k").get_recommended_papers("p1", fields=["title"], limit=5)

    @pytest.mark.asyncio
    async def test_batch_without_list_raises(self, http, unthrottled):
        http.return_value = _response(200, {"data": []})
        with pytest.raises(S2APIError, match="expected a list"):
            await S2Client(api_key="k").get_papers(["p1"], fields=["title"])


class TestRequestShapes:
    @pytest.mark.asyncio
    async def test_query_is_passed_unencoded_for_httpx_to_encode(self, http, unthrottled):
        """Queries containing "+", "&" or "#" reach the API unchanged."""
        _server(http, lambda _p: _response(200, {"total": 0, "offset": 0}))
        await _drain(await S2Client(api_key="k").search_paper("C++ & R&D #1", fields=["title"], limit=5))
        assert http.call_args.kwargs["params"]["query"] == "C++ & R&D #1"

    @pytest.mark.asyncio
    async def test_query_survives_real_url_encoding(self):
        seen = []

        def handler(request):
            seen.append(request.url.params["query"])
            return httpx.Response(200, json={"total": 0, "offset": 0})

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with (
            patch("s2.httpx.AsyncClient", lambda *a, **kw: real_client(*a, transport=transport, **kw)),
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=0.0),
            patch("s2.Path.touch"),
        ):
            await _drain(await S2Client(api_key="k").search_paper("C++ & R&D", fields=["title"], limit=5))
        assert seen == ["C++ & R&D"]

    @pytest.mark.asyncio
    async def test_search_filters(self, http, unthrottled):
        _server(http, lambda _p: _response(200, {"total": 0, "offset": 0}))
        await _drain(
            await S2Client(api_key="k").search_paper(
                "q",
                fields=["title", "year"],
                limit=5,
                year="2020-",
                publication_date_or_year="2020-01:",
                publication_types=["Review", "JournalArticle"],
                open_access_pdf=True,
                venue=["Nature"],
                fields_of_study=["Physics", "Biology"],
                min_citation_count=10,
            )
        )
        assert http.call_args.args[1].endswith("/graph/v1/paper/search")
        assert http.call_args.kwargs["params"] == {
            "query": "q",
            "fields": "title,year",
            "year": "2020-",
            "publicationDateOrYear": "2020-01:",
            "publicationTypes": "Review,JournalArticle",
            "openAccessPdf": "",
            "venue": "Nature",
            "fieldsOfStudy": "Physics,Biology",
            "minCitationCount": 10,
            "offset": 0,
            "limit": 5,
        }

    @pytest.mark.asyncio
    async def test_match_title_sends_no_paging_params(self, http, unthrottled):
        http.return_value = _response(200, {"data": [{"paperId": "p1", "matchScore": 1.0}]})
        paper = await S2Client(api_key="k").match_paper_title("Attention", fields=["title"])
        assert paper == {"paperId": "p1", "matchScore": 1.0}
        assert http.call_args.args[1].endswith("/graph/v1/paper/search/match")
        assert "offset" not in http.call_args.kwargs["params"]
        assert "limit" not in http.call_args.kwargs["params"]

    @pytest.mark.asyncio
    async def test_match_title_without_data_is_not_found(self, http, unthrottled):
        http.return_value = _response(200, {"data": []})
        with pytest.raises(ObjectNotFoundException, match="Title match not found"):
            await S2Client(api_key="k").match_paper_title("x", fields=["title"])

    @pytest.mark.asyncio
    async def test_recommendations_from_lists_sends_arrays(self, http, unthrottled):
        http.return_value = _response(200, {"recommendedPapers": [{"paperId": "r1"}]})
        papers = await S2Client(api_key="k").get_recommended_papers_from_lists(["p1"], fields=["title"], limit=5)
        assert papers == [{"paperId": "r1"}]
        args, kwargs = http.call_args
        assert args[0] == "POST" and args[1].endswith("/recommendations/v1/papers/")
        assert kwargs["json"] == {"positivePaperIds": ["p1"], "negativePaperIds": []}
        assert kwargs["params"] == {"fields": "title", "limit": 5}

    @pytest.mark.asyncio
    async def test_recommendations_for_paper(self, http, unthrottled):
        http.return_value = _response(200, {"recommendedPapers": [{"paperId": "r1"}]})
        papers = await S2Client(api_key="k").get_recommended_papers("p1", fields=["title"], limit=5, pool_from="all-cs")
        assert papers == [{"paperId": "r1"}]
        assert http.call_args.args == ("GET", "https://api.semanticscholar.org/recommendations/v1/papers/forpaper/p1")
        assert http.call_args.kwargs["params"] == {"fields": "title", "limit": 5, "from": "all-cs"}


class TestS2Requester:
    @pytest.mark.asyncio
    async def test_throttles_requests(self, http, mock_sleep):
        with (
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=time.time() - 0.3),
            patch("s2.Path.touch"),
        ):
            await S2Requester(timeout=10, retry=False).request("http://test", "")
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
            await S2Requester(timeout=10, retry=False).request("http://test", "")
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_timestamp_marked_after_response(self, http, unthrottled):
        """The rate timestamp records when the response arrived, not when the request left."""
        order = []
        http.side_effect = lambda *a, **kw: order.append("request") or _response(200)
        unthrottled.touch.side_effect = lambda: order.append("touch")
        await S2Requester(timeout=10, retry=False).request("http://test", "")
        assert order == ["request", "touch"]

    @pytest.mark.asyncio
    async def test_timestamp_marked_when_request_fails(self, http, unthrottled):
        http.side_effect = httpx.ConnectTimeout("timed out")
        with pytest.raises(httpx.ConnectTimeout):
            await S2Requester(timeout=10, retry=True).request("http://test", "")
        unthrottled.touch.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("call", "body"),
        [
            (lambda c: c.get_paper_citations("p1", fields=["title"], limit=5), {"data": []}),
            (lambda c: c.get_paper_references("p1", fields=["title"], limit=5), {"data": []}),
            (lambda c: c.get_author_papers("a1", fields=["title"], limit=5), {"data": []}),
            (lambda c: c.search_paper("q", fields=["title"], limit=5), {"data": []}),
            (lambda c: c.match_paper_title("q", fields=["title"]), {"data": [{"paperId": "p"}]}),
            (lambda c: c.search_author("q", fields=["name"], limit=5), {"data": []}),
            (lambda c: c.get_papers(["p1"], fields=["title"]), [{"paperId": "p1"}]),
            (lambda c: c.get_recommended_papers("p1", fields=["title"], limit=5), {"recommendedPapers": []}),
            (
                lambda c: c.get_recommended_papers_from_lists(["p1"], fields=["title"], limit=5),
                {"recommendedPapers": []},
            ),
        ],
        ids=["citations", "references", "author-papers", "search", "match", "search-author", "batch", "recommend",
             "recommend-lists"],
    )
    async def test_client_sends_api_key_on_every_endpoint(self, http, unthrottled, call, body):
        http.return_value = _response(200, body)
        result = await call(S2Client(api_key="k"))
        if hasattr(result, "__aiter__"):
            [item async for item in result]
        assert http.await_count == 1
        assert http.call_args.kwargs["headers"]["x-api-key"] == "k"

    @pytest.mark.asyncio
    async def test_rate_limited_retries_go_through_throttle(self, http, unthrottled, mock_sleep):
        http.side_effect = [_response(429), _response(429), _response(200, {"data": "ok"})]
        result = await S2Requester(timeout=10, retry=True).request("http://test", "")
        assert result == {"data": "ok"}
        assert unthrottled.lock.call_count == 3
        assert unthrottled.touch.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_after_header_sets_wait(self, http, unthrottled, mock_sleep):
        http.side_effect = [_response(429, headers={"Retry-After": "7"}), _response(200)]
        await S2Requester(timeout=10, retry=True).request("http://test", "")
        mock_sleep.assert_called_once_with(7.0)

    @pytest.mark.asyncio
    async def test_backoff_without_retry_after_has_jitter(self, http, unthrottled, mock_sleep):
        http.side_effect = [_response(429), _response(200)]
        await S2Requester(timeout=10, retry=True).request("http://test", "")
        delay = mock_sleep.call_args[0][0]
        assert 1.0 <= delay <= 2.0

    @pytest.mark.asyncio
    async def test_rate_limited_exhausted(self, http, unthrottled, mock_sleep):
        http.return_value = _response(429)
        with pytest.raises(RetryError) as exc_info:
            await S2Requester(timeout=10, retry=True).request("http://test", "")
        assert isinstance(exc_info.value.last_attempt.exception(), RateLimitedError)
        assert http.await_count == RETRY_ATTEMPTS

    @pytest.mark.asyncio
    async def test_retry_false_makes_one_attempt(self, http, unthrottled, mock_sleep):
        http.return_value = _response(429)
        with pytest.raises(RetryError):
            await S2Requester(timeout=10, retry=False).request("http://test", "")
        assert http.await_count == 1

    @pytest.mark.asyncio
    async def test_server_error_retried(self, http, unthrottled, mock_sleep):
        http.side_effect = [_response(500, {"message": "boom"}), _response(200, {"data": "ok"})]
        result = await S2Requester(timeout=10, retry=True).request("http://test", "")
        assert result == {"data": "ok"}
        assert http.await_count == 2

    @pytest.mark.asyncio
    async def test_server_error_exhausted(self, http, unthrottled, mock_sleep):
        http.return_value = _response(503)
        with pytest.raises(RetryError) as exc_info:
            await S2Requester(timeout=10, retry=True).request("http://test", "")
        assert isinstance(exc_info.value.last_attempt.exception(), ServerErrorException)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "exc_type"),
        [(400, BadQueryParametersException), (403, PermissionError), (404, ObjectNotFoundException)],
    )
    async def test_client_errors_not_retried(self, http, unthrottled, status, exc_type):
        http.return_value = _response(status, {"error": "bad"})
        with pytest.raises(exc_type):
            await S2Requester(timeout=10, retry=True).request("http://test", "")
        assert http.await_count == 1

    @pytest.mark.asyncio
    async def test_error_only_body_raises(self, http, unthrottled):
        """A 200 whose body is only an error message is an error, not empty data."""
        http.return_value = _response(200, {"error": "no match"})
        with pytest.raises(S2APIError, match="no match"):
            await S2Requester(timeout=10, retry=False).request("http://test", "")

    @pytest.mark.asyncio
    async def test_payload_sent_as_post(self, http, unthrottled):
        await S2Requester(timeout=10, retry=False).request("http://test", {"fields": "title"}, {"ids": ["p1"]})
        args, kwargs = http.call_args
        assert args[0] == "POST"
        assert kwargs["params"] == {"fields": "title"}
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
            await asyncio.gather(*[requester.request("http://test", "") for _ in range(3)])

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
                        await s2.S2Requester(10, False).request("http://test", "")

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
    @pytest.mark.parametrize(
        ("message", "tip"),
        [("Unrecognized or unsupported fields: [bogus]", True), ("No valid paper ids given", False)],
        ids=["field-error", "id-error"],
    )
    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_bad_query_parameters_prints_stderr(self, mock_cmd, capsys, message, tip):
        """The field-names tip appears only when the API rejected fields."""
        mock_cmd.side_effect = BadQueryParametersException(message)

        with patch("sys.argv", ["s2", "search", "test"]):
            main()  # should NOT raise SystemExit

        stderr = capsys.readouterr().err
        assert message in stderr
        assert ("s2 fields" in stderr) is tip

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
        attempt.exception.return_value = ServerErrorException("500")
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
        exc = self._make_retry_error(ServerErrorException("500"))
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

    @pytest.mark.parametrize(
        ("argv", "attr"),
        [
            (["search", "q"], "limit"),
            (["search-author", "q"], "limit"),
            (["citations", "-i", "p1"], "limit"),
            (["references", "-i", "p1"], "limit"),
            (["recommend", "-i", "p1"], "limit"),
            (["author-papers", "-i", "a1"], "limit"),
        ],
        ids=["search", "search-author", "citations", "references", "recommend", "author-papers"],
    )
    def test_result_caps_default_to_none(self, argv, attr):
        """Without -n a command returns everything its endpoint allows."""
        command = argv[0].replace("-", "_")
        with patch(f"s2.cmd_{command}", new_callable=AsyncMock) as mock_cmd, patch("sys.argv", ["s2", *argv]):
            main()
        assert getattr(mock_cmd.call_args[0][0], attr) is None

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

    def test_recommend_pool_rejects_invalid(self):
        with patch("sys.argv", ["s2", "recommend", "-i", "s1", "--pool", "invalid"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    @patch("s2.cmd_search", new_callable=AsyncMock)
    def test_search_parses_all_filters(self, mock_cmd):
        argv = ["s2", "search", "q", "-y", "2020-", "-d", "2020-01:", "-t", "Review", "--open-access",
                "--venue", "Nature", "--fields-of-study", "Physics", "--min-citations", "5", "--match-title"]
        with patch("sys.argv", argv):
            main()
        args = mock_cmd.call_args[0][0]
        assert (args.year, args.publication_date, args.publication_types, args.open_access) == ("2020-", "2020-01:", "Review", True)
        assert (args.venue, args.fields_of_study, args.min_citations, args.match_title) == ("Nature", "Physics", 5, True)

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
    async def test_custom_fields(self, mock_client):
        mock_client.get_author_papers.return_value = async_iter([make_paper({"title": "X"})])

        await cmd_author_papers(make_args(ids=["auth1"], fields="title,year", limit=5))

        mock_client.get_author_papers.assert_called_once_with("auth1", fields=["title", "year"], limit=5)


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


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
ARXIV_PDF = {"https://arxiv.org/pdf/2604.00001": (200, b"%PDF-1.7 body")}


class TestFetch:
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

    def _setup(self, mock_client, paper=ARXIV_PAPER, not_found=()):
        mock_client.get_papers.return_value = ([make_paper(paper)], list(not_found))
        mock_client.get_paper_citations.return_value = async_iter([])

    async def _read(self, routes, calls=None, ids=("ArXiv:2604.00001",), **kwargs):
        with patch("s2._http_client", _http(routes, calls)):
            await cmd_read(make_args(ids=list(ids), **kwargs))

    @pytest.mark.asyncio
    async def test_saves_arxiv_pdf(self, mock_client, capsys):
        self._setup(mock_client)
        await self._read(ARXIV_PDF)
        out = json.loads(capsys.readouterr().out)
        assert Path(out["pdfPath"]) == self.cache / "p1" / "paper.pdf"
        assert Path(out["pdfPath"]).read_bytes() == b"%PDF-1.7 body"
        assert set(out) == {"paperId", "title", "year", "pdfPath", "citationCount", "citationsInRange", "note"}

    @pytest.mark.asyncio
    async def test_note_tells_reader_to_read_first_page_to_last(self, mock_client, capsys):
        self._setup(mock_client)
        await self._read(ARXIV_PDF)  # fresh read
        await self._read(ARXIV_PDF)  # served from the cache
        fresh, cached = (json.loads(line) for line in capsys.readouterr().out.splitlines())
        assert fresh["note"] == cached["note"] == READ_NOTE
        assert "first page to the last" in READ_NOTE and "Read tool" in READ_NOTE

    @pytest.mark.asyncio
    async def test_note_is_null_without_a_pdf(self, mock_client, capsys):
        self._setup(mock_client, paper={"paperId": "p9", "title": "Lost", "externalIds": {}})
        await self._read({})
        assert json.loads(capsys.readouterr().out)["note"] is None

    @pytest.mark.asyncio
    async def test_open_access_pdf_without_arxiv(self, mock_client, capsys):
        self._setup(mock_client, paper={"paperId": "p2", "openAccessPdf": {"url": "https://example.org/a.pdf"}})
        await self._read({"https://example.org/a.pdf": (200, b"%PDF-1.4")}, ids=["DOI:10.1/x"])
        assert Path(json.loads(capsys.readouterr().out)["pdfPath"]).read_bytes() == b"%PDF-1.4"

    @pytest.mark.asyncio
    async def test_open_access_used_when_arxiv_pdf_missing(self, mock_client, capsys):
        paper = {**ARXIV_PAPER, "openAccessPdf": {"url": "https://example.org/a.pdf"}}
        self._setup(mock_client, paper=paper)
        await self._read({"https://example.org/a.pdf": (200, b"%PDF-1.4")})
        assert Path(json.loads(capsys.readouterr().out)["pdfPath"]).read_bytes() == b"%PDF-1.4"

    @pytest.mark.asyncio
    async def test_landing_page_is_not_a_pdf(self, mock_client, capsys):
        self._setup(mock_client, paper={"paperId": "p2", "title": "Lost", "openAccessPdf": {"url": "https://example.org/landing"}})
        await self._read({"https://example.org/landing": (200, b"<html>landing</html>")}, ids=["DOI:10.1/x"])
        captured = capsys.readouterr()
        assert json.loads(captured.out)["pdfPath"] is None
        assert "no PDF found" in captured.err and "'Lost'" in captured.err

    @pytest.mark.asyncio
    async def test_repeat_read_within_a_day_makes_no_requests(self, mock_client, capsys):
        self._setup(mock_client)
        await self._read(ARXIV_PDF)
        mock_client.get_papers.reset_mock()
        calls = []
        await self._read(ARXIV_PDF, calls)
        first, second = (json.loads(line) for line in capsys.readouterr().out.splitlines())
        assert first == second
        assert calls == [] and mock_client.get_papers.call_count == 0

    @pytest.mark.asyncio
    async def test_read_older_than_a_day_is_refreshed(self, mock_client, capsys):
        self._setup(mock_client)
        await self._read(ARXIV_PDF)
        with patch("s2.time.time", return_value=time.time() + READ_CACHE_SECONDS + 1):
            mock_client.get_papers.reset_mock()
            self._setup(mock_client, paper={**ARXIV_PAPER, "citationCount": 4})
            calls = []
            await self._read(ARXIV_PDF, calls)
        first, second = (json.loads(line) for line in capsys.readouterr().out.splitlines())
        assert (first["citationCount"], second["citationCount"]) == (3, 4)
        assert mock_client.get_papers.call_count == 1 and calls == []  # the PDF itself stays cached

    @pytest.mark.asyncio
    async def test_cache_is_per_year_range(self, mock_client, capsys):
        self._setup(mock_client)
        await self._read(ARXIV_PDF)
        mock_client.get_papers.reset_mock()
        self._setup(mock_client)
        await self._read(ARXIV_PDF, year="2020")
        assert mock_client.get_papers.call_count == 1

    @pytest.mark.asyncio
    async def test_failed_read_is_not_cached(self, mock_client, capsys):
        self._setup(mock_client, paper={"paperId": "p9", "title": "Lost", "externalIds": {}})
        await self._read({})
        mock_client.get_papers.reset_mock()
        await self._read({})
        assert mock_client.get_papers.call_count == 1

    @pytest.mark.asyncio
    async def test_year_counts_citations_in_range(self, mock_client, capsys):
        self._setup(mock_client)
        mock_client.get_paper_citations.return_value = async_iter([make_citation({}) for _ in range(4)])
        await self._read(ARXIV_PDF, year="2018-2020")
        out = json.loads(capsys.readouterr().out)
        assert out["citationsInRange"] == 4
        mock_client.get_paper_citations.assert_called_once_with(
            "p1", fields=["paperId"], limit=1000, publication_date_or_year="2018:2020"
        )

    @pytest.mark.asyncio
    async def test_reads_ids_from_piped_search_output(self, mock_client):
        self._setup(mock_client)
        piped = io.StringIO('{"paperId": "p1", "title": "A"}\n{"paperId": "p2", "title": "B"}\n')
        with patch("sys.stdin", piped), patch("s2._http_client", _http({})):
            await cmd_read(make_args(ids=None))
        assert mock_client.get_papers.call_args.args[0] == ["p1", "p2"]

    @pytest.mark.asyncio
    async def test_not_found_ids_reported(self, mock_client, capsys):
        mock_client.get_papers.return_value = ([], ["ArXiv:9999.99999"])
        with patch("s2._http_client", _http({})):
            await cmd_read(make_args(ids=["ArXiv:9999.99999"]))
        assert "error: not found: ArXiv:9999.99999" in capsys.readouterr().err

    def test_rejects_date_for_year(self, capsys):
        with patch("sys.argv", ["s2", "read", "-i", "p1", "-y", "2026-06-01"]), pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
