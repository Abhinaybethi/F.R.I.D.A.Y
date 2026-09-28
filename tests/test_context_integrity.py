"""
REGRESSION — conversation-context integrity, routing and empty-content fixes.

Pins the Phase-3 pre-requisite work:

  * no garbage entity ingestion ("president it", "the those president",
    "who is most favorable country in this war" as an EVENT)
  * no blind demonstrative substitution ("... in this war war", "in most
    favorable country in most favorable country in ...")
  * no query accumulation (a resolved query never re-embeds an earlier
    question's wording)
  * role-ellipsis / demonstrative-head build clean role-of questions
  * informational follow-ups route CHAT, tool commands still route ACTION
  * research receives the *resolved* query, never the raw corrupt one
  * llama.cpp empty content (null content / reasoning_content / finish_reason)

No LLM, no network, no llama.cpp server.
"""
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.core.conversation import (
    ConversationContext,
    ConversationManager,
    _REF_STATUS_NOT_NEEDED,
    _REF_STATUS_RESOLVED,
)
from friday.intent.classifier import RequestClass, classify
from friday.intent.router import Action, route
from friday.planning.context_resolver import ShortTermContext


class RecordingReasoner:
    """Records (transcript, mode) per call; returns a canned answer."""

    def __init__(self, responses=None):
        self.seen = []
        self.modes = []
        self.responses = responses or {}

    def is_available(self):
        return True

    def request(self, transcript, context=None, mode="action", **kwargs):
        self.seen.append(transcript)
        self.modes.append(mode)
        low = (transcript or "").lower()
        for prefix, text in self.responses.items():
            if low.startswith(prefix):
                return {"type": "response", "text": text}
        return {"type": "response", "text": "Understood."}


class StubResearchAgent:
    """Records the query handed to the research subsystem."""

    enabled = True

    def __init__(self, needs_web=False):
        self.seen = []
        self._needs_web = needs_web

    def research(self, query):
        self.seen.append(query)
        results = []
        if self._needs_web:
            results = [SimpleNamespace(title="Result A", url="http://a", snippet="s")]
        return SimpleNamespace(
            needs_web=self._needs_web,
            success=True,
            results=results,
            decision=SimpleNamespace(reason="stub"),
        )


def _manager(reasoner=None, **kwargs):
    cm = ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=reasoner or RecordingReasoner(),
        **kwargs,
    )
    cm.start_session()
    return cm


def _names(ctx):
    return [e["name"] for e in ctx._entity_memory]


# ---------------------------------------------------------------------------
# 1. Garbage entity ingestion must not happen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("transcript,banned", [
    ("who is the president it", "president it"),
    ("who are those president", "those president"),
    ("who is most favorable country in this war", "most favorable country"),
    ("What did he do before becoming president?", "becoming president"),
    ("who is he", "who is he"),
    ("why did that happen", "that happen"),
])
def test_non_entity_predicates_never_enter_memory(transcript, banned):
    ctx = ConversationContext()
    ctx.observe_turn(transcript)
    for name in _names(ctx):
        assert banned not in name, f"{transcript!r} polluted memory with {name!r}"


def test_verb_phrase_is_not_ingested_as_event():
    ctx = ConversationContext()
    ctx.observe_turn("who is the most recent winner of the final match?")
    for e in ctx._entity_memory:
        assert e["type"] != "EVENT" or "winner" not in e["name"]


def test_legitimate_role_and_event_still_ingested():
    ctx = ConversationContext()
    ctx.observe_turn("Who is the president of Russia?")
    assert "the president of russia" in _names(ctx)
    assert "russia" in _names(ctx)

    ctx2 = ConversationContext()
    ctx2.observe_turn("The Russia-Ukraine war has continued for years.")
    assert any("russia-ukraine war" in n for n in _names(ctx2))


