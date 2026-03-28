"""Tests for scripts/s2.py."""

import asyncio
import io
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from conftest import async_iter, make_args, make_citation, make_paper
from s2 import (
    AUTHOR_SCAN_FIELDS,
    DETAIL_FIELDS,
    FIELDS_HELP,
    RETRY_EXCEPTIONS,
    RETRY_WAIT,
    SCAN_FIELDS,
    S2Requester,
    _describe_error,
    cmd_author_papers,
    cmd_citations,
    cmd_fields,
    cmd_get,
    cmd_recommend,
    cmd_references,
    cmd_search,
    cmd_search_author,
    main,
    make_client,
    output,
    read_ids,
)
from semanticscholar.SemanticScholarException import (
    InternalServerErrorException,
    ObjectNotFoundException,
)
from tenacity import RetryError, stop_after_attempt

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
    def test_without_api_key(self):
        with patch("s2.Path.read_text", side_effect=FileNotFoundError):
            client = make_client()
        assert client.auth_header == {}


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


class TestS2Requester:
    @staticmethod
    def _make_requester(retry):
        """Create an S2Requester with a mocked _get_data_async."""
        requester = S2Requester(timeout=10, retry=retry)
        mock_retrying = AsyncMock(return_value={"data": "test"})
        requester._get_data_async = MagicMock()
        requester._get_data_async.retry_with.return_value = mock_retrying
        return requester

    @pytest.mark.asyncio
    async def test_throttles_requests(self):
        requester = self._make_requester(retry=False)

        with (
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=time.time() - 0.3),
            patch("s2.Path.touch"),
            patch("s2.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            await requester.get_data_async("http://test", {}, {})
            mock_sleep.assert_called_once()
            delay = mock_sleep.call_args[0][0]
            assert 0.0 < delay <= 1.1

    @pytest.mark.asyncio
    async def test_no_sleep_when_enough_time_passed(self):
        requester = self._make_requester(retry=False)

        with (
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=time.time() - 2.0),
            patch("s2.Path.touch"),
            patch("s2.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            await requester.get_data_async("http://test", {}, {})
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_true_uses_exponential_wait(self):
        requester = self._make_requester(retry=True)

        with (
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=time.time() - 2.0),
            patch("s2.Path.touch"),
        ):
            await requester.get_data_async("http://test", {}, {})

        call_kwargs = requester._get_data_async.retry_with.call_args[1]
        assert call_kwargs["retry"] is RETRY_EXCEPTIONS
        assert call_kwargs["wait"] is RETRY_WAIT
        assert isinstance(call_kwargs["stop"], stop_after_attempt)
        assert call_kwargs["stop"].max_attempt_number == 4

    @pytest.mark.asyncio
    async def test_retry_false_uses_stop_after_attempt(self):
        requester = self._make_requester(retry=False)

        with (
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=time.time() - 2.0),
            patch("s2.Path.touch"),
        ):
            await requester.get_data_async("http://test", {}, {})

        call_kwargs = requester._get_data_async.retry_with.call_args[1]
        assert isinstance(call_kwargs["stop"], stop_after_attempt)
        assert call_kwargs["stop"].max_attempt_number == 1

    @pytest.mark.asyncio
    async def test_concurrent_requests_are_serialized(self, tmp_path):
        """asyncio.gather through the real file lock spaces requests ~1.1s apart."""
        lock_file = str(tmp_path / "s2_rate.lock")
        ts_file = str(tmp_path / "s2_rate.ts")
        timestamps = []

        requester = self._make_requester(retry=False)
        real_get = requester.get_data_async

        async def recording_get(*a, **kw):
            result = await real_get(*a, **kw)
            timestamps.append(time.monotonic())
            return result

        with patch("s2._RATE_LOCK", lock_file), patch("s2._RATE_TS", ts_file):
            await asyncio.gather(*[recording_get("http://test", {}, {}) for _ in range(3)])

        assert len(timestamps) == 3
        for i in range(1, len(timestamps)):
            gap = timestamps[i] - timestamps[i - 1]
            assert gap >= 1.0, f"gap between request {i - 1} and {i} was {gap:.3f}s, expected >= 1.0s"

    @pytest.mark.asyncio
    async def test_server_error_retried(self):
        """InternalServerErrorException is retried and succeeds on second attempt."""
        requester = S2Requester(timeout=10, retry=True)
        call_count = 0

        async def flaky(*args, **kwargs):  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise InternalServerErrorException("500 Internal Server Error")
            return {"data": "ok"}

        with (
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=0.0),
            patch("s2.Path.touch"),
            patch.object(type(requester), "_get_data_async", create=True),
        ):
            # Replace the real tenacity-wrapped method with our flaky function,
            # configured with the same retry settings used in production.
            from tenacity import retry

            requester._get_data_async = retry(
                retry=RETRY_EXCEPTIONS,
                wait=RETRY_WAIT,
                stop=stop_after_attempt(4),
            )(flaky)
            result = await requester.get_data_async("http://test", {}, {})

        assert call_count == 2
        assert result == {"data": "ok"}

    @pytest.mark.asyncio
    async def test_server_error_exhausted(self):
        """InternalServerErrorException raised 4 times → RetryError."""
        requester = S2Requester(timeout=10, retry=True)

        async def always_500(*args, **kwargs):  # noqa: ARG001
            raise InternalServerErrorException("500 Internal Server Error")

        with (
            patch("s2.AsyncFileLock", return_value=AsyncMock()),
            patch("s2.os.path.getmtime", return_value=0.0),
            patch("s2.Path.touch"),
            patch.object(type(requester), "_get_data_async", create=True),
        ):
            from tenacity import retry

            requester._get_data_async = retry(
                retry=RETRY_EXCEPTIONS,
                wait=RETRY_WAIT,
                stop=stop_after_attempt(4),
            )(always_500)
            with pytest.raises(RetryError):
                await requester.get_data_async("http://test", {}, {})


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
