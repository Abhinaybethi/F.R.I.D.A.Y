"""
UNIT TEST — Conversational follow-up machinery (Phases 2-6)

Covers the deterministic conversational layer added to ConversationManager /
ConversationContext: topic tracking, reference resolution, follow-up query
rewriting, and the deterministic brain router. No Ollama / network / mic.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.brain.router import route_request
from friday.core.conversation import ConversationContext, ConversationManager
from friday.planning.context_resolver import ShortTermContext
from friday.reasoning.interface import Reasoner


class RecordingReasoner(Reasoner):
    """Records every transcript the reasoner sees; never talks to a server."""

    def __init__(self, text="Understood."):
        self.text = text
        self.seen = []

    def is_available(self) -> bool:
        return True

    def health(self) -> str:
        return "mock"

    def request(self, transcript, context, mode="action", **kwargs) -> dict:
        self.seen.append(transcript)
        return {"type": "response", "text": self.text}

    def close(self):
        pass


# ---------------------------------------------------------------------------
# ConversationContext unit tests
# ---------------------------------------------------------------------------

def test_update_topic_from_knowledge_question():
    ctx = ConversationContext()
    ctx.update_topic("Tell me about the backend architecture")
    assert "backend architecture" in ctx.active_topic


def test_update_topic_tracks_entity_category():
    ctx = ConversationContext()
    ctx.update_topic("What is the backend built with?")
    assert ctx.active_topic == "backend built with"
    assert "backend" in ctx.entities


def test_update_topic_switchaway_clears():
    ctx = ConversationContext()
    ctx.active_topic = "voice"
    ctx.update_topic("Actually, forget that. What time is it?")
    assert ctx.active_topic == ""


def test_resolve_reference_system_subject_pronoun():
    ctx = ConversationContext()
    ctx.update_topic("What backend does it use?")
    resolved, ok = ctx.resolve_reference("Why did we choose that?")
    assert ok
    assert "friday" in resolved and "backend" in resolved


def test_resolve_reference_what_about():
    ctx = ConversationContext()
    ctx.update_topic("What is the backend?")
    resolved, ok = ctx.resolve_reference("What about it?")
    assert ok
    assert resolved == "what about backend?"


def test_rewrite_followup_grounded_pronoun():
    ctx = ConversationContext()
    ctx.update_topic("What backend does it use?")
    rewritten = ctx.rewrite_followup("Why did we choose that?", history=[])
    assert rewritten.lower() == "why did friday choose backend?"


def test_rewrite_followup_plain_first_turn_unchanged():
    ctx = ConversationContext()
    rewritten = ctx.rewrite_followup("What is F.R.I.D.A.Y.?", history=[])
    assert rewritten == "What is F.R.I.D.A.Y.?"


def test_rewrite_followup_bare_connector_uses_prior_turn():
    ctx = ConversationContext()
    rewritten = ctx.rewrite_followup(
        "And after?",
        history=[{"transcript": "what was our rag score before the optimization"}],
    )
    assert "rag score" in rewritten


# ---------------------------------------------------------------------------
# End-to-end multi-turn through ConversationManager (fake reasoner)
# ---------------------------------------------------------------------------

def _cm_with_recorded_reasoner():
    reasoner = RecordingReasoner()
    cm = ConversationManager(dry_run=True, allow_real_execution=False, reasoner=reasoner)
    cm.start_session()
    return cm, reasoner


def test_multiturn_followups_are_rewritten_standalone():
    cm, reasoner = _cm_with_recorded_reasoner()

    resp1, _ = cm.handle_transcript("What is F.R.I.D.A.Y.?")
    resp2, _ = cm.handle_transcript("What backend does it use?")
    resp3, _ = cm.handle_transcript("Why did we choose that?")

    # resolve_context normalises each turn; later turns must arrive as
    # standalone, grounded queries (no dangling "it"/"we"/"that").
    assert "friday" in reasoner.seen[0].lower()
    turns = [s.lower() for s in reasoner.seen]
    assert "backend" in turns[1] and "friday" in turns[1]          # standalone
    assert "backend" in turns[2] and "friday" in turns[2]          # grounded
    assert " it" not in turns[2] and "we" not in turns[2].split("friday")[1]
    assert cm.context.active_topic == "backend"
    assert resp1 and resp2 and resp3


def test_multiturn_survives_topic_switch_away():
    cm, reasoner = _cm_with_recorded_reasoner()

    cm.handle_transcript("What backend does it use?")
    cm.handle_transcript("Actually, forget that. What was our RAG score before optimization?")

    # The forgetting turn carries its full subject (resolve_context normalises
    # casing/punctuation); the rewriter must not strip or mangle it.
    last = reasoner.seen[-1].lower()
    assert "rag score" in last and "optimization" in last
    assert "backend" not in last.split("forget that")[0] or last.startswith("actually forget that")


def test_multiturn_does_not_break_deterministic_commands():
    cm, _ = _cm_with_recorded_reasoner()
    resp, keep = cm.handle_transcript("open chrome")
    assert keep is True
    assert resp and ("chrome" in resp.lower() or "would" in resp.lower())


# ---------------------------------------------------------------------------
# Brain router
# ---------------------------------------------------------------------------

def test_router_tool():
    out = route_request("Open Chrome")
    assert out["kind"] == "tool"
    assert out["action"].name == "OPEN_APP"


def test_router_knowledge():
    out = route_request("What is F.R.I.D.A.Y.?")
    assert out["kind"] == "knowledge"


def test_router_reasoning():
    out = route_request("calculate what is 25 * 40")
    assert out["kind"] == "reasoning"


def test_router_clarification():
    out = route_request("Why did we choose that?")
    assert out["kind"] == "clarification"


def test_router_empty():
    out = route_request("")
    assert out["kind"] == "unsupported"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])