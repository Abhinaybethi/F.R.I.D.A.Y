"""
UNIT — search layer (Phase 2): URL canonicalization, dedupe, provider wiring
and failure mapping. No live network: the DDG client is stubbed via
monkeypatch.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.research.models import SearchResult
from friday.research.search.base import SearchError, canonicalize_url, dedupe_results
from friday.research.search.ddg_provider import _map_exception


# ---------------------------------------------------------------------------
# canonicalize_url
# ---------------------------------------------------------------------------

def test_canonicalize_strips_tracking_params():
    url = ("https://example.com/news?utm_medium=email&utm_source=x&id=42&fbclid=abc")
    assert canonicalize_url(url) == "https://example.com/news?id=42"


def test_canonicalize_strips_fragment_and_trailing_slash():
    assert canonicalize_url("https://example.com/page/#section") == "https://example.com/page"


def test_canonicalize_keeps_trailing_slash_for_root():
    assert canonicalize_url("https://example.com") == "https://example.com/"


def test_canonicalize_requires_known_scheme():
    # Non-http(s) URLs are returned unchanged at this layer; strict blocking
    # of dangerous schemes is enforced by the caller's SSRF defense.
    assert canonicalize_url("ftp://example.com/file") == "ftp://example.com/file"


@pytest.mark.parametrize("candidate", [
    "javascript:alert(1)",
    "data:text/html,<script>",
    "file:///etc/passwd",
    "not a url",
    "",
])
def test_canonicalize_leaves_unsupported_inputs_unchanged(candidate):
    assert canonicalize_url(candidate) == candidate


def test_canonicalize_defaults_path_to_root():
    assert canonicalize_url("https://example.com") == "https://example.com/"


# ---------------------------------------------------------------------------
# dedupe_results
# ---------------------------------------------------------------------------

def _result(title, url, rank=0):
    return SearchResult(title=title, url=url, snippet="", source="ddg", rank=rank)


def test_dedupe_by_canonical_url_keeps_first():
    a = SearchResult(title="A", url="https://ex.com/x?utm_medium=email", snippet="", source="ddg", rank=1)
    b = SearchResult(title="B", url="https://ex.com/x", snippet="", source="ddg", rank=2)
    out = dedupe_results([a, b])
    assert len(out) == 1
    assert out[0].title == "A"  # first wins


def test_dedupe_preserves_order_and_limits():
    results = [_result(f"r{i}", f"https://ex.com/{i}", rank=i) for i in range(10)]
    out = dedupe_results(results, max_results=3)
    assert [r.rank for r in out] == [0, 1, 2]


def test_dedupe_tolerates_empty():
    assert dedupe_results([]) == []


# ---------------------------------------------------------------------------
# duckduckgo provider — failure mapping
# ---------------------------------------------------------------------------

def test_map_ratelimit_exception():
    from duckduckgo_search.exceptions import RatelimitException

    mapped = _map_exception(RatelimitException("ratelimit"), "ddg")
    assert isinstance(mapped, SearchError)
    assert mapped.retryable is True
    assert mapped.error_type == "rate_limit"


def test_map_timeout_exception():
    from duckduckgo_search.exceptions import TimeoutException

    mapped = _map_exception(TimeoutException("timeout"), "ddg")
    assert mapped.retryable is True
    assert mapped.error_type == "timeout"


def test_map_connection_exception_is_retryable():
    mapped = _map_exception(ConnectionError("socket closed"), "ddg")
    assert mapped.retryable is True
    assert mapped.error_type == "network"


def test_map_unknown_exception_is_not_retryable():
    mapped = _map_exception(RuntimeError("boom"), "ddg")
    assert mapped.retryable is False
    assert mapped.error_type == "provider_error"
    assert mapped.provider == "ddg"


class _BoomClient:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, query, **kwargs):
        raise RuntimeError("network is down")


class _EmptyClient(_BoomClient):
    def text(self, query, **kwargs):
        return []


def test_provider_wraps_client_errors(monkeypatch):
    from friday.research.search.ddg_provider import DuckDuckGoSearchProvider
    import friday.research.search.ddg_provider as mod

    monkeypatch.setattr(mod, "_load_ddgs_client", lambda: _BoomClient)
    provider = DuckDuckGoSearchProvider(api_key="")
    with pytest.raises(SearchError) as exc_info:
        provider.search("things", max_results=5, timeout=10, freshness=None)
    assert exc_info.value.error_type == "provider_error"
    assert exc_info.value.retryable is False


def test_provider_maps_empty_to_results(monkeypatch):
    from friday.research.search.ddg_provider import DuckDuckGoSearchProvider
    import friday.research.search.ddg_provider as mod

    monkeypatch.setattr(mod, "_load_ddgs_client", lambda: _EmptyClient)
    provider = DuckDuckGoSearchProvider(api_key="")
    assert provider.search("nothing here", max_results=5, timeout=10) == []


def test_provider_normalizes_items(monkeypatch):
    from friday.research.search.ddg_provider import DuckDuckGoSearchProvider
    import friday.research.search.ddg_provider as mod

    class RichClient(_BoomClient):
        def text(self, query, **kwargs):
            return [
                {"title": "Python 3.13 Released", "href": "https://python.org/3.13",
                 "body": "Announcement details."},
                {"title": "No Link Item", "href": "", "body": "should be skipped"},
            ]

    monkeypatch.setattr(mod, "_load_ddgs_client", lambda: RichClient)
    provider = DuckDuckGoSearchProvider(api_key="")
    results = provider.search("python", max_results=5, timeout=10)
    assert len(results) == 1
    assert results[0].title == "Python 3.13 Released"
    assert results[0].url == "https://python.org/3.13"
    assert results[0].source == "duckduckgo"
    assert results[0].rank == 1


def test_load_ddgs_client_smoke():
    import friday.research.search.ddg_provider as mod

    assert mod._load_ddgs_client() is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])