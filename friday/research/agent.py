"""
ResearchAgent — orchestrates the Phase 1 + Phase 2 research pipeline.

    decide()  -> ResearchRouter.decide
    research() -> decide -> plan -> run each search query -> ResearchResponse

Never fabricates results: any provider failure becomes a structured
:class:`SearchFailure` on the response and the caller falls back to the local
pipeline. When research is disabled the agent is a safe no-op.
"""
import time
from typing import List, Optional

from friday.research.config import ResearchConfig
from friday.research.models import QueryType, ResearchDecision, ResearchResponse, SearchFailure
from friday.research.router import ResearchRouter
from friday.research.search.base import SearchError, SearchProvider, dedupe_results
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def build_provider(provider_name: str, api_key: str = "") -> SearchProvider:
    """Construct a configured provider by name (lowercase, tolerant)."""
    name = (provider_name or "").strip().lower()
    if name in ("", "duckduckgo", "ddg", "duckduckgo_search"):
        from friday.research.search.ddg_provider import DuckDuckGoSearchProvider
        return DuckDuckGoSearchProvider(api_key=api_key or "")
    raise ValueError(f"Unknown search provider: {provider_name!r}")


class ResearchAgent:
    def __init__(
        self,
        provider: Optional[SearchProvider] = None,
        router: Optional[ResearchRouter] = None,
        config: Optional[ResearchConfig] = None,
    ):
        self.config = config or ResearchConfig.load()
        self.router = router or ResearchRouter()
        if provider is not None:
            self.provider = provider
        else:
            self.provider = self._make_provider()

    def _make_provider(self) -> SearchProvider:
        try:
            return build_provider(self.config.provider, self.config.api_key)
        except ValueError:
            logger.warning("[RESEARCH] unknown provider %r; falling back to duckduckgo",
                           self.config.provider)
            return build_provider("duckduckgo", self.config.api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled)

    def decide(
        self,
        user_query: str,
        conversation_context=None,
        existing_retrieval_context=None,
    ) -> ResearchDecision:
        return self.router.decide(
            user_query,
            conversation_context=conversation_context,
            existing_retrieval_context=existing_retrieval_context,
        )

    def research(self, user_query: str) -> ResearchResponse:
        """Run the full research pipeline for *user_query*."""
        start = time.monotonic()
        response = ResearchResponse(original_query=user_query)
        if not self.enabled:
            response.success = True  # research off: nothing to do, not a failure
            response.elapsed_ms = (time.monotonic() - start) * 1000.0
            return response

        decision = self.decide(user_query)
        response.search_queries = list(decision.search_queries)
        response.query_type = decision.query_type
        response.needs_web = decision.needs_web
        response.provider = self.provider.name
        if not decision.needs_web:
            response.success = True  # nothing to search; not a failure
            response.elapsed_ms = (time.monotonic() - start) * 1000.0
            return response

        logger.info(
            "[RESEARCH] needs_web=true type=%s reason=%s queries=%d",
            decision.query_type, decision.reason, len(decision.search_queries),
        )

        collected: List = []
        failures: List[SearchError] = []
        deadline = time.monotonic() + self.config.timeout * max(1, len(decision.search_queries))
        for query in decision.search_queries:
            if time.monotonic() >= deadline:
                break
            try:
                found = self.provider.search(
                    query,
                    max_results=self.config.max_results,
                    timeout=self.config.timeout,
                    freshness=self._freshness_for(decision.query_type),
                )
                logger.info(
                    "[SEARCH] provider=%s query=%r results=%d",
                    self.provider.name, query, len(found),
                )
            except SearchError as exc:
                logger.warning(
                    "[SEARCH] provider=%s query=%r error=%s retryable=%s",
                    self.provider.name, query, exc.error_type, exc.retryable,
                )
                failures.append(exc)
                if not exc.retryable:
                    break
                continue
            except Exception as exc:  # noqa: BLE001 - guard against provider bugs
                failures.append(SearchError(str(exc), error_type="provider_error",
                                            retryable=False, provider=self.provider.name))
                break
            collected.extend(found)
            if len(collected) >= self.config.max_results:
                break

        response.results = dedupe_results(collected, max_results=self.config.max_results)
        response.elapsed_ms = (time.monotonic() - start) * 1000.0

        worst = self._worst_failure(failures)
        if not response.results:
            response.success = False
            response.error = SearchFailure(
                provider=self.provider.name,
                error_type=worst.error_type if worst else "empty_results",
                message=(worst.message if worst else "no search results returned"),
                retryable=worst.retryable if worst else False,
            )
            logger.info(
                "[SEARCH] provider=%s results=0 latency_ms=%.0f error=%s",
                self.provider.name, response.elapsed_ms,
                response.error.error_type,
            )
        else:
            response.success = True
            logger.info(
                "[SEARCH] provider=%s results=%d latency_ms=%.0f",
                self.provider.name, len(response.results), response.elapsed_ms,
            )
        return response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _freshness_for(query_type: str) -> Optional[str]:
        if query_type in (QueryType.NEWS.value, QueryType.CURRENT_INFORMATION.value):
            return "month"
        if query_type == QueryType.TIME_SENSITIVE.value:
            return "week"
        return None

    @staticmethod
    def _worst_failure(failures: List[SearchError]) -> Optional[SearchError]:
        if not failures:
            return None
        failures = sorted(failures, key=lambda f: (f.retryable, f.error_type))
        return failures[-1]


__all__ = ["ResearchAgent", "build_provider"]