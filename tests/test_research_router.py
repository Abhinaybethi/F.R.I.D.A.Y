"""
UNIT — ResearchRouter (Phase 1).

Pin the deterministic decide() behaviour: local queries must NOT trigger web
research, current-information / news / explicit-search queries MUST, and
generated query plans stay small.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.research.models import QueryType
from friday.research.router import ResearchRouter

ROUTER = ResearchRouter()


def _decide(query):
    return ROUTER.decide(query)


# ---------------------------------------------------------------------------
# Should NOT search
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "What is a binary tree?",
    "Explain REST API.",
    "What is Python?",
    "What is dependency injection?",
    "Explain polymorphism.",
    "What is JWT?",
    "What is the difference between PUT and PATCH?",
    "Explain this code.",
    "What did I ask you previously?",
    "Who is the president of Britain?",
])
def test_local_knowledge_never_triggers_web(query):
    decision = _decide(query)
    assert decision.needs_web is False, query
    assert decision.search_queries == [], query


@pytest.mark.parametrize("query", [
    "What is a linked list?",
    "How does an LLM work?",
    "Define recursion.",
])
def test_static_concepts_stay_local(query):
    assert _decide(query).needs_web is False


# ---------------------------------------------------------------------------
# Should search
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "What is the latest Python version?",
    "What happened today?",
    "Latest Node.js release.",
    "Current price of Bitcoin?",
    "Who won yesterday's match?",
    "Current government notification",
    "What are the current requirements for this job?",
    "Is this website/service currently available?",
    "What changed in React recently?",
    "Latest React documentation",
])
def test_current_information_triggers_web(query):
    decision = _decide(query)
    assert decision.needs_web is True, query
    assert decision.query_type in (QueryType.CURRENT_INFORMATION.value,
                                   QueryType.NEWS.value,
                                   QueryType.TIME_SENSITIVE.value), query
    assert 1 <= len(decision.search_queries) <= 3, query


@pytest.mark.parametrize("query", [
    "What is the latest news about OpenAI?",
    "Breaking: anything notable today",
    "Any news about SpaceX?",
])
def test_news_classes_as_news(query):
    decision = _decide(query)
    assert decision.needs_web is True
    assert decision.query_type == QueryType.NEWS.value


@pytest.mark.parametrize("query", [
    "Search the web for React 20 changes.",
    "search online for the latest Python",
    "Look this up on the internet.",
    "Research this.",
    "Find current information about the weather today",
    "Check the latest on Bitcoin",
    "Browse the internet for today's tech news",
    "Google it",
])
def test_explicit_search_requests_always_trigger(query):
    decision = _decide(query)
    assert decision.needs_web is True, query
    assert decision.explicit_request is True, query
    assert decision.confidence >= 0.9, query
    assert decision.search_queries
    # The search framing must be stripped from the generated queries.
    first = decision.search_queries[0].lower()
    assert "search the web for" not in first
    assert "look this up on the internet" not in first


def test_fact_check_verify_triggers_web():
    assert _decide("Verify this claim about the election.").needs_web is True


def test_plain_fact_question_stays_local():
    decision = _decide("Is it true that the Earth is round?")
    assert decision.needs_web is False


def test_llm_classify_fallback_can_override_unknown():
    router = ResearchRouter(classify=lambda q: QueryType.CURRENT_INFORMATION)
    decision = router.decide("Tell me about quantum computing trends")
    assert decision.query_type == QueryType.CURRENT_INFORMATION.value


def test_empty_query_never_searches():
    decision = _decide("")
    assert decision.needs_web is False
    assert decision.query_type == QueryType.UNKNOWN.value


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])