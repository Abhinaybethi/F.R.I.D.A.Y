"""
UNIT TEST — Referent-resolution regression matrix.

Covers it / this / that / they / them / those across the two resolvers the
pipeline actually uses (ConversationContext.resolve_reference for the
rewrite path, resolve_conversation_reference for the chat path, and the RAG
query analyzer's follow-up expansion), including:

  * one clear antecedent
  * multiple possible antecedents  -> clarification, never a forced guess
  * no valid antecedent            -> original question preserved
  * explicit subject in question   -> question preserved
  * stale active topic conflicting with the question -> no leak
  * expletive / in-turn "it" ("What is RAG and how does it work?") -> preserved

All deterministic: no model, no network, no microphone.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.core.conversation import ConversationContext
from friday.rag.query_analyzer import analyze_query


def _ctx(topic="", entities=None, persons=None):
    ctx = ConversationContext()
    if topic:
        ctx.active_topic = topic
    for name, value in (entities or {}).items():
        ctx.entities[name] = value
    for name, kind in persons or []:
        ctx.push_entity(name, kind)
    return ctx


# ---------------------------------------------------------------------------
# resolve_reference — the rewrite-path resolver
# ---------------------------------------------------------------------------


def test_it_clear_antecedent_resolves():
    resolved, ok = _ctx(topic="python").resolve_reference("Tell me more about it")
    assert ok
    assert "python" in resolved.lower()
    assert " it" not in resolved.lower()


def test_that_clear_antecedent_resolves():
    resolved, ok = _ctx(topic="war in europe").resolve_reference("Why did that happen?")
    assert ok
    assert "war in europe" in resolved.lower()


def test_this_clear_antecedent_resolves():
    resolved, ok = _ctx(topic="python").resolve_reference("This is confusing")
    assert ok
    assert resolved.lower().startswith("python")


def test_determiner_use_is_never_substituted():
    """'this war' / 'those countries' are determiners over a noun, not referents."""
    resolved, ok = _ctx(topic="war in europe").resolve_reference("explain this war")
    assert not ok
    assert resolved == "explain this war"

    resolved, ok = _ctx(topic="europe").resolve_reference("What are those countries?")
    assert not ok
    assert resolved == "What are those countries?"


def test_no_antecedent_preserves_question():
    ctx = ConversationContext()
    resolved, ok = ctx.resolve_reference("What about it?")
    assert not ok
    assert resolved == "What about it?"

    resolved, ok = ctx.resolve_reference("Tell me more about it")
    assert not ok
    assert resolved == "Tell me more about it"


def test_explicit_subject_preserved():
    resolved, ok = _ctx(topic="python").resolve_reference("What is JWT?")
    assert not ok
    assert resolved == "What is JWT?"


def test_stale_topic_does_not_corrupt_explicit_subject():
    resolved, _ok = _ctx(topic="backend architecture").resolve_reference(
        "What is the Eiffel Tower?"
    )
    assert "backend" not in resolved.lower()


# ---------------------------------------------------------------------------
# resolve_conversation_reference — the chat-path resolver
# ---------------------------------------------------------------------------


def test_they_resolves_to_group_entity():
    ctx = _ctx(persons=[("the Beatles", "GROUP")])
    ref = ctx.resolve_conversation_reference("When did they break up?", [])
    assert ref.status == "resolved"
    assert "beatles" in ref.resolved.lower()


def test_them_resolves_to_group_entity():
    ctx = _ctx(persons=[("LED Zeppelin", "GROUP")])
    ref = ctx.resolve_conversation_reference("Tell me more about them", [])
    assert ref.status == "resolved"
    assert "led zeppelin" in ref.resolved.lower()


def test_those_without_antecedent_is_preserved():
    ctx = _ctx(topic="python releases")
    ref = ctx.resolve_conversation_reference("What are those?", [])
    assert ref.resolved == "What are those?"


def test_multiple_antecedents_is_ambiguous_not_guessed():
    ctx = _ctx(persons=[("Alice", "PERSON"), ("Bob", "PERSON")])
    ref = ctx.resolve_conversation_reference("What about him?", [])
    assert ref.status == "ambiguous"
    assert ref.clarification  # a clarification is offered


def test_no_valid_antecedent_is_unresolved_not_forced():
    ref = ConversationContext().resolve_conversation_reference(
        "Why did they do that?", []
    )
    assert ref.status == "unresolved"
    assert ref.resolved == "Why did they do that?"


def test_stale_topic_conflict_preserves_explicit_question():
    ctx = _ctx(topic="backend architecture")
    ref = ctx.resolve_conversation_reference("What is the Eiffel Tower?", [])
    assert "backend" not in ref.resolved.lower()
    assert "eiffel tower" in ref.resolved.lower()


def test_expletive_it_in_turn_question_is_preserved():
    """'What is RAG and how does it work?' — 'it' refers to RAG, not the topic."""
    for topic in ("", "backend architecture", "RAG implementation"):
        ctx = _ctx(topic=topic)
        ref = ctx.resolve_conversation_reference(
            "What is RAG and how does it work?", []
        )
        assert ref.resolved == "What is RAG and how does it work?", topic
        # never rewritten around the stale topic
        assert "backend" not in ref.resolved.lower(), topic


# ---------------------------------------------------------------------------
# RAG query analyzer — retrieval-query expansion + topic classification
# ---------------------------------------------------------------------------

_HIST_PY = [{"transcript": "what is python", "response": "a programming language"}]
_HIST_RAG = [
    {"transcript": "what is RAG", "response": "retrieval augmented generation"}
]


def test_rag_expletive_it_never_appends_unrelated_topic():
    a = analyze_query("What is RAG and how does it work?", _HIST_PY)
    assert "(what is python)" not in a.semantic_query
    assert a.semantic_query == "What is RAG and how does it work?"
    assert a.needs_rag is True
    assert a.query_type in ("technical", "factual")


def test_rag_explicit_subject_not_extended():
    a = analyze_query("What is JWT?", _HIST_PY)
    assert a.semantic_query == "What is JWT?"


def test_rag_dangling_it_still_expands():
    a = analyze_query("Which model does it use?", _HIST_PY)
    assert a.semantic_query != a.original
    assert "what is python" in a.semantic_query


@pytest.mark.parametrize(
    "question",
    [
        "Why is it slow?",
        "Why did that change?",
        "When did they release it?",
        "Tell me more about them",
        "What are those?",
        "How does this compare?",
        "Why?",
    ],
)
def test_rag_pronoun_followups_expand_with_prior_topic(question):
    a = analyze_query(question, _HIST_PY)
    assert "what is python" in a.semantic_query, question


def test_rag_topic_classification_stable():
    assert analyze_query("What is RAG and how does it work?", []).query_type in (
        "technical",
        "factual",
    )
    assert analyze_query("open chrome", []).query_type == "command"
    assert (
        analyze_query(
            "Do you remember my favorite programming language?", []
        ).query_type
        == "memory"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])
