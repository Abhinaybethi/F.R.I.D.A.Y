"""
REGRESSION - STT quality / garbage protection.

The 2026-09-29 voice run produced these transcripts and Friday treated the
noise as a factual entity:

    "can you tell me about? no jes"          -> entity "No Jes", Bonsai explained it
    "asking about not nodejs, nodejs"        -> doubled fragment
    "no jes, I mean Node.js"                 -> noisy prefix + explicit correction

Rules pinned here:

  * uncertain STT output is never turned into a confident entity
  * an ambiguous turn is clarified, never hallucinated
  * valid technical terms survive untouched (node.js / nodejs / Node JS /
    faster-whisper / llama.cpp / Friday / Python / JavaScript)
  * explicit self-correction in the same turn wins over the noisy fragment
  * no global "node.js = no jes" string replacement exists
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.core.conversation import ConversationManager
from friday.core.transcript_quality import (
    CLARIFICATION,
    assess_transcript,
)


class SpyReasoner:
    def __init__(self, text='"No Jes" is a term used in software development.'):
        self.seen = []
        self.text = text

    def is_available(self):
        return True

    def request(self, transcript, context=None, mode="action", **kwargs):
        self.seen.append(transcript)
        return {"type": "response", "text": self.text}


def make_manager(reasoner=None, **kwargs):
    manager = ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=reasoner or SpyReasoner(),
        **kwargs,
    )
    manager.start_session()
    return manager


# ---------------------------------------------------------------------------
# 1. noise alone is a clarification, not an entity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "no jes",
    "no jess",
    "node jes",
    "no jess.",
    "uh jess",
])
def test_ambiguous_noise_is_flagged(text):
    verdict = assess_transcript(text)
    assert verdict.ok is False
    assert verdict.reason
    assert verdict.clarification


@pytest.mark.parametrize("text", [
    "no jes",
    "no jess",
    "node jes",
])
def test_ambiguous_noise_never_reaches_the_reasoner(text):
    reasoner = SpyReasoner()
    manager = make_manager(reasoner)
    response, _ = manager.handle_transcript(text)
    assert reasoner.seen == [], "garbage must not be explained by the model"
    assert "no jes" not in response.lower() or "?" in response
    assert "didn't catch" in response.lower() or "say it again" in response.lower()


def test_hallucinated_entity_is_never_produced():
    reasoner = SpyReasoner()
    manager = make_manager(reasoner)
    response, _ = manager.handle_transcript("can you tell me about? no jes")
    assert "is a term" not in response.lower()
    assert "didn't catch" in response.lower() or "say it again" in response.lower()
    assert reasoner.seen == []


def test_clarification_default_text_is_available():
    assert CLARIFICATION
    assert assess_transcript("no jes").clarification == CLARIFICATION


# ---------------------------------------------------------------------------
# 2. technical terms are never discarded
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "node.js",
    "nodejs",
    "Node JS",
    "faster-whisper",
    "llama.cpp",
    "Friday",
    "Python",
    "JavaScript",
    "what is node.js",
    "tell me about node.js",
    "search for node.js tutorials",
    "open chrome",
    "what time is it",
])
def test_valid_technical_terms_pass_the_guard(text):
    verdict = assess_transcript(text)
    assert verdict.ok is True, f"{text!r} must not be flagged: {verdict.reason}"
    assert verdict.text == text


@pytest.mark.parametrize("text", [
    "what is node.js",
    "tell me about node.js",
    "node.js",
    "nodejs",
    "node js",
])
def test_node_terms_reach_the_information_path(text):
    reasoner = SpyReasoner("Node.js is a JavaScript runtime.")
    manager = make_manager(reasoner)
    manager.handle_transcript(text)
    assert reasoner.seen, f"{text!r} must reach the normal information path"
    assert "node" in reasoner.seen[-1].lower()


# ---------------------------------------------------------------------------
# 3. same-turn self-correction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("no jes, I mean Node.js", "node.js"),
    ("no jes, I mean nodejs", "nodejs"),
    ("not no jes, Node.js", "node.js"),
    ("no, Node.js", "node.js"),
    ("asking about not nodejs, nodejs", "nodejs"),
])
def test_self_correction_prefers_the_explicit_term(text, expected):
    verdict = assess_transcript(text)
    assert verdict.ok is True
    assert verdict.corrected is True
    assert expected in verdict.text.lower()
    assert "no jes" not in verdict.text.lower()


def test_self_correction_asks_when_only_noise_is_present():
    verdict = assess_transcript("no jes")
    assert verdict.ok is False
    assert verdict.clarification


def test_no_global_replacement_table_exists():
    """The fix must be contextual, not a 'node.js = no jes' substitution."""
    import inspect

    from friday.core import transcript_quality

    source = inspect.getsource(transcript_quality)
    # No string-literal rewrite of "no jes" anywhere in the resolver: the fix is
    # contextual, never a global substitution table.
    for line in source.splitlines():
        if "replace(" in line.replace(" ", ""):
            raise AssertionError(f"suspicious replacement line: {line.strip()}")


def test_corrected_text_is_used_by_the_manager():
    reasoner = SpyReasoner("Node.js is a JavaScript runtime.")
    manager = make_manager(reasoner)
    manager.handle_transcript("no jes, I mean Node.js")
    assert reasoner.seen, "the corrected topic must reach the information path"
    assert "node" in reasoner.seen[-1].lower()


def test_noise_never_becomes_a_context_entity():
    manager = make_manager()
    manager.handle_transcript("no jes")
    candidates = []
    for attr in ("_entity_candidates", "candidates"):
        value = getattr(manager.context, attr, None)
        if isinstance(value, list):
            candidates = [str(getattr(c, "name", c)) for c in value]
    assert not any("no jes" in name.lower() or "no jess" in name.lower()
                   for name in candidates)


# ---------------------------------------------------------------------------
# 4. misc guard behaviour
# ---------------------------------------------------------------------------
def test_empty_transcript_is_flagged():
    verdict = assess_transcript("   ")
    assert verdict.ok is False
    assert verdict.reason


def test_real_question_is_not_flagged():
    verdict = assess_transcript("what is the capital of France?")
    assert verdict.ok is True


def test_guard_does_not_invent_word_level_confidence():
    """The guard must not claim to have word-level STT confidence."""
    verdict = assess_transcript("what time is it")
    # No per-word probability is exposed or invented.
    fields = set(getattr(verdict, "__dataclass_fields__", {}))
    for name in fields:
        assert "word" not in name.lower()
    # The only STT signal is the optional segment-level hint, unknown by default.
    assert verdict.stt_quality_ok is None
    import inspect

    from friday.core import transcript_quality

    signature = inspect.signature(transcript_quality.assess_transcript)
    assert list(signature.parameters) == ["text", "stt_quality_ok"]


def test_segment_level_hint_is_honoured_when_provided():
    verdict = assess_transcript("open chrome", stt_quality_ok=False)
    assert verdict.ok is False
    assert verdict.reason == "stt_low_confidence"
    verdict = assess_transcript("open chrome", stt_quality_ok=True)
    assert verdict.ok is True


def test_guard_is_cheap():
    import time

    samples = []
    for _ in range(200):
        started = time.perf_counter()
        assess_transcript("can you tell me about node.js and llama.cpp please")
        samples.append((time.perf_counter() - started) * 1000.0)
    samples.sort()
    assert samples[len(samples) // 2] < 1.0