def test_tell_me_about_keeps_event_name_only():
    ctx = ConversationContext()
    ctx.observe_turn("Tell me about the Russia Ukraine war")
    names = _names(ctx)
    assert "russia ukraine war" in names
    for name in names:
        assert "tell me about" not in name, f"utterance leaked into {name!r}"
        assert "russia ukraine" != name, "event fragment demoted to a bare PERSON"


# ---------------------------------------------------------------------------
# 2. Blind demonstrative substitution must not happen
# ---------------------------------------------------------------------------

def test_demonstrative_with_head_noun_is_not_substituted():
    ctx = ConversationContext()
    ctx.observe_turn("Tell me about Russia")
    ctx.push_entity("russia-ukraine war", "EVENT")

    res = ctx.resolve_conversation_reference("who is most favorable country in this war")
    assert res.status in (_REF_STATUS_RESOLVED, _REF_STATUS_NOT_NEEDED)
    assert "war war" not in res.resolved
    assert "in this war war" not in res.resolved
    assert res.resolved.count("in this war") <= 1
    assert "most favorable country in most favorable country" not in res.resolved


def test_object_position_demonstrative_still_resolves():
    ctx = ConversationContext()
    ctx.observe_turn("The Russia-Ukraine war has continued for years.")

    res = ctx.resolve_conversation_reference("why did that happen")
    assert res.status == _REF_STATUS_RESOLVED
    assert "russia-ukraine war" in res.resolved
    assert "that" not in res.resolved


def test_rewrite_followup_does_not_append_noun_head_demonstrative():
    ctx = ConversationContext()
    ctx.update_topic("Tell me about the Russia Ukraine war")
    out = ctx.rewrite_followup(
        "who is most favorable country in this war",
        history=[{"transcript": "tell me about the russia ukraine war"}],
    )
    assert "war war" not in out
    assert "in most favorable country" not in out
    assert "russia ukraine war)" not in out, "previous question must not be appended"


def test_self_substitution_is_banned():
    ctx = ConversationContext()
    out = ctx._apply_ref("tell me more about this", "this", "in this war")
    assert out == "tell me more about this"


# ---------------------------------------------------------------------------
# 3. No query accumulation
# ---------------------------------------------------------------------------

def test_resolved_query_never_re_embeds_previous_question():
    ctx = ConversationContext()
    ctx.observe_turn("who is the president of britain")
    ctx.push_entity("king charles iii", "PERSON", "male")

    res = ctx.resolve_conversation_reference("who is the president")
    assert res.resolved == "who is the president of britain"


def test_bare_role_question_does_not_append_prior_turn():
    ctx = ConversationContext()
    ctx.observe_turn("Tell me about Russia")
    history = [
        {"transcript": "Who is the president of Russia?"},
        {"transcript": "Tell me more about him"},
    ]
    out = ctx.rewrite_followup("who is the president", history=history)
    assert "tell me more about him" not in out
    assert "(" not in out


# ---------------------------------------------------------------------------
# 4. Role ellipsis + demonstrative head build clean questions
# ---------------------------------------------------------------------------

def test_bare_role_question_becomes_role_of_anchor():
    ctx = ConversationContext()
    ctx.observe_turn("Who is the president of Russia?")
    ctx.observe_turn("Who is the president")

    res = ctx.resolve_conversation_reference("Who is the president")
    assert res.status == _REF_STATUS_RESOLVED
    assert res.resolved == "who is the president of russia"
    assert res.entity == "russia"
    assert res.source == "role-ellipsis"


def test_plural_role_ellipsis_with_event_anchor():
    ctx = ConversationContext()
    ctx.observe_turn("Tell me about the Russia Ukraine war")

    res = ctx.resolve_conversation_reference("who are the presidents")
    assert res.status == _REF_STATUS_RESOLVED
    assert res.resolved == "who are the presidents of russia ukraine war"
    assert "presidents presidents" not in res.resolved


