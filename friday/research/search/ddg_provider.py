"""
DuckDuckGoSearchProvider — first concrete provider.

Uses the exact DuckDuckGo client the project already depends on
(``duckduckgo-search`` with a ``ddgs`` fallback), so no new network dependency
and no API key. All provider output is normalized into :class:`SearchResult`.
"""
import re
from typing import List, Optional

from friday.research.models import SearchResult
from friday.research.search.base import SearchError, SearchProvider, _render_datetime
from friday.utils.logger import get_logger

logger = get_logger(__name__)

_NEWSY = re.compile(
    r"\b(latest|breaking|most\s+recent|recent|now|today|tonight|"
    r"this\s+week|current|updates?|news)\b", re.IGNORECASE,
)


def _load_ddgs_client():
    """Import the DuckDuckGo client, trying modern then legacy package names."""
    try:
        from ddgs import DDGS  # newer metapackage
    except ImportError:
        from duckduckgo_search import DDGS  # legacy package (project default)
    return DDGS


def _map_exception(exc: Exception, provider: str) -> SearchError:
    """Map low-level provider exceptions to structured :class:`SearchError`."""
    module = type(exc).__module__ or ""
    name = type(exc).__name__.lower()
    message = str(exc) or type(exc).__name__

    if isinstance(exc, TimeoutError) or "timeout" in name:
        return SearchError(message, error_type="timeout", retryable=True, provider=provider)
    if "ratelimit" in name or "rate_limit" in name or "429" in message:
        return SearchError(message, error_type="rate_limit", retryable=True, provider=provider)
    if "no results" in message.lower() or "nodie" in name:
        return SearchError(message, error_type="empty_results", retryable=False, provider=provider)
    if "connection" in name or "socket" in module or "network" in name:
        return SearchError(message, error_type="network", retryable=True, provider=provider)
    if "parse" in name or "decode" in name:
        return SearchError(message, error_type="parse", retryable=False, provider=provider)
    return SearchError(message, error_type="provider_error", retryable=False, provider=provider)


class DuckDuckGoSearchProvider(SearchProvider):
    """DuckDuckGo text search, normalized into :class:`SearchResult` objects."""

    name = "duckduckgo"
    requires_api_key = False

    def __init__(self, api_key: str = "", region: str = "wt-wt", safesearch: str = "moderate"):
        self.api_key = api_key
        self.region = region
        self.safesearch = safesearch

    def _timelimit(self, freshness: Optional[str]) -> Optional[str]:
        if freshness:
            mapping = {"day": "d", "week": "w", "month": "m"}
            return mapping.get(freshness.lower())
        return None

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        timeout: float = 10.0,
        freshness: Optional[str] = None,
    ) -> List[SearchResult]:
        if not query or not query.strip():
            raise SearchError("empty search query", error_type="empty_query",
                              provider=self.name)
        max_results = max(1, min(20, int(max_results)))

        results: List[SearchResult] = []
        timelimit = self._timelimit(freshness)
        DDGS = _load_ddgs_client()

        try:
            with DDGS() as ddgs:
                try:
                    raw_items = ddgs.text(
                        query,
                        region=self.region,
                        safesearch=self.safesearch,
                        timelimit=timelimit,
                        max_results=max_results,
                    )
                except TypeError:
                    # Older duckduckgo_search signatures lack `timelimit`.
                    raw_items = ddgs.text(
                        query, region=self.region, safesearch=self.safesearch,
                        max_results=max_results,
                    )
        except SearchError:
            raise
        except Exception as exc:  # noqa: BLE001 - structured failure contract
            raise _map_exception(exc, self.name) from exc

        for idx, item in enumerate(raw_items or [], start=1):
            if not isinstance(item, dict):
                raise SearchError(
                    "provider returned malformed result", error_type="parse",
                    retryable=False, provider=self.name,
                )
            title = (item.get("title") or "").strip()
            url = (item.get("href") or item.get("url") or "").strip()
            snippet = (item.get("body") or item.get("snippet") or "").strip()
            if not url:
                continue
            results.append(SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                source=self.name,
                published_at=_render_datetime(item.get("date")),
                rank=idx,
            ))
        return results


__all__ = ["DuckDuckGoSearchProvider"]