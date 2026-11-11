"""
Free, unlimited web search using the `duckduckgo-search` package - no API
key required. This is how Friday stays grounded in live internet
information without needing any expensive "training" of her own.

Result items carry a relevance score so the caller can rank or filter.
"""
from duckduckgo_search import DDGS
from typing import List, TypedDict, Optional

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class SearchResult(TypedDict):
    title: str
    url: str
    summary: str
    rank: int


class WebSearch:
    def search(self, query: str, max_results: int = 3) -> List[SearchResult]:
        """Return up to *max_results* grounded DDG results.

        Each result carries ``title``, ``url``, ``summary`` and a simple
        ``rank`` (1 = most relevant the API returned).  Empty list means
        nothing was found – callers should treat that as "no answer" rather
        than an error.
        """
        if not query or not query.strip():
            logger.warning("Web search called with empty query")
            return []

        results: List[SearchResult] = []
        try:
            with DDGS() as ddgs:
                for idx, r in enumerate(ddgs.text(query, max_results=max_results), start=1):
                    title = r.get("title") or ""
                    body = r.get("body") or ""
                    href = r.get("href") or ""
                    # Normalise: skip results with no URL or empty title
                    if not href or not title.strip():
                        continue
                    results.append(SearchResult(
                        title=title,
                        url=href,
                        summary=body,
                        rank=idx,
                    ))
        except Exception as e:
            logger.warning("Web search failed: %s", e)
        return results
