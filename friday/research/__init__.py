"""
Research subsystem — Phase 1 + Phase 2.

A modular, provider-independent web-research foundation:

    ResearchRouter   deterministic decide(needs_web / query_type / queries)
    ResearchPlanner  generates 1–3 search queries per original user query
    SearchProvider   provider-independent search abstraction
    DuckDuckGoSearchProvider  first concrete provider (no API key)
    ResearchAgent    orchestrates decide -> plan -> search -> ResearchResponse

Later phases add page fetching, browser navigation, extraction, RAG and
cross-source verification. Nothing in this package synthesizes a final answer.
"""
from friday.research.agent import ResearchAgent
from friday.research.config import ResearchConfig
from friday.research.models import (
    QueryType,
    ResearchDecision,
    ResearchResponse,
    SearchFailure,
    SearchResult,
)
from friday.research.planner import ResearchPlanner
from friday.research.router import ResearchRouter
from friday.research.search.base import SearchProvider
from friday.research.search.ddg_provider import DuckDuckGoSearchProvider

__all__ = [
    "DuckDuckGoSearchProvider",
    "QueryType",
    "ResearchAgent",
    "ResearchConfig",
    "ResearchDecision",
    "ResearchPlanner",
    "ResearchResponse",
    "ResearchRouter",
    "SearchFailure",
    "SearchProvider",
    "SearchResult",
]