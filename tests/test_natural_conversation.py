"""
REGRESSION - Natural Conversation Layer (deterministic local chatter).

Guarantees pinned here:

  * pure greetings / wellbeing / thanks / ack / feedback / farewells are
    answered locally, with NO reasoner, RAG, research or browser call
  * the existing deterministic response contracts survive
    (greeting starts with "Hello", thanks == "You're welcome!")
  * compound utterances are handled ONLY when every segment is conversational
  * anything carrying a substantive request (question, command, entity,
    context-dependent follow-up) is handed back to the normal pipeline
  * the raw utterance is never rewritten
  * feature flag + env override, metrics and logging contract

No LLM, no network, no llama.cpp server.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.core.conversation import ConversationManager
from friday.core.natural_conversation import (
    ACKNOWLEDGEMENT,
    GOODBYE,
    GREETING,
    NEGATIVE_FEEDBACK,
    POSITIVE_FEEDBACK,
    THANKS,
    WELLBEING,
    NaturalConversationRouter,
)


class RecordingReasoner:
    """Records (transcript, mode) per call; returns a canned answer."""

    def __init__(self):
        self.seen = []
        self.modes = []

    def is_available(self):
        return True

    def request(self, transcript, context=None, mode="action", **kwargs):
        self.seen.append(transcript)
        self.modes.append(mode)
        return {"type": "response", "text": "REASONER-ANSWER"}


def make_router(**kwargs):
    return NaturalConversationRouter(**kwargs)


def make_manager(reasoner=None, **kwargs):
    manager = ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=reasoner or RecordingReasoner(),
        **kwargs,
    )
    manager.start_session()
    return manager


# ---------------------------------------------------------------------------
# 1. basic intent coverage
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "hi", "hello", "hey", "hey friday", "good morning", "good evening",
    "hi there", "morning", "howdy",
])
def test_greetings_handled_locally(text):
    result = make_router().route(text)
    assert result is not None and result.handled
    assert result.intent == GREETING
    assert result.response


@pytest.mark.parametrize("text", [
    "how are you?", "how are you doing", "how's it going?", "how is it going",
    "are you okay?", "how you doing?", "you doing okay", "everything okay?",
])
def test_wellbeing_handled_locally(text):
    result = make_router().route(text)
    assert result is not None and result.handled
    assert result.intent == WELLBEING
    assert result.response


@pytest.mark.parametrize("text", [
    "thanks", "thank you", "thanks a lot", "thank you very much",
    "much appreciated", "appreciate it", "that is helpful", "that helped",
    "you are the best",
])
def test_thanks_handled_locally(text):
    result = make_router().route(text)
    assert result is not None and result.handled
    assert result.intent == THANKS
    assert result.response


@pytest.mark.parametrize("text", [
    "okay", "ok", "sure", "got it", "gotcha", "understood", "roger", "noted",
    "sounds good", "will do",
])
def test_acknowledgements_handled_locally(text):
    result = make_router().route(text)
    assert result is not None and result.handled
    assert result.intent == ACKNOWLEDGEMENT
    assert result.response


@pytest.mark.parametrize("text", [
    "nice", "great", "awesome", "amazing", "perfect", "excellent", "cool",
    "that's great", "that is good", "sounds great", "love it", "looks good",
])
def test_positive_feedback_handled_locally(text):
    result = make_router().route(text)
    assert result is not None and result.handled
    assert result.intent == POSITIVE_FEEDBACK
    assert result.response


@pytest.mark.parametrize("text", [
    "bye", "bye friday", "goodbye", "good bye", "see you", "see you later",
    "see ya later", "chat later", "talk to you later", "catch you later",
])
def test_goodbyes_handled_locally(text):
    result = make_router().route(text)
    assert result is not None and result.handled
    assert result.intent == GOODBYE
    assert result.response


@pytest.mark.parametrize("text", [
    "ugh", "oh no", "no way", "that's bad", "that is not good", "not good",
    "that's unfortunate", "too bad", "that sucks", "oh man", "ah man",
])
def test_negative_feedback_handled_locally(text):
    result = make_router().route(text)
    assert result is not None and result.handled
    assert result.intent == NEGATIVE_FEEDBACK
    assert result.response


# ---------------------------------------------------------------------------
# 2. normalization / phrasing variants
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Hey Friday, how's it going?", WELLBEING),
    ("um, hi.", GREETING),
    ("Thank you so much!", THANKS),
    ("okay, thanks!", THANKS),
    ("Ok.", ACKNOWLEDGEMENT),
    ("HI!!!", GREETING),
    ("  hi  ", GREETING),
    ("well, hello there", GREETING),
    ("friday, thanks", THANKS),
])
def test_normalization_variants(text, expected):
    result = make_router().route(text)
    assert result is not None and result.handled
    assert result.intent == expected


def test_raw_text_is_never_rewritten():
    raw = "Hey Friday, how's it going?"
    result = make_router().route(raw)
    assert result.raw_text == raw
    assert result.normalized_text != raw
    assert raw == "Hey Friday, how's it going?"


def test_normalize_keeps_tokens_inside_names():
    # A dot inside a token must not split the utterance into bogus segments.
    assert make_router().normalize("Node.js") == "node js"
    assert "|" not in make_router().normalize("Node.js")
    # Punctuation between clauses IS a segment boundary.
    assert make_router().normalize("hi, how are you?") == "hi | how are you"


# ---------------------------------------------------------------------------
# 3. compound utterances - all-or-nothing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("hi, how are you?", WELLBEING),
    ("thanks, bye", GOODBYE),
    ("hello, how are you?", WELLBEING),
    ("hi and thanks", THANKS),
    ("thanks and bye", GOODBYE),
])
def test_pure_conversational_compounds_handled(text, expected):
    result = make_router().route(text)
    assert result is not None and result.handled
    assert result.intent == expected


@pytest.mark.parametrize("text", [
    "okay tell me about Russia",
    "okay, what is Node.js?",
    "thanks, search for Python 3.14",
    "nice, explain React hooks",
    "great, who is the president of Russia?",
    "hi, what time is it?",
    "thanks, open chrome",
    "good morning, open chrome",
    "hello, what's the weather today?",
    "cool, give me a summary of that",
])
def test_compound_with_substantive_request_not_handled(text):
    assert make_router().route(text) is None


# ---------------------------------------------------------------------------
# 4. never steal the pipeline's work
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "",
    "tell me more",
    "what is this?",
    "what is Node.js?",
    "who is the president of Russia?",
    "what is the latest Python version?",
    "so what about Ukraine?",
    "open chrome",
    "search for Python",
    "play kalyani song on youtube",
    "set volume to 50",
    "what did we do so far?",
    "yes",
    "no",
    "help",
    "cancel",
    "can you tell me the time?",
    "what is 2 plus 2",
    "yes tell me more about it",
])
def test_substantive_utterances_are_not_handled(text):
    assert make_router().route(text) is None


def test_node_man_utterance_is_not_handled():
    """Section 17: the full utterance must reach context resolution."""
    text = (
        "can you tell me about it? freddened like node man. "
        "what is node man? what's the purpose of using it?"
    )
    assert make_router().route(text) is None


def test_good_night_is_not_stolen_from_existing_ack():
    # "good night" keeps the pre-existing conversational-ack behaviour.
    assert make_router().route("good night") is None
    manager = make_manager()
    response, _ = manager.handle_transcript("good night")
    assert "night" in response.lower()


# ---------------------------------------------------------------------------
# 5. response contracts
# ---------------------------------------------------------------------------
def test_existing_response_contracts_preserved():
    router = make_router()
    assert router.route("hello").response.startswith("Hello")
    assert router.route("thanks").response == "You're welcome!"


def test_responses_rotate_instead_of_repeating_exactly():
    router = make_router()
    seen = [router.route("thanks").response for _ in range(4)]
    assert len(set(seen)) > 1
    assert all(seen)


def test_selector_injection():
    router = make_router(selector=lambda intent, pool: f"<{intent}>")
    result = router.route("hi")
    assert result.response == f"<{GREETING}>"


# ---------------------------------------------------------------------------
# 6. configuration
# ---------------------------------------------------------------------------
def test_disabled_router_never_handles():
    router = make_router(enabled=False)
    assert router.route("hi") is None
    assert router.route("thanks") is None


def test_config_enabled_default_true():
    assert NaturalConversationRouter.from_config({}).enabled is True
    assert NaturalConversationRouter.from_config(None).enabled is True
    assert NaturalConversationRouter.from_config(
        {"natural_conversation": {}}
    ).enabled is True


def test_config_disable():
    assert NaturalConversationRouter.from_config(
        {"natural_conversation": {"enabled": False}}
    ).enabled is False


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("off", False),
])
def test_env_override(value, expected, monkeypatch):
    monkeypatch.setenv("FRIDAY_NATURAL_CONVERSATION_ENABLED", value)
    router = NaturalConversationRouter.from_config(
        {"natural_conversation": {"enabled": not expected}}
    )
    assert router.enabled is expected


def test_env_override_wins_over_config(monkeypatch):
    monkeypatch.setenv("FRIDAY_NATURAL_CONVERSATION_ENABLED", "false")
    assert NaturalConversationRouter.from_config(
        {"natural_conversation": {"enabled": True}}
    ).enabled is False
    monkeypatch.setenv("FRIDAY_NATURAL_CONVERSATION_ENABLED", "true")
    assert NaturalConversationRouter.from_config(
        {"natural_conversation": {"enabled": False}}
    ).enabled is True


def test_shipped_config_enables_the_layer():
    import yaml
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, "config.yaml"), encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    assert "natural_conversation" in config
    assert NaturalConversationRouter.from_config(config).enabled is True


# ---------------------------------------------------------------------------
# 7. metrics + logging
# ---------------------------------------------------------------------------
def test_metrics_snapshot_contract():
    router = make_router()
    router.route("hi")
    router.route("how are you?")
    router.route("what is the latest Python version?")
    snapshot = router.metrics.snapshot()
    for key in (
        "natural_chat_count",
        "natural_chat_llm_bypass_count",
        "natural_chat_latency_ms_total",
        "natural_chat_latency_ms_avg",
        "natural_chat_latency_ms_max",
        "natural_chat_rejected_count",
    ):
        assert key in snapshot
    assert snapshot["natural_chat_count"] == 2
    assert snapshot["natural_chat_llm_bypass_count"] == 2
    assert snapshot["natural_chat_rejected_count"] == 1
    assert snapshot["natural_chat_latency_ms_max"] >= 0.0
    assert router.metrics.by_intent[GREETING] == 1


def test_logging_contract():
    from unittest import mock

    from friday.core import natural_conversation as nc

    router = make_router()
    with mock.patch.object(nc.logger, "info") as info:
        router.route("how are you?")
    assert info.called
    message = info.call_args[0][0] % info.call_args[0][1:]
    assert "[NATURAL_CHAT]" in message
    assert f"intent={WELLBEING}" in message
    assert "handled=true" in message


# ---------------------------------------------------------------------------
# 8. manager integration - LLM bypass
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "hi", "hello", "hey friday", "good morning", "how are you?", "how's it going",
    "thanks", "thank you", "okay", "got it", "nice", "great", "bye friday",
    "see you later", "that's bad", "ugh", "hi, how are you?", "thanks, bye",
])
def test_manager_answers_locally_without_reasoner(text):
    reasoner = RecordingReasoner()
    manager = make_manager(reasoner)
    response, keep_going = manager.handle_transcript(text)
    assert reasoner.seen == []
    assert response
    assert keep_going is True


def test_manager_metrics_count_the_bypass():
    reasoner = RecordingReasoner()
    router = make_router()
    manager = make_manager(reasoner, natural_conversation_router=router)
    manager.handle_transcript("how are you?")
    snapshot = router.metrics.snapshot()
    assert snapshot["natural_chat_count"] == 1
    assert snapshot["natural_chat_llm_bypass_count"] == 1
    assert reasoner.seen == []


@pytest.mark.parametrize("text", [
    "okay tell me about Russia",
    "thanks, search for Python 3.14",
    "what is Node.js?",
    "tell me more",
])
def test_manager_defers_substantive_requests(text):
    reasoner = RecordingReasoner()
    manager = make_manager(reasoner)
    manager.handle_transcript(text)
    assert reasoner.seen, f"expected the reasoner to see {text!r}"


def test_manager_disabled_layer_uses_pipeline():
    reasoner = RecordingReasoner()
    manager = make_manager(reasoner, natural_conversation_enabled=False)
    response, _ = manager.handle_transcript("how are you?")
    assert len(reasoner.seen) == 1
    # the pipeline hands the reasoner its cleaned query, not the raw chatter
    assert reasoner.seen[0] == "how are you"
    assert response == "REASONER-ANSWER"


def test_manager_does_not_touch_commands():
    reasoner = RecordingReasoner()
    manager = make_manager(reasoner)
    response, _ = manager.handle_transcript("open chrome")
    assert reasoner.seen == []
    assert "chrome" in response.lower()


def test_manager_records_local_response_in_context():
    manager = make_manager()
    response, _ = manager.handle_transcript("how are you?")
    assert manager.context.last_response == response
    assert manager.context.history


def test_layer_is_enabled_by_default():
    manager = make_manager()
    assert manager.natural_conversation_enabled is True
    assert manager.natural_conversation_router is not None


def test_local_latency_is_sub_millisecond():
    """The deterministic path itself must be sub-millisecond (no model call)."""
    import time
    from unittest import mock

    from friday.core import natural_conversation as nc

    router = make_router()
    samples = []
    with mock.patch.object(nc.logger, "info"):  # exclude sink I/O noise
        for _ in range(50):
            started = time.perf_counter()
            assert router.route("how are you?").handled
            samples.append((time.perf_counter() - started) * 1000.0)
    samples.sort()
    assert samples[len(samples) // 2] < 1.0
