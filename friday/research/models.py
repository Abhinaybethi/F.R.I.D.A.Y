"""
Typed models for the research subsystem.

The project uses plain dataclasses (no Pydantic dependency), so every object
in this package is a dataclass with explicit defaults — safe to construct in
tests and fully serialisable.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class QueryType(Enum):
    """Semantic class of a researched query."""

    GENERAL_KNOWLEDGE = "GENERAL_KNOWLEDGE"
    CURRENT_INFORMATION = "CURRENT_INFORMATION"
    NEWS = "NEWS"
    TECHNICAL_DOCUMENTATION = "TECHNICAL_DOCUMENTATION"
    FACT_CHECK = "FACT_CHECK"
    COMPARISON = "COMPARISON"
    RECOMMENDATION = "RECOMMENDATION"
    LOCAL_INFORMATION = "LOCAL_INFORMATION"
    TIME_SENSITIVE = "TIME_SENSITIVE"
    UNKNOWN = "UNKNOWN"


def _utc_aware(value: Optional[datetime]) -> Optional[datetime]:
    """Coerce *value* to a timezone-aware datetime (UTC) or return None."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class SearchResult:
    """A single, provider-normalized search result."""

    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = ""
    published_at: Optional[datetime] = None
    rank: int = 0

    def __post_init__(self):
        self.published_at = _utc_aware(self.published_at)


@dataclass
class SearchFailure:
    """Structured failure from a search provider. Never fabricated results."""

    provider: str = ""
    error_type: str = ""
    message: str = ""
    retryable: bool = False


@dataclass
class ResearchDecision:
    """Outcome of ``ResearchRouter.decide``."""

    needs_web: bool = False
    reason: str = ""
    query_type: str = QueryType.UNKNOWN.value
    confidence: float = 0.0
    search_queries: list = field(default_factory=list)
    explicit_request: bool = False


@dataclass
class ResearchResponse:
    """Structured payload consumed by later research phases."""

    original_query: str = ""
    search_queries: list = field(default_factory=list)
    results: list = field(default_factory=list)
    provider: str = ""
    elapsed_ms: float = 0.0
    success: bool = False
    needs_web: bool = False
    query_type: str = QueryType.UNKNOWN.value
    error: Optional[SearchFailure] = None