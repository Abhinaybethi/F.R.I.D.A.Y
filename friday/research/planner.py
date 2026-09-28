"""
ResearchPlanner — deterministic search-query generation.

Turns one original user query into a small set (1–3) of concrete search
queries. Technical questions get official-source variants; news/current-info
queries get a freshened variant. Never emits dozens of queries.
"""
from typing import List

from friday.research.models import QueryType

_FRESH_WORDS = ("latest", "recent", "today", "current", "now", "this week")


class ResearchPlanner:
    def __init__(self, max_queries: int = 3):
        self.max_queries = max(1, min(5, int(max_queries)))

    def plan(self, original_query: str, query_type: QueryType) -> List[str]:
        """Generate 1–3 deduplicated search queries for *original_query*."""
        base = (original_query or "").strip()
        if not base:
            return []
        base = base.rstrip("?.! ")
        queries = [base]
        variants: List[str] = []

        if query_type in (
            QueryType.NEWS,
            QueryType.CURRENT_INFORMATION,
            QueryType.TIME_SENSITIVE,
        ):
            if not any(w in base.lower() for w in _FRESH_WORDS):
                variants.append(f"{base} latest")
        if query_type == QueryType.TECHNICAL_DOCUMENTATION:
            variants.append(f"{base} official documentation")
            variants.append(f"{base} release notes")
        if query_type == QueryType.FACT_CHECK:
            variants.append(f"{base} official source")
        if query_type == QueryType.COMPARISON:
            variants.append(f"{base} comparison")
        if query_type == QueryType.RECOMMENDATION:
            variants.append(f"{base} top rated")

        for v in variants:
            if v.lower() not in (q.lower() for q in queries):
                queries.append(v)
        return queries[: self.max_queries]


__all__ = ["ResearchPlanner"]