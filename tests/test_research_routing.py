"""
ROUTING — live web research must own current-information turns.

Regression suite for the P-live fix: news / current-information queries must
never be answered from the reasoner's stale knowledge. Explicit news requests
are owned by the dedicated news skill (real headlines, grounded summary);
other time-sensitive queries are owned by the research subsystem. This pins:

  * explicit "news" requests reach ``news_skill`` and never the bare reasoner;
  * research is evaluated on the *resolved* query for current-information
    turns, regardless of the intent classifier's class;
  * "how are you" still stays on the natural-conversation layer (no research,
    no reasoner);
  * static questions ("what is Node.js") stay on the local path;
  * a time-sensitive query whose data source fails returns an honest
    "live sources unavailable" reply and is NEVER answered from the static
    model.

All providers are stubs — never the real network.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday import news_skill
from friday.core.conversation import ConversationManager
from friday.research.models import (
    QueryType, ResearchResponse, SearchFailure, SearchResult,
)
from friday.research.router import ResearchRouter


class RecordingReasoner:
    """Counts every request the bare reasoner would have received."""

    def __init__(self):
        self.requests = []

    def is_available(self):
        return True

    def request(self, text, st_context, mode="chat"):
        self.requests.append(text)
        return {"type": "response", "text": f"local answer: {text}"}


class RecordingResearch:  # noqa: PLW1641 - not a real ResearchAgent, just a stub
    enabled = True

    def __init__(self, fail=False):
        self.seen = []
        self._router = ResearchRouter()
        self._fail = fail

    def decide(self, query):
        return self._router.decide(query)

    def research(self, query):
        self.seen.append(query)
        decision = self.decide(query)
        if not decision.needs_web:
            return ResearchResponse(
                original_query=query, needs_web=False,
                query_type=decision.query_type, success=True,
            )
        if self._fail:
            return ResearchResponse(
                original_query=query, needs_web=True,
                query_type=decision.query_type, success=False,
                error=SearchFailure(provider="stub", error_type="network",
                                    message="down"),
            )
        results = [
            SearchResult(title=f"Result {i}", url=f"https://news.example/{i}",
                         snippet="s", source="stub", rank=i)
            for i in range(1, 4)
        ]
        return ResearchResponse(
            original_query=query, needs_web=True,
            query_type=decision.query_type, success=True,
            results=results, provider="stub",
        )


def _manager(research=None, reasoner=None):
    cm = ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=reasoner,
        research_agent=research,
        research_enabled=bool(research is not None and research.enabled),
    )
    cm.start_session()
    return cm


def _patch_news(monkeypatch, spoken="Grounded headline summary.", fetch_ok=True):
    """Stub the news skill so routing tests never touch the network or the LLM."""
    calls = []

    def fake_summarize(llm_client=None, limit=8, hindi=False, region=None):
        calls.append({"limit": limit, "hindi": hindi, "region": region})
        if not fetch_ok:
            return "I couldn't retrieve live news right now. feed down", None
        return spoken, [{"title": "Headline", "source": "Test"}]

    monkeypatch.setattr(news_skill, "summarize_headlines", fake_summarize)
    return calls


# ---------------------------------------------------------------------------
# Explicit news requests are owned by the dedicated news skill
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "can you tell me the latest news?",
    "latest news about India",
    "give me the news",
])
def test_news_queries_reach_news_skill_not_research_or_reasoner(monkeypatch, utterance):
    calls = _patch_news(monkeypatch, spoken="Grounded headline summary.")
    research = RecordingResearch()
    reasoner = RecordingReasoner()
    cm = _manager(research=research, reasoner=reasoner)
    reply, sent = cm.handle_transcript(utterance)
    assert sent is True
    assert calls, f"news skill must handle {utterance!r}"
    assert research.seen == [], "news requests skip live research"
    assert reasoner.requests == [], "news requests never reach the bare reasoner"
    assert "Grounded headline summary." in reply


# ---------------------------------------------------------------------------
# Non-news current-information turns still own the research gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "check further latest information about news, such were news articles, "
    "yesterday or today.",
    "what is happening today?",
    "what happened yesterday",
])
def test_time_sensitive_queries_reach_research_not_reasoner(utterance):
    research = RecordingResearch()
    reasoner = RecordingReasoner()
    cm = _manager(research=research, reasoner=reasoner)
    reply, sent = cm.handle_transcript(utterance)
    assert sent is True
    assert research.seen, f"research must be evaluated for {utterance!r}"
    assert reasoner.requests == [], f"reasoner must not answer {utterance!r}"
    assert "I checked current sources" in reply


def test_unknown_class_query_reaches_research():
    research = RecordingResearch()
    reasoner = RecordingReasoner()
    cm = _manager(research=research, reasoner=reasoner)
    reply, sent = cm.handle_transcript("what happened yesterday")
    assert sent is True
    assert research.seen
    assert reasoner.requests == []
    assert "I checked current sources" in reply
    assert "news.example" in reply  # source-annotated evidence, not bare knowledge


def test_command_classed_conditional_news_reaches_research():
    research = RecordingResearch()
    reasoner = RecordingReasoner()
    cm = _manager(research=research, reasoner=reasoner)
    reply, sent = cm.handle_transcript(
        "if you dont know the latest news, search in a virtual browser and "
        "fetch it to me."
    )
    assert sent is True
    assert research.seen
    assert reasoner.requests == []
    assert "I checked current sources" in reply


def test_news_followup_resolves_regional_context_before_research(monkeypatch):
    _patch_news(monkeypatch)
    research = RecordingResearch()
    reasoner = RecordingReasoner()
    cm = _manager(research=research, reasoner=reasoner)
    cm.handle_transcript("latest news about India")
    cm.handle_transcript("what about yesterday?")
    assert len(research.seen) == 1
    assert "India" in research.seen[-1]  # resolved query, not the raw ellipsis


# ---------------------------------------------------------------------------
# Non-news turns stay on their normal path
# ---------------------------------------------------------------------------

def test_natural_chatter_skips_research_and_reasoner():
    research = RecordingResearch()
    reasoner = RecordingReasoner()
    cm = _manager(research=research, reasoner=reasoner)
    reply, sent = cm.handle_transcript("how are you")
    assert sent is True
    assert research.seen == [], "pure chatter must not reach research"
    assert reasoner.requests == [], "pure chatter must not reach the reasoner"
    assert reply


def test_static_knowledge_stays_local_with_research_enabled():
    research = RecordingResearch()
    reasoner = RecordingReasoner()
    cm = _manager(research=research, reasoner=reasoner)
    reply, sent = cm.handle_transcript("what is Node.js")
    assert sent is True
    assert research.seen, "research hook is evaluated"
    assert not research._router.decide("what is Node.js").needs_web
    assert reasoner.requests, "factual questions stay on the local path"


def test_news_still_handled_when_research_disabled(monkeypatch):
    calls = _patch_news(monkeypatch, spoken="Grounded headline summary.")
    reasoner = RecordingReasoner()
    cm = _manager(research=None, reasoner=reasoner)
    reply, sent = cm.handle_transcript("can you tell me the latest news?")
    assert sent is True
    assert calls, "news skill owns the turn even without the research subsystem"
    assert reasoner.requests == [], "reasoner must not answer news from stale knowledge"
    assert "Grounded headline summary." in reply


# ---------------------------------------------------------------------------
# Bounded fallback
# ---------------------------------------------------------------------------

def test_news_fetch_failure_is_honest_and_blocks_static_reasoner(monkeypatch):
    _patch_news(monkeypatch, fetch_ok=False)
    research = RecordingResearch()
    reasoner = RecordingReasoner()
    cm = _manager(research=research, reasoner=reasoner)
    reply, sent = cm.handle_transcript("can you tell me the latest news?")
    assert sent is True
    assert reasoner.requests == [], "static model must not answer time-sensitive gaps"
    assert "couldn't retrieve live news" in reply


def test_news_research_failure_reply_for_current_information():
    research = RecordingResearch(fail=True)
    reasoner = RecordingReasoner()
    cm = _manager(research=research, reasoner=reasoner)
    reply, _ = cm.handle_transcript("what is happening today?")
    assert "couldn't retrieve" in reply
    assert reasoner.requests == []


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])