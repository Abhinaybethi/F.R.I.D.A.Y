"""Provider-independent search interface."""
from friday.research.search.base import SearchError, SearchProvider
from friday.research.search.ddg_provider import DuckDuckGoSearchProvider

__all__ = ["DuckDuckGoSearchProvider", "SearchError", "SearchProvider"]