"""Shared fixtures and helpers for research-assistant tests."""

import argparse
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


# ---------------------------------------------------------------------------
# Helper functions (import these directly in test files)
# ---------------------------------------------------------------------------


def make_args(**kwargs):
    """Build a namespace mimicking argparse output."""
    defaults = {
        "fields": None,
        "limit": 10,
        "ids": None,
        "command": "test",
        "year": None,
        "publication_date": None,
        "publication_types": None,
        "open_access": False,
        "venue": None,
        "fields_of_study": None,
        "min_citations": None,
        "match_title": False,
        "negative_ids": None,
        "pool": "recent",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def make_paper(data):
    """Create a mock paper object with raw_data."""
    return SimpleNamespace(raw_data=data)


def make_citation(data, has_paper=True):
    """Create a mock citation/reference with a nested paper object.

    When has_paper=True, the .paper attr is a SimpleNamespace (truthy, like a
    real Paper).  When False, .paper is None (as when the API omits the nested
    paper object).
    """
    paper = SimpleNamespace(raw_data=data) if has_paper else None
    return SimpleNamespace(paper=paper, raw_data=data)


def tty_stdin():
    """Return a mock stdin that reports isatty()=True (avoids pytest capture OSError)."""
    mock = MagicMock()
    mock.isatty.return_value = True
    return mock


async def async_iter(items):
    """Async generator from a list — drop-in replacement for async iterators."""
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Provide a fresh AsyncMock S2 client and patch make_client to return it."""
    from unittest.mock import AsyncMock

    client = AsyncMock()
    with patch("s2.make_client", return_value=client):
        yield client


@pytest.fixture(autouse=True)
def _fake_stdin():
    """Patch sys.stdin to a tty mock globally (avoids pytest stdin capture OSError)."""
    with patch("sys.stdin", tty_stdin()):
        yield
