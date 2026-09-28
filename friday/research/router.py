"""
ResearchRouter — deterministic Phase 1 routing.

Decides whether a query needs live web research, and if so then *what kind*
of research and *which* concrete search queries to run.

The router is deliberately heuristic (regex signals + lightweight keyword
classification) so no expensive LLM call is required just to decide whether to
search. An optional ``classify`` callable can be injected later — when the
heuristics are ambiguous about a query type — without changing the interface.
"""
import re
from typing import Callable, Optional

from friday.research.models import QueryType, ResearchDecision

# Explicit research requests: the user says so directly.
_EXPLICIT_REQUEST = re.compile(
    r"\b(search\s+(?:the\s+)?(?:web|internet|online)|"
    r"search\s+for|look\s+(?:it\s+)?up\b|look\s+this\s+up\b|"
    r"research\s+(?:this|it)|find\s+current\s+information|"
    r"check\s+the\s+latest|browse\s+(?:the\s+)?(?:web|internet)|"
    r"google\s+it|search\s+online|find\s+online)\b",
    re.IGNORECASE,
)

# Framing verbs removed from an explicit search request to recover the
# underlying subject ("search the web for React 20 changes" -> "React 20
# changes").
_EXPLICIT_STRIP = re.compile(
    r"^(?:please\s+)?(?:can\s+you\s+)?(?:search|look|research|browse|google|find)"
    r"(?:\s+(?:the\s+)?(?:web|internet|online|it|this|up))?\s*"
    r"(?:for\s+|into\s+)?",
    re.IGNORECASE,
)

_NEWS = re.compile(
    r"\b(news|breaking|latest\s+news|headlines?|happened\s+today|"
    r"today'?s?\s+(?:headlines|news|updates)|current\s+events)\b",
    re.IGNORECASE,
)

_FRESHNESS = re.compile(
    r"\b(latest|current|recent|recently|today|tonight|yesterday|today'?s?|"
    r"now|this\s+week|this\s+month|updates?|newest|"
    r"202[0-9]|price|weather|stock|released?\s+(?:today|now|this)|"
    r"who\s+won|what\s+happened)\b",
    re.IGNORECASE,
)

_TIME_SENSITIVE = re.compile(
    r"\b(at\s+the\s+moment|right\s+now|as\s+of\s+(?:now|today)|"
    r"currently\s+(?:available|happening|going\s+on)|still\s+available|"
    r"how\s+much\s+is\s+insurance|today'?s?\s+rate|exchange\s+rate|"
    r"weather\s+(?:today|now|tomorrow)|is\s+it\s+(?:still|currently))\b",
    re.IGNORECASE,
)

_DOCS = re.compile(
    r"\b(documentation|docs|release\s+notes|changelog|"
    r"official\s+(?:docs|documentation)|api\s+changes|deprecated\b|"
    r"migration\s+guide|upgrade\s+guide)\b",
    re.IGNORECASE,
)

_FACT_CHECK = re.compile(
    r"\b(fact\s*check|verify|is\s+it\s+true\b|is\s+that\s+true|"
    r"is\s+this\s+real|did\s+that\s+really|claim\b|debunk|misinformation)\b",
    re.IGNORECASE,
)

_COMPARISON = re.compile(r"\b(compare|comparison|vs\.?|versus|difference\s+between)\b", re.IGNORECASE)

_RECOMMENDATION = re.compile(
    r"\b(best|recommend|top\s+rated|top\s+10|worth\s+buying|"
    r"should\s+i\s+buy|which\s+to\s+buy|good\s+options?)\b",
    re.IGNORECASE,
)

_LOCAL = re.compile(
    r"\b(near\s+me|in\s+my\s+area|local|weather\s+(?:today|now)"
    r"|opening\s+hours|timings?\s+today)\b",
    re.IGNORECASE,
)

# Static-knowledge phrasings must never trigger research on their own.
_KNOWLEDGE_PHRASING = re.compile(
    r"^(?:what\s+is|what\s+are|explain|describe|define|how\s+does|"
    r"how\s+do|what\s+does|who\s+is)\b",
    re.IGNORECASE,
)

_CONFIDENCE = {
    QueryType.NEWS: 0.9,
    QueryType.CURRENT_INFORMATION: 0.85,
    QueryType.TIME_SENSITIVE: 0.85,
    QueryType.LOCAL_INFORMATION: 0.7,
    QueryType.TECHNICAL_DOCUMENTATION: 0.7,
    QueryType.FACT_CHECK: 0.75,
    QueryType.COMPARISON: 0.6,
    QueryType.RECOMMENDATION: 0.65,
    QueryType.GENERAL_KNOWLEDGE: 0.4,
    QueryType.UNKNOWN: 0.2,
}


def _query_type_to_string(query_type: QueryType) -> str:
    return query_type.value


