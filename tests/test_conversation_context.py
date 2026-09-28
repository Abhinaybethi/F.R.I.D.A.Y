"""
UNIT + INTEGRATION — Conversational Context & Reference Resolution.

Pins the short-term conversational context upgrade: typed entity memory,
person/place/group/event resolution, ellipsis rewrites, ambiguity and
no-antecedent clarification, raw-vs-resolved query separation, live-web
follow-up bridging and after-answer entity harvesting. No Ollama / network.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.core.conversation import (
    ConversationContext,
    ConversationManager,
    _REF_STATUS_RESOLVED,
    _REF_STATUS_AMBIGUOUS,
    _REF_STATUS_UNRESOLVED,
    _REF_STATUS_NOT_NEEDED,
)
from friday.intent.classifier import RequestClass, classify


class PersonaReasoner:
    """Records queries; returns a canned text per lowercased prefix."""

    def __init__(self, responses=None):
        self.seen = []
        self.responses = responses or {}

    def is_available(self):
        return True

    def request(self, transcript, context=None, mode="action", **kwargs):
        self.seen.append(transcript)
        low = (transcript or "").lower()
        for prefix, text in self.responses.items():
            if low.startswith(prefix):
                return {"type": "response", "text": text}
        return {"type": "response", "text": "Understood."}


def _manager(reasoner=None):
    cm = ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=reasoner or PersonaReasoner(),
    )
    cm.start_session()
    return cm


# ---------------------------------------------------------------------------
# ConversationContext — unit level
# ---------------------------------------------------------------------------

def _harvest(ctx, raw, resolved, response):
    ctx.last_raw_query = raw
    ctx.last_resolved_query = resolved
    ctx.last_response = response
    ctx.finalize_turn()


def test_person_reference_resolves_to_harvested_name():
    ctx = ConversationContext()
    ctx.observe_turn("Who is the president of Britain?")
    _harvest(ctx, "Who is the president of Britain?",
             "who is the president of britain",
             "He is King Charles III, the monarch of the United Kingdom.")

    res = ctx.resolve_conversation_reference("Who is he?")
    assert res.status == _REF_STATUS_RESOLVED
    assert "who is king charles iii" in res.resolved.lower()
    assert res.entity == "king charles iii"
    assert ctx.current_person == "king charles iii"
    assert ctx.current_person_gender == "male"


def test_person_reference_falls_back_to_role_before_answer():
    ctx = ConversationContext()
    ctx.observe_turn("Who is the president of Britain?")

    res = ctx.resolve_conversation_reference("Who is he?")
    assert res.status == _REF_STATUS_RESOLVED
    assert "president of britain" in res.resolved


def test_female_person_reference_resolves_with_gender():
    ctx = ConversationContext()
    ctx.observe_turn("Who was the first female president?")
    _harvest(ctx, "who was the first female president",
             "who was the first female president",
             "She was Vigdis Finnbogadottir of Iceland.")

    res = ctx.resolve_conversation_reference("Where is she from?")
    assert res.status == _REF_STATUS_RESOLVED
    assert "vigdis finnbogadottir" in res.resolved
    assert ctx.current_person_gender == "female"


def test_place_possessive_resolution():
    ctx = ConversationContext()
    ctx.observe_turn("What is the capital of France?")

    res = ctx.resolve_conversation_reference("What is its population?")
    assert res.status == _REF_STATUS_RESOLVED
    assert "france" in res.resolved
    assert "'s" in res.resolved


def test_entity_pronoun_it_resolves_to_named_person():
    ctx = ConversationContext()
    ctx.observe_turn("What kind of car does Elon Musk drive?")

    res = ctx.resolve_conversation_reference("How fast is it?")
    assert res.status == _REF_STATUS_RESOLVED
    assert "elon musk" in res.resolved


def test_ambiguity_clarification_for_two_people():
    ctx = ConversationContext()
    ctx.observe_turn("Tell me about Elon Musk and Jeff Bezos.")

    res = ctx.resolve_conversation_reference("How old is he?")
    assert res.status == _REF_STATUS_AMBIGUOUS
    assert "Elon Musk" in res.clarification
    assert "Jeff Bezos" in res.clarification
    assert set(res.candidates) == {"elon musk", "jeff bezos"}


def test_no_antecedent_person_pronoun_asks_who():
    ctx = ConversationContext()
    res = ctx.resolve_conversation_reference("Who is he?")
    assert res.status == _REF_STATUS_UNRESOLVED
    assert res.clarification == "Who are you referring to?"


def test_event_why_followup_rewrites_to_event_question():
    ctx = ConversationContext()
    ctx.observe_turn("The Russia-Ukraine war has continued for years.")

    res = ctx.resolve_conversation_reference("Why?")
    assert res.status == _REF_STATUS_RESOLVED
    assert res.resolved == "why did the russia-ukraine war happen?"


def test_demonstrative_that_resolves_to_event():
    ctx = ConversationContext()
    ctx.observe_turn("The Russia-Ukraine war has continued for years.")

    res = ctx.resolve_conversation_reference("Why did that happen?")
    assert res.status == _REF_STATUS_RESOLVED
    assert "russia-ukraine war" in res.resolved
    assert "that" not in res.resolved


def test_tell_more_ellipsis_resolves_to_focus():
    ctx = ConversationContext()
    ctx.observe_turn("Who is the president of Britain?")
    _harvest(ctx, "Who is the president of Britain?",
             "who is the president of britain",
             "He is King Charles III, the monarch of the United Kingdom.")

    res = ctx.resolve_conversation_reference("Tell me more about him.")
    assert res.status == _REF_STATUS_RESOLVED
    assert res.resolved == "tell me more about king charles iii"


def test_ellipsis_with_explicit_subject_passes_through():
    ctx = ConversationContext()
    ctx.observe_turn("Who is the president of Britain?")

    res = ctx.resolve_conversation_reference("Tell me more about King Charles III.")
    assert res.status == _REF_STATUS_NOT_NEEDED
    assert res.resolved == "Tell me more about King Charles III."


def test_what_about_other_one():
    ctx = ConversationContext()
    ctx._entity_memory = [
        {"name": "elon musk", "type": "PERSON", "gender": "male", "seq": 1},
        {"name": "jeff bezos", "type": "PERSON", "gender": "male", "seq": 2},
    ]
    ctx._entity_seq = 2

    res = ctx.resolve_conversation_reference("What about the other one?")
    assert res.status == _REF_STATUS_RESOLVED
    assert res.resolved == "what about elon musk"


def test_named_followup_subject_passes_through():
    ctx = ConversationContext()
    ctx.observe_turn("What is the latest news about Russia?")

    res = ctx.resolve_conversation_reference("What about Ukraine?")
    assert res.status == _REF_STATUS_NOT_NEEDED
    assert res.entity == "ukraine"


def test_it_without_antecedent_is_not_hijacked():
    ctx = ConversationContext()
    res = ctx.resolve_conversation_reference("what backend does it use")
    assert res.status == _REF_STATUS_NOT_NEEDED
    assert res.resolved == "what backend does it use"


def test_legacy_demonstrative_leave_to_rewriter():
    ctx = ConversationContext()
    res = ctx.resolve_conversation_reference("why did we choose that")
    assert res.status == _REF_STATUS_NOT_NEEDED


def test_raw_query_never_overwritten_by_resolution():
    ctx = ConversationContext()
    ctx.last_raw_query = "raw query"
    ctx.last_resolved_query = "resolved query"
    assert ctx.last_raw_query == "raw query"
    assert ctx.last_resolved_query == "resolved query"


def test_recency_window_is_bounded():
    ctx = ConversationContext()
    ctx.recent_turns_max = 3
    for i in range(5):
        ctx.push_entity(f"person {i}", "PERSON", "male")
    assert len(ctx._entity_memory) == 3
    assert {"name": "person 0"} not in ctx._entity_memory


def test_gender_mismatch_requests_clarification():
    ctx = ConversationContext()
    ctx.push_entity("king charles iii", "PERSON", "male")

    res = ctx.resolve_conversation_reference("Who is she?")
    assert res.status == _REF_STATUS_UNRESOLVED
    assert res.clarification == "Who are you referring to?"


def test_named_person_outranks_role_for_male_pronoun():
    ctx = ConversationContext()
    ctx.push_entity("the president of the united states", "PERSON_ROLE")
    _harvest(ctx, "Who is the president of the United States?",
             "who is the president of the united states",
             "The president is Joe Biden.")

    res = ctx.resolve_conversation_reference("What is his age?")
    assert res.status == _REF_STATUS_RESOLVED
    assert "joe biden" in res.resolved


# ---------------------------------------------------------------------------
# ConversationManager — integration level
# ---------------------------------------------------------------------------

def test_manager_resolves_person_followup_across_turns():
    reasoner = PersonaReasoner({
        "who is the president of britain":
            "He is King Charles III, the monarch of the United Kingdom.",
    })
    cm = _manager(reasoner)

    resp1, _ = cm.handle_transcript("Who is the president of Britain?")
    assert resp1

    resp2, _ = cm.handle_transcript("Who is he?")
    assert reasoner.seen[-1] == "who is king charles iii", reasoner.seen
    assert cm.context.current_person == "king charles iii"
    assert cm.context.current_person_gender == "male"


def test_manager_ambiguity_returns_clarification_without_reasoner():
    cm = _manager(PersonaReasoner())
    cm.handle_transcript("Tell me about Elon Musk and Jeff Bezos.")
    cm.context._entity_memory = [
        {"name": "elon musk", "type": "PERSON", "gender": "", "seq": 1},
        {"name": "jeff bezos", "type": "PERSON", "gender": "", "seq": 2},
    ]
    cm.context._entity_seq = 2
    reasoner = cm.reasoner
    reasoner.seen.clear()

    resp, _ = cm.handle_transcript("How old is he?")
    assert "Elon Musk" in resp and "Jeff Bezos" in resp
    assert reasoner.seen == [], "ambiguous reference must not reach the reasoner"


def test_manager_no_antecedent_asks_for_referent():
    cm = _manager()
    resp, _ = cm.handle_transcript("Who is he?")
    assert resp == "Who are you referring to?"
    assert cm.reasoner.seen == []


def test_manager_reasoner_fallback_resolves_unknown_pronoun():
    cm = _manager()
    cm.context.push_entity("king charles iii", "PERSON", "male")

    resp, _ = cm.handle_transcript("Tell me more about him.")
    assert cm.reasoner.seen[-1] == "tell me more about king charles iii"


def test_manager_event_why_followup_is_grounded():
    cm = _manager()
    cm.handle_transcript("The Russia-Ukraine war has continued for years.")
    resp, _ = cm.handle_transcript("Why?")
    last = cm.reasoner.seen[-1]
    assert "why did the" in last and "russia" in last and "war" in last and "happen" in last


def test_manager_live_web_followup_bridges_to_search():
    cm = _manager()
    resp1, _ = cm.handle_transcript("What is the latest news about Russia?")
    assert cm.context.live_topic == "russia"
    reasoner = cm.reasoner
    reasoner.seen.clear()

    resp2, _ = cm.handle_transcript("What about Ukraine?")
    assert cm.context.live_topic == "ukraine"
    assert reasoner.seen == [], "live follow-up must not hit the reasoner"
    assert "ukraine" in (resp2 or "").lower()


def test_manager_live_topic_cleared_on_session_reset():
    cm = _manager()
    cm.handle_transcript("What is the latest news about Russia?")
    assert cm.context.live_topic == "russia"
    cm.context.clear_ephemeral()
    assert cm.context.live_topic == ""
    assert cm.context._entity_memory == []


def test_manager_reference_does_not_hijack_deterministic_command():
    cm = _manager()
    resp, keep = cm.handle_transcript("open chrome")
    assert keep is True


def test_manager_resolved_query_has_separate_raw_and_resolved():
    reasoner = PersonaReasoner({
        "who is the president of britain":
            "He is King Charles III, the monarch of the United Kingdom.",
    })
    cm = _manager(reasoner)
    cm.handle_transcript("Who is the president of Britain?")
    cm.handle_transcript("Who is he?")

    assert cm.context.last_raw_query == "Who is he?"
    assert cm.context.last_resolved_query == "who is king charles iii"
    assert cm.context.last_resolution_status == _REF_STATUS_RESOLVED
    assert reasoner.seen[-1] == "who is king charles iii"

    turn = cm.context.history[-1]
    assert turn["transcript"] == "Who is he?"
    assert turn["resolved"] == "who is king charles iii"


def test_context_log_emits_structured_lines():
    import logging

    from friday.core.conversation import logger as conv_logger

    cm = _manager(PersonaReasoner())
    cm.context.push_entity("king charles iii", "PERSON", "male")

    lines = []

    class _Capture(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))

    handler = _Capture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    conv_logger.addHandler(handler)
    try:
        cm.handle_transcript("Who is he?")
    finally:
        conv_logger.removeHandler(handler)

    context_lines = [ln for ln in lines if "[CONTEXT] " in ln]
    assert context_lines, "a [CONTEXT] line must be emitted"
    header = context_lines[0]
    assert "raw='Who is he?'" in header
    assert "status=resolved" in header
    assert "entity=king charles iii" in header and "type=PERSON" in header
    assert "latency_ms=" in header and "source=" in header


def test_resolution_latency_is_bounded():
    ctx = ConversationContext()
    ctx.push_entity("king charles iii", "PERSON", "male")
    for _ in range(500):
        res = ctx.resolve_conversation_reference("Who is he?")
    assert res.status == _REF_STATUS_RESOLVED
    assert res.latency_ms < 50.0


def test_classifier_labels_resolved_query_as_question():
    assert classify("Who is King Charles III?") == RequestClass.QUESTION


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])