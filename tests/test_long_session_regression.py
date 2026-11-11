"""
UNIT TEST — Long-session answer-replay & prompt-construction regression.

Stress-tests the conversation pipeline over alternating turns with a fully
deterministic fake reasoner (no GPU, no network, no microphone):

  * independent questions on different topics must reach the model standalone
    (never rewritten around a stale topic)
  * genuine / pronoun follow-ups must resolve to the correct referent
  * returning to an earlier topic must not inherit intermediate topics
  * prior answers must never be duplicated into the current turn's prompt
    context, and prior-answer snippets are bounded
  * similar questions that legitimately deserve the same factual answer must
    each reach the model (no client-side answer replay/suppression)

Prompt construction is tested separately from model output: the fake RAG
service records exactly the history blocks the prompt builder would receive.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.core.conversation import ConversationManager
from friday.rag.query_analyzer import _compact_conversation
from friday.reasoning.interface import Reasoner


class RecordingReasoner(Reasoner):
    """Records every transcript/context the reasoner sees; never hits a server."""

    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.seen = []
        self.contexts = []

    def is_available(self) -> bool:
        return True

    def health(self) -> str:
        return "mock"

    def request(
        self, transcript, context, mode="action", retrieval_context: str = ""
    ) -> dict:
        self.seen.append(transcript)
        self.contexts.append(context)
        text = self.answers.pop(0) if self.answers else "Understood."
        return {"type": "response", "text": text}

    def close(self):
        pass


class RecordingRAGService:
    """Stands in for RAGService; records the history handed to prompt build."""

    def __init__(self):
        self.calls = []

    class _Config:
        enabled = True

    config = _Config()

    def build_result(self, transcript, history=None):
        self.calls.append({"query": transcript, "history": list(history or [])})

        class _Result:
            no_context = True
            final_context: tuple = ()
            context_block = ""
            reason = "test-no-context"

        return _Result()


def _cm(answers=None):
    reasoner = RecordingReasoner(answers)
    rag = RecordingRAGService()
    cm = ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=reasoner,
        rag_service=rag,
    )
    cm.start_session()
    return cm, reasoner, rag


# ---------------------------------------------------------------------------
# Long alternating session
# ---------------------------------------------------------------------------


def test_fourteen_turn_alternating_session_stays_grounded():
    cm, reasoner, _ = _cm()

    turns = [
        # (transcript, substrings that MUST be in what the model receives,
        #  substrings that must NOT be there)
        ("What is F.R.I.D.A.Y.?", ["friday"], []),
        ("What backend does it use?", ["backend", "friday"], []),
        ("Why did we choose that?", ["backend", "friday"], []),
        # Independent question on a new topic: no backend leakage.
        ("What is the RAG pipeline?", ["rag pipeline"], ["backend"]),
        ("How does it index documents?", ["rag pipeline"], []),
        # Explicit switch-away, then an unrelated question.
        (
            "Actually, forget that. What is the Eiffel Tower?",
            ["eiffel tower"],
            ["rag", "backend"],
        ),
        ("How tall is it?", ["eiffel tower"], []),
        # Another independent topic.
        ("Tell me about the voice pipeline", ["voice pipeline"], ["eiffel", "backend"]),
        ("Why is it delayed?", ["voice pipeline"], []),
        # Unrelated question: topic state must not leak in.
        ("What is the Stoic concept of ataraxia?", ["ataraxia"], ["voice", "eiffel"]),
        # Return to the earlier topic by naming it explicitly.
        (
            "What backend does F.R.I.D.A.Y. use?",
            ["backend", "friday"],
            ["ataraxia", "voice"],
        ),
        ("And after the migration?", ["backend"], []),
        ("What about it?", ["backend"], []),
        # Fresh independent question at the end.
        ("What is quantum tunneling?", ["quantum tunneling"], ["backend", "voice"]),
    ]

    for transcript, must_include, must_exclude in turns:
        response, keep = cm.handle_transcript(transcript)
        assert keep is True
        assert response, f"empty response for {transcript!r}"

    # Every knowledge turn reached the model exactly once.
    assert len(reasoner.seen) == len(turns)

    for (transcript, must_include, must_exclude), seen in zip(turns, reasoner.seen):
        low = seen.lower()
        for frag in must_include:
            assert frag in low, f"{transcript!r}: model saw {seen!r}, missing {frag!r}"
        for frag in must_exclude:
            assert frag not in low, (
                f"{transcript!r}: stale topic {frag!r} leaked into {seen!r}"
            )

    # No dangling bare pronouns survive in what the model receives for
    # follow-up turns (they must be grounded, not replayed verbatim).
    followup_idxs = [1, 2, 4, 6, 8, 11, 12]
    for i in followup_idxs:
        low = reasoner.seen[i].lower()
        assert " it " not in f" {low} ".replace("? ", " ").replace(". ", " ") or any(
            frag in low
            for frag in ("friday", "backend", "rag pipeline", "eiffel", "voice")
        ), f"turn {i}: ungrounded follow-up reached the model: {reasoner.seen[i]!r}"


# ---------------------------------------------------------------------------
# Prompt-construction vs model output (answer-replay resistance)
# ---------------------------------------------------------------------------


def test_rag_history_never_contains_current_turn():
    """The current question must not be injected twice (query + context block)."""
    cm, _, rag = _cm()
    cm.handle_transcript("What is the RAG relevance gate?")
    cm.handle_transcript("What is the context compressor?")

    assert len(rag.calls) == 2
    for call in rag.calls:
        for turn in call["history"]:
            t = (turn or {}).get("transcript", "")
            assert t != call["query"], (
                f"current question {call['query']!r} leaked into RAG history"
            )


def test_prior_answers_are_bounded_snippets_never_the_whole_transcript():
    long_answer = "x" * 400
    cm, _, rag = _cm(answers=[long_answer])
    cm.handle_transcript("What is the RAG pipeline?")
    cm.handle_transcript("How does it index documents?")
    # History stores the raw response, but every prompt-visible rendering of it
    # (the RECENT CONVERSATION block via _compact_conversation) is bounded.
    history = rag.calls[-1]["history"]
    assert history, "expected prior turns in RAG history"
    first = history[0]
    assert first["response"] == long_answer  # raw retained for non-prompt uses

    from friday.rag.query_analyzer import _compact_conversation

    block = _compact_conversation(history)
    answer_line = next(ln for ln in block.splitlines() if ln.startswith("Assistant:"))
    assert len(answer_line) < 260, "RECENT CONVERSATION must bound prior answers"
    assert answer_line.endswith("...")


def test_history_is_capped_and_rag_sees_only_recent_turns():
    cm, _, rag = _cm()
    for i in range(8):
        cm.handle_transcript(f"What is topic number {i}?")

    assert len(cm.context.history) <= 5, "history must stay bounded"
    assert len(rag.calls[-1]["history"]) <= 5


def test_identical_repeated_question_reaches_model_twice():
    """Exact repetition is a legitimate ask; replay must not suppress it."""
    cm, reasoner, _ = _cm(answers=["Forty-two.", "Forty-two."])
    r1, _ = cm.handle_transcript("What is the answer to everything?")
    r2, _ = cm.handle_transcript("What is the answer to everything?")

    assert len(reasoner.seen) == 2
    assert reasoner.seen[0] == reasoner.seen[1]
    assert r1 == "Forty-two." and r2 == "Forty-two."


def test_similar_question_gets_fresh_answer_not_replayed_one():
    """A reworded question must hit the model and may share the factual answer."""
    cm, reasoner, _ = _cm(
        answers=[
            "RAG is retrieval augmented generation.",
            "RAG is retrieval augmented generation.",
        ]
    )
    r1, _ = cm.handle_transcript("What is RAG?")
    r2, _ = cm.handle_transcript("Explain RAG to me.")

    assert len(reasoner.seen) == 2
    assert reasoner.seen[1] != reasoner.seen[0]  # each query sent as asked/resolved
    assert r1 == r2  # same factual answer is legitimate, not a replay bug


def test_manager_does_not_return_cached_previous_answer():
    """A new question must never be answered client-side from the last response."""
    cm, _reasoner, _ = _cm(answers=["Paris.", "The Eiffel Tower is 330 metres."])
    a1, _ = cm.handle_transcript("What is the capital of France?")
    a2, _ = cm.handle_transcript("How tall is the Eiffel Tower?")

    assert a1 == "Paris."
    assert a2 == "The Eiffel Tower is 330 metres."
    assert a2 != a1


# ---------------------------------------------------------------------------
# _compact_conversation contract (the RECENT CONVERSATION prompt block)
# ---------------------------------------------------------------------------


def test_compact_conversation_truncates_long_answers():
    history = [
        {"transcript": "q" * 10, "response": "a" * 500},
    ]
    block = _compact_conversation(history)
    assert "Assistant: " in block
    answer_line = next(ln for ln in block.splitlines() if ln.startswith("Assistant:"))
    assert len(answer_line) < 260, "RECENT CONVERSATION must bound prior answers"
    assert block.endswith("...")


def test_compact_conversation_only_last_three_turns():
    history = [
        {"transcript": f"question {i}", "response": f"answer {i}"} for i in range(6)
    ]
    block = _compact_conversation(history)
    assert "question 2" not in block  # 3, 4, 5 are the last three
    assert "question 3" in block
    assert "question 5" in block


def test_compact_conversation_skips_malformed_turns():
    block = _compact_conversation([None, "not-a-dict", {"transcript": "hello"}])
    assert "hello" in block


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])