class ResearchRouter:
    """Decide whether (and how) a user query needs live web research."""

    def __init__(self, planner=None, classify: Optional[Callable[..., str]] = None):
        from friday.research.planner import ResearchPlanner

        self.planner = planner or ResearchPlanner()
        self.classify = classify

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide(
        self,
        user_query: str,
        conversation_context=None,
        existing_retrieval_context=None,
    ) -> ResearchDecision:
        """Classify *user_query* and produce a :class:`ResearchDecision`."""
        text = (user_query or "").strip()
        if not text:
            return ResearchDecision(reason="empty query", query_type=QueryType.UNKNOWN.value)

        low = text.lower()

        if _EXPLICIT_REQUEST.search(low):
            subject = _EXPLICIT_STRIP.sub("", text).strip().rstrip("?.! ")
            subject = subject or text
            query_type = self._classify_type(subject)
            if query_type == QueryType.UNKNOWN:
                query_type = QueryType.CURRENT_INFORMATION
            queries = self.planner.plan(subject, query_type)
            return ResearchDecision(
                needs_web=True,
                reason="explicit search request",
                query_type=_query_type_to_string(query_type),
                confidence=0.95,
                search_queries=queries,
                explicit_request=True,
            )

        query_type = self._classify_type(text)
        needs_web = self._needs_web(query_type, low)

        plan: list = []
        if needs_web:
            plan = self.planner.plan(text, query_type)

        return ResearchDecision(
            needs_web=needs_web,
            reason=self._reason(query_type, needs_web),
            query_type=_query_type_to_string(query_type),
            confidence=float(_CONFIDENCE.get(query_type, 0.0)),
            search_queries=plan,
        )

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    def _classify_type(self, text: str) -> QueryType:
        low = text.lower()
        if _NEWS.search(low):
            return QueryType.NEWS
        if _TIME_SENSITIVE.search(low):
            return QueryType.TIME_SENSITIVE
        if _LOCAL.search(low):
            return QueryType.LOCAL_INFORMATION
        if _FRESHNESS.search(low):
            return QueryType.CURRENT_INFORMATION
        if _DOCS.search(low):
            return QueryType.TECHNICAL_DOCUMENTATION
        if _FACT_CHECK.search(low):
            return QueryType.FACT_CHECK
        if _COMPARISON.search(low):
            return QueryType.COMPARISON
        if _RECOMMENDATION.search(low):
            return QueryType.RECOMMENDATION
        if self.classify is not None:
            # Optional heuristic-LLM fallback: injected classifiers may return a
            # QueryType member, its value string, or its enum name.
            try:
                label = self.classify(text)
                if isinstance(label, QueryType):
                    return label
                name = str(label or "").strip().upper()
                if name in QueryType.__members__:
                    return QueryType[name]
                for qt in QueryType:
                    if qt.value == name:
                        return qt
            except Exception:
                pass
        if _KNOWLEDGE_PHRASING.match(low):
            return QueryType.GENERAL_KNOWLEDGE
        return QueryType.UNKNOWN

    def _needs_web(self, query_type: QueryType, low: str) -> bool:
        if query_type in (QueryType.NEWS, QueryType.CURRENT_INFORMATION,
                          QueryType.TIME_SENSITIVE):
            return True
        if query_type == QueryType.LOCAL_INFORMATION:
            return bool(_FRESHNESS.search(low) or "weather" in low or "near me" in low)
        # Technical / comparison / recommendation queries only need the web when
        # coupled with a recency signal ("latest docs", "recent changes").
        if query_type in (QueryType.TECHNICAL_DOCUMENTATION,
                          QueryType.COMPARISON,
                          QueryType.RECOMMENDATION):
            return bool(_FRESHNESS.search(low))
        if query_type == QueryType.FACT_CHECK:
            # Verify-style checks benefit from the web; plain textbook
            # questions about whether X is true stay local without a marker.
            return bool(_FRESHNESS.search(low)) or "verify" in low or "fact check" in low
        return False

    @staticmethod
    def _reason(query_type: QueryType, needs_web: bool) -> str:
        if not needs_web:
            return "query answerable from local knowledge/context"
        reasons = {
            QueryType.NEWS: "query asks about news/current events",
            QueryType.CURRENT_INFORMATION: "query requests current information",
            QueryType.TIME_SENSITIVE: "query is time-sensitive",
            QueryType.LOCAL_INFORMATION: "query asks about local/live conditions",
            QueryType.TECHNICAL_DOCUMENTATION: "query asks for current technical documentation",
            QueryType.FACT_CHECK: "query asks to verify a claim",
            QueryType.COMPARISON: "query compares current options",
            QueryType.RECOMMENDATION: "query asks for a current recommendation",
        }
        return reasons.get(query_type, "query requires external information")


__all__ = ["ResearchRouter"]