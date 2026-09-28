"""
UNIT/INTEGRATION — ResearchAgent orchestration (Phase 1+2) and opt-in hookup
inside ConversationManager. All searches use stub providers — never the real
network. The local pipeline must behave unchanged when research is disabled
(backward compatibility).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.research.agent import ResearchAgent
from friday.research.config import ResearchConfig
from friday.research.models import QueryType, ResearchResponse, SearchFailure, SearchResult
from friday.research.search.base import SearchError, SearchProvider


class StubProvider(SearchProvider):
    name = "stub"
    requires_api_key = False

    def __init__(self, results=None, error=None):
        self._results = results or []
        self._error = error
        self.calls = []

    def search(self, query, max_results=5, timeout=10.0, freshness=None):
        self.calls.append((query, max_results, freshness))
        if self._error is not None:
            raise self._error
        return [SearchResult(title=f"{query} #{i}", url=f"https://example.com/{i}",
                             snippet="", source=self.name, rank=i + 1)
                for i in range(min(len(self._results), max_results))]


def _config(provider="stub", enabled=True, max_results=5, max_queries=3, timeout=10.0):
    return ResearchConfig(
        enabled=enabled, provider=provider, api_key="", max_results=max_results,
        max_queries=max_queries, timeout=timeout, prefer_official=False,
    )


# ---------------------------------------------------------------------------
# Agent behaviour
# ---------------------------------------------------------------------------

def test_disabled_agent_is_safe_noop():
    provider = StubProvider(results=["a"])
    agent = ResearchAgent(provider=provider, config=_config(enabled=False))
    response = agent.research("latest Python version")
    assert response.success is True
    assert response.results == []
    assert response.needs_web is False
    assert provider.calls == []  # never touched the provider


def test_local_question_does_not_seek_web():
    provider = StubProvider(results=["a"])
    agent = ResearchAgent(provider=provider, config=_config(enabled=True))
    response = agent.research("What is a binary tree?")
    assert response.needs_web is False
    assert provider.calls == []
    assert response.success is True
    assert response.results == []
    assert response.query_type == QueryType.GENERAL_KNOWLEDGE.value


def test_web_question_plans_and_searches():
    provider = StubProvider(results=[f"r{i}" for i in range(6)])
    agent = ResearchAgent(provider=provider, config=_config(enabled=True))
    response = agent.research("What is the latest Python version?")
    assert response.needs_web is True
    assert provider.calls, "expected provider to be invoked"
    assert response.success is True
    assert 1 <= len(response.results) <= 5
    assert response.results[0].url.startswith("https://example.com/")
    assert response.provider == "stub"


def test_provider_failure_never_raises_and_reports():
    error = SearchError("server unreachable", error_type="network",
                        retryable=True, provider="stub")
    provider = StubProvider(error=error)
    agent = ResearchAgent(provider=provider, config=_config(enabled=True))
    response = agent.research("latest Python version")
    assert response.success is False
    assert response.results == []
    assert isinstance(response.error, SearchFailure)
    assert response.error.error_type == "network"
    assert response.error.retryable is True


def test_empty_results_map_to_search_failure():
    provider = StubProvider(results=[])
    agent = ResearchAgent(provider=provider, config=_config(enabled=True))
    response = agent.research("latest Python version")
    assert response.success is False
    assert response.error is not None
    assert response.error.error_type == "empty_results"


def test_results_are_deduped_and_capped():
    class DupProvider(SearchProvider):
        name = "dup"
        requires_api_key = False

        def search(self, query, max_results=5, timeout=10.0, freshness=None):
            return [SearchResult(title="same", url="https://ex.com/x?utm_source=a",
                                 snippet="", source=self.name, rank=i)
                    for i in range(1, 7)]

    agent = ResearchAgent(provider=DupProvider(), config=_config(enabled=True, max_results=3))
    response = agent.research("latest Python version")
    assert len(response.results) == 1
    assert response.success is True


def test_decide_exposes_plan():
    provider = StubProvider(results=[])
    agent = ResearchAgent(provider=provider, config=_config(enabled=True))
    decision = agent.decide("search the web for React 20")
    assert decision.explicit_request is True
    assert decision.search_queries
    assert decision.search_queries[0].lower().startswith("react 20")


def test_unknown_provider_config_falls_back():
    agent = ResearchAgent(config=_config(provider="not-a-provider", enabled=False))
    assert agent.provider.name in ("duckduckgo", "stub")


# ---------------------------------------------------------------------------
# ConversationManager integration (opt-in, backward compatible)
# ---------------------------------------------------------------------------

def _manager(research_agent=None, research_enabled=None):
    from friday.core.conversation import ConversationManager

    return ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=None,
        research_agent=research_agent,
        research_enabled=research_enabled,
    )


RESEARCH_QUERY = "What changed in React recently?"


def test_manager_enabled_surfaces_research_evidence():
    provider = StubProvider(results=[f"r{i}" for i in range(4)])
    agent = ResearchAgent(provider=provider, config=_config(enabled=True))
    mgr = _manager(research_agent=agent, research_enabled=True)
    reply, sent = mgr.handle_transcript(RESEARCH_QUERY)
    assert sent is True
    assert "I checked current sources" in reply
    assert "found 4 results" in reply
    assert mgr.context.last_research is not None
    assert isinstance(mgr.context.last_research, ResearchResponse)


def test_manager_research_disabled_pipeline_unchanged():
    """Backward compatibility: local path answers exactly as before."""
    mgr = _manager(research_agent=None)
    reply, sent = mgr.handle_transcript("What is 2 + 2?")
    assert sent is True
    assert mgr.context.last_research is None
    assert isinstance(reply, str) and reply


def test_manager_research_enabled_but_local_question_stays_local():
    provider = StubProvider(results=["a", "b"])
    agent = ResearchAgent(provider=provider, config=_config(enabled=True))
    mgr = _manager(research_agent=agent, research_enabled=True)
    reply, sent = mgr.handle_transcript("What is a binary tree?")
    assert sent is True
    assert provider.calls == []  # router said NO — provider untouched
    assert mgr.context.last_research is not None
    assert mgr.context.last_research.needs_web is False


def test_manager_research_failure_falls_through_gracefully():
    provider = StubProvider(error=SearchError("down", error_type="network",
                                              retryable=True, provider="stub"))
    agent = ResearchAgent(provider=provider, config=_config(enabled=True))
    mgr = _manager(research_agent=agent, research_enabled=True)
    reply, sent = mgr.handle_transcript(RESEARCH_QUERY)
    assert sent is True
    assert isinstance(reply, str) and reply  # still answered by local pipeline


def test_manager_env_flag_rules_agent_enabled():
    """Gated manager: research_enabled=True forces the hook even if the agent
    config is enabled (simulates the env-flag flow used by assistant.py)."""
    provider = StubProvider(results=["a"])
    agent = ResearchAgent(provider=provider, config=_config(enabled=True))
    mgr = _manager(research_agent=agent)
    assert mgr.research_enabled is True  # defaults from agent.enabled


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])