def test_demonstrative_role_head_resolves_to_clean_question():
    ctx = ConversationContext()
    ctx.observe_turn("Who is the president of Russia?")

    res = ctx.resolve_conversation_reference("who are those president")
    assert res.status == _REF_STATUS_RESOLVED
    assert res.resolved == "who is the president of russia"
    assert "the the" not in res.resolved
    assert "those" not in res.resolved

    res2 = ctx.resolve_conversation_reference("who are those countries president")
    assert res2.resolved == "who are the presidents of russia"
    assert "those" not in res2.resolved


def test_role_question_without_anchor_is_left_alone():
    ctx = ConversationContext()
    res = ctx.resolve_conversation_reference("Who is the president?")
    assert res.status == _REF_STATUS_NOT_NEEDED
    assert res.resolved == "Who is the president?"


# ---------------------------------------------------------------------------
# 5. Structured state is clean and cleared with the session
# ---------------------------------------------------------------------------

def test_structured_state_fields_populated():
    cm = _manager(RecordingReasoner({
        "who is the president of britain": "He is King Charles III.",
    }))
    cm.handle_transcript("Who is the president of Britain?")
    cm.handle_transcript("Who is he?")

    ctx = cm.context
    assert ctx.active_entity == "king charles iii"
    assert ctx.active_entity_type == "PERSON"
    assert ctx.active_question_type in ("QUESTION", "FOLLOW_UP")
    assert "?" not in ctx.active_entity
    assert "tell me" not in ctx.active_entity

    cm.context.clear_ephemeral()
    assert ctx.active_entity == ""
    assert ctx.active_entity_type == ""
    assert ctx.active_question_type == ""


# ---------------------------------------------------------------------------
# 6. Routing: informational -> CHAT, tool command -> ACTION
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("tell me more about him", RequestClass.FOLLOW_UP),
    ("tell me more about it", RequestClass.FOLLOW_UP),
    ("who is the president", RequestClass.QUESTION),
    ("who are those president", RequestClass.QUESTION),
])
def test_informational_phrasing_never_routes_to_action(phrase, expected):
    cls = classify(phrase)
    assert cls == expected, f"{phrase!r} must classify as {expected}, got {cls}"
    assert cls not in (RequestClass.UNKNOWN, RequestClass.COMMAND)
    assert route(phrase).action == Action.UNKNOWN


def test_informational_followup_uses_chat_mode_never_action():
    reasoner = RecordingReasoner({
        "who is the president of britain": "He is King Charles III.",
    })
    cm = _manager(reasoner)
    cm.handle_transcript("Who is the president of Britain?")
    reasoner.seen.clear()
    reasoner.modes.clear()

    cm.handle_transcript("Tell me more about him")
    assert reasoner.seen == ["tell me more about king charles iii"]
    assert set(reasoner.modes) == {"chat"}, "informational follow-up must use CHAT mode"


def test_reasoner_fallback_never_uses_action_mode():
    reasoner = RecordingReasoner()
    cm = _manager(reasoner)
    for phrase in ("more about him", "and then what about it", "who is he"):
        reasoner.seen.clear()
        reasoner.modes.clear()
        cm.handle_transcript(phrase)
        assert "action" not in reasoner.modes, (
            f"{phrase!r} reached the reasoner in ACTION mode (R3)"
        )


def test_command_near_miss_stays_off_the_reasoner():
    reasoner = RecordingReasoner()
    cm = _manager(reasoner)
    for phrase in ("open grove", "open groom"):
        cm.handle_transcript(phrase)
    assert reasoner.seen == [], "command near-misses must not reach the reasoner"


def test_tool_command_still_routes_as_action():
    reasoner = RecordingReasoner()
    cm = _manager(reasoner)
    resp, keep = cm.handle_transcript("open chrome")

    assert keep is True
    assert reasoner.seen == [], "a deterministic tool command must not hit the reasoner"
    assert cm.context.last_intent is not None
    assert cm.context.last_intent.action == Action.OPEN_APP
    assert cm.context.last_intent.target == "chrome"


# ---------------------------------------------------------------------------
# 7. Research receives the resolved query
# ---------------------------------------------------------------------------

def test_research_receives_resolved_query_not_raw():
    research = StubResearchAgent()
    reasoner = RecordingReasoner({
        "who is the president of britain": "He is King Charles III.",
    })
    cm = _manager(reasoner, research_agent=research, research_enabled=True)
    cm.handle_transcript("Who is the president of Britain?")
    research.seen.clear()

    cm.handle_transcript("Tell me more about him")
    assert research.seen == ["tell me more about king charles iii"]


def test_research_disabled_is_noop():
    research = StubResearchAgent()
    cm = _manager(RecordingReasoner(), research_agent=research, research_enabled=False)
    cm.handle_transcript("Who is the current president of Russia?")
    assert research.seen == []


# ---------------------------------------------------------------------------
# 8. Full runtime sequence: no corruption anywhere
# ---------------------------------------------------------------------------

_RUNTIME_TURNS = [
    "Who is the president of Russia?",
    "Tell me more about him",
    "who is the president",
    "Tell me about the Russia Ukraine war",
    "who is most favorable country in this war",
    "who are those president",
    "open chrome",
]

_CORRUPTION_MARKERS = (
    "war war",
    "in most favorable country in most favorable country",
    "the those president",
    "president it",
    "tell me about the russia ukraine war (",
)


def test_runtime_sequence_keeps_every_resolved_query_clean():
    reasoner = RecordingReasoner({
        "who is the president of russia": "Vladimir Putin is the president of Russia.",
    })
    cm = _manager(reasoner)

    for turn in _RUNTIME_TURNS:
        cm.handle_transcript(turn)
        resolved = cm.context.last_resolved_query or turn
        low = resolved.lower()
        for marker in _CORRUPTION_MARKERS:
            assert marker not in low, f"{turn!r} -> corrupt query {resolved!r}"
        assert "  " not in resolved, f"double space in {resolved!r}"

    assert reasoner.modes and set(reasoner.modes) == {"chat"}, (
        "no informational turn may reach the ACTION reasoner"
    )
    assert cm.context.active_entity
    assert "the the" not in cm.context.active_entity


def test_runtime_sequence_resolved_queries_are_distinct():
    reasoner = RecordingReasoner({
        "who is the president of russia": "Vladimir Putin is the president of Russia.",
    })
    cm = _manager(reasoner)
    seen = []
    for turn in _RUNTIME_TURNS:
        cm.handle_transcript(turn)
        q = (cm.context.last_resolved_query or turn).strip().lower()
        if not seen or seen[-1] != q:
            seen.append(q)
    # A resolved query must not grow by re-absorbing the previous one.
    for prev, cur in zip(seen, seen[1:]):
        if prev in cur and prev != cur:
            assert not cur.endswith("(" + prev + ")"), cur


# ---------------------------------------------------------------------------
# 9. llama.cpp empty-content handling
# ---------------------------------------------------------------------------

def _reasoner():
    from friday.reasoning.llamacpp_reasoner import LlamaCppReasoner
    return LlamaCppReasoner(base_url="http://127.0.0.1:8080", model="m", timeout=5)


class _Chunked:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        return self._lines.pop(0) if self._lines else b""


def test_bulk_null_content_falls_back_to_reasoning_content():
    r = _reasoner()
    body = json.dumps({
        "choices": [{
            "message": {"content": None, "reasoning_content": "Putin is the president."},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 4},
    }).encode()
    resp = SimpleNamespace(readline=lambda: None, read=lambda: body)
    text, _p, _c, _t, _g, streamed, _h, fr = r._read_payload(resp, time.monotonic() + 2)
    assert text == "Putin is the president."
    assert streamed is False
    assert fr == "stop"


def test_sse_null_content_chunks_are_skipped_not_fatal():
    r = _reasoner()
    lines = [
        b'data: {"choices":[{"delta":{"content":null}}]}\n\n',
        b'data: {"choices":[{"delta":{"reasoning_content":"Paris "}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"is the capital."}}],"finish_reason":null}\n\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    text, _p, _c, _t, _g, streamed, _h, fr = r._read_payload(
        _Chunked(lines), time.monotonic() + 2,
    )
    assert text == "Paris is the capital."
    assert streamed is True
    assert fr == "stop"


def test_really_empty_payload_returns_unknown_with_finish_reason():
    r = _reasoner()
    lines = [
        b'data: {"choices":[{"delta":{"content":null},"finish_reason":"length"}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    text, _p, _c, _t, _g, _s, _h, fr = r._read_payload(_Chunked(lines), time.monotonic() + 2)
    assert text == ""
    assert fr == "length"


class _BulkResp:
    status = 200

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def test_request_recovers_from_null_content_bulk():
    r = _reasoner()
    r.is_available = lambda: True
    payload = {"choices": [{"message": {"content": None,
                                        "reasoning_content": "He is King Charles III."}}]}
    with mock.patch("friday.reasoning.llamacpp_reasoner.urllib.request.urlopen",
                    return_value=_BulkResp(payload)):
        out = r.request("who is the king", ShortTermContext(), mode="chat")
    assert out["type"] == "response"
    assert out["text"] == "He is King Charles III."


def test_request_returns_unknown_for_truly_empty_content():
    r = _reasoner()
    r.is_available = lambda: True
    payload = {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}
    with mock.patch("friday.reasoning.llamacpp_reasoner.urllib.request.urlopen",
                    return_value=_BulkResp(payload)):
        out = r.request("who is the king", ShortTermContext(), mode="chat")
    assert out == {"type": "unknown"}


def test_chat_mode_never_parses_structured_action_output():
    """A natural-language question in CHAT mode must not be sent through the
    ACTION structured parser (the mode-mismatch that produced empty content)."""
    r = _reasoner()
    r.is_available = lambda: True
    payload = {"choices": [{"message": {"content": "Just prose, no JSON at all."}}]}
    with mock.patch("friday.reasoning.llamacpp_reasoner.urllib.request.urlopen",
                    return_value=_BulkResp(payload)):
        out = r.request("who is the president of russia", ShortTermContext(), mode="chat")
    assert out == {"type": "response", "text": "Just prose, no JSON at all."}


# ---------------------------------------------------------------------------
# Section 17: same-turn repeated topic beats older structured context
# ---------------------------------------------------------------------------
_NODE_MAN = (
    "can you tell me about it? freddened like node man. "
    "what is node man? what's the purpose of using it?"
)


def test_node_man_utterance_binds_trailing_its_to_same_turn_topic():
    ctx = ConversationContext()
    # Structured context already holds a *different* entity.
    ctx.observe_turn("who is the president of russia")
    res = ctx.resolve_conversation_reference(_NODE_MAN)
    low = res.resolved.lower()
    assert "node man" in low
    assert "russia" not in low
    assert res.entity == "node man"
    assert res.source == "same-turn-anchor"


def test_node_man_utterance_reaches_the_pipeline_in_full():
    reasoner = RecordingReasoner()
    manager = ConversationManager(
        dry_run=True, allow_real_execution=False, reasoner=reasoner,
    )
    manager.start_session()
    manager.handle_transcript(_NODE_MAN)
    assert reasoner.seen, "the full utterance must reach the reasoner"
    seen = reasoner.seen[-1].lower()
    assert "freddened like node man" in seen
    assert "purpose of using node man" in seen


def test_same_turn_anchor_ignores_single_mention():
    ctx = ConversationContext()
    res = ctx.resolve_conversation_reference(
        "what is node js? tell me about it",
    )
    assert res.source != "same-turn-anchor"


def test_same_turn_anchor_keeps_person_ambiguity_rules():
    ctx = ConversationContext()
    ctx.observe_turn("tell me about vladimir putin")
    ctx.observe_turn("tell me about keir starmer")
    res = ctx.resolve_conversation_reference("who is he? what is it about him?")
    assert res.status != _REF_STATUS_RESOLVED or res.entity != "node man"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])
