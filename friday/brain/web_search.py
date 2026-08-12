"""
Free, unlimited web search using the `duckduckgo-search` package - no API
key required. This is how Friday stays grounded in live internet
information without needing any expensive "training" of her own.
"""
from duckduckgo_search import DDGS

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class WebSearch:
    def search(self, query: str, max_results: int = 3):
        results = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "summary": r.get("body", ""),
                        "url": r.get("href", ""),
                    })
        except Exception as e:
            logger.warning("Web search failed: %s", e)
        return results
