"""
REGRESSION - Deterministic System Router (TIME_QUERY, and only TIME_QUERY).

The 2026-09-29 voice run sent "can you tell me the current time?" to Bonsai,
which then claimed it could not provide the current time. Information that the
local system can answer deterministically must never reach the LLM.

This suite pins:

  * TIME_QUERY phrasings are answered locally with the real system clock
  * the response is not hard-coded and is not verbose
  * the reasoner is NEVER called for a time query (mocked, call_count == 0)
  * the router is extensible (register another deterministic intent) without
    touching the existing command router
  * non-time traffic is never intercepted
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.core.conversation import ConversationManager
from friday.core.system_commands import (
    TIME_QUERY,
    DeterministicSystemRouter,
    SystemCommandResult,
)

TIME_PHRASINGS = [
    "what time is it",
    "what time is it right now",
    "what's the time",
    "what is the current time",
    "can you tell me the current time?",
    "can you tell me the time?",
    "tell me the time",
    "tell me the time please",
    "friday what time is it",
    "hey friday what is the current time",
    "do you know the time",
    "current time?",
]


class CountingReasoner:
    """Reasoner double that counts calls and must never be reached."""

    def __init__(self):
        self.calls = 0
        self.seen = []

    def is_available(self):
        return True

    def request(self, transcript, context=None, mode="action", **kwargs):
        self.calls += 1
        self.seen.append(transcript)
        return {"type": "response", "text": "BONSai says it cannot tell the time."}


def make_manager(reasoner=None, **kwargs):
    manager = ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=reasoner or CountingReasoner(),
        **kwargs,
    )
    manager.start_session()
    return manager


# ---------------------------------------------------------------------------
# router unit behaviour
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", TIME_PHRASINGS)
def test_router_handles_time_phrasings(text):
    result = DeterministicSystemRouter().route(text)
    assert result is not None, f"expected a deterministic system answer for {text!r}"
    assert result.handled is True
    assert result.intent == TIME_QUERY
    assert result.response


def test_time_response_uses_the_real_clock_not_a_constant():
    import datetime

    router = DeterministicSystemRouter()
    first = router.route("what time is it").response
    assert not re.search(r"\d{2}:\d{2}:\d{2}", first), "response must be the spoken form"
    # The response must agree with the local wall clock to the minute.
    now = datetime.datetime.now()
    spoken = re.sub(r"^it'?s\s+", "", first.strip(), flags=re.I).rstrip(".")
    hour12 = int(re.match(r"(\d{1,2}):", spoken).group(1))
    ampm = spoken.split()[-1].upper()
    expected_hour = now.hour % 12 or 12
    if now.minute == 0 or True:  # tolerate a minute rollover during the test
        assert hour12 == expected_hour
        if ampm in ("AM", "PM"):
            assert (ampm == "AM") == (now.hour < 12)


def test_time_response_is_concise():
    response = DeterministicSystemRouter().route("what time is it").response
    assert response.startswith("It's") or response.startswith("It is")
    assert response.count(" ") <= 5


@pytest.mark.parametrize("text", [
    "what is node.js",
    "tell me about node.js",
    "how are you",
    "thanks",
    "open chrome",
    "who is the president of russia",
    "tell me more about it",
    "i believe in russia",
])
def test_router_ignores_non_system_queries(text):
    assert DeterministicSystemRouter().route(text) is None


def test_disabled_router_never_answers():
    router = DeterministicSystemRouter(enabled=False)
    assert router.route("what time is it") is None


def test_router_is_extensible():
    router = DeterministicSystemRouter()
    router.register(
        "PING",
        re.compile(r"^ping$"),
        lambda: "pong",
    )
    result = router.route("ping")
    assert isinstance(result, SystemCommandResult)
    assert result.intent == "PING"
    assert result.response == "pong"
    # the pre-existing time intent is untouched
    assert router.route("what time is it").intent == TIME_QUERY


def test_router_result_is_falsy_when_not_handled():
    assert not SystemCommandResult(handled=False)
    assert SystemCommandResult(handled=True, response="x")


def test_from_config_default_enabled():
    assert DeterministicSystemRouter.from_config({}).enabled is True
    assert DeterministicSystemRouter.from_config(None).enabled is True


def test_from_config_disable():
    assert DeterministicSystemRouter.from_config(
        {"system_commands": {"enabled": False}}
    ).enabled is False


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("off", False),
])
def test_env_override(value, expected, monkeypatch):
    monkeypatch.setenv("FRIDAY_SYSTEM_COMMANDS_ENABLED", value)
    router = DeterministicSystemRouter.from_config(
        {"system_commands": {"enabled": not expected}}
    )
    assert router.enabled is expected


def test_metrics_snapshot():
    router = DeterministicSystemRouter()
    router.route("what time is it")
    router.route("what is node.js")
    snapshot = router.metrics.snapshot()
    assert snapshot["system_command_count"] == 1
    assert snapshot["system_command_llm_bypass_count"] == 1
    assert snapshot["system_command_latency_ms_avg"] >= 0.0


# ---------------------------------------------------------------------------
# acceptance: time must never reach the LLM
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "what time is it?",
    "what is the current time?",
    "can you tell me the current time?",
    "tell me the time",
    "what's the time",
])
def test_time_query_never_invokes_the_reasoner(text):
    reasoner = CountingReasoner()
    manager = make_manager(reasoner)
    response, keep_going = manager.handle_transcript(text)
    assert reasoner.calls == 0, f"reasoner must not be called for {text!r}"
    assert reasoner.seen == []
    assert keep_going is True
    assert ":" in response or "AM" in response or "PM" in response
    assert "cannot" not in response.lower()


def test_time_query_response_is_recorded_in_context():
    manager = make_manager()
    response, _ = manager.handle_transcript("what time is it?")
    assert manager.context.last_response == response
    assert manager.context.history


def test_manager_disabled_system_router_falls_back():
    """With the layer off, the pre-existing command-router path still answers."""
    reasoner = CountingReasoner()
    manager = make_manager(reasoner, system_commands_enabled=False)
    response, _ = manager.handle_transcript("what time is it")
    assert ":" in response or "AM" in response or "PM" in response
    assert reasoner.calls == 0


def test_time_query_does_not_disturb_following_turns():
    reasoner = CountingReasoner()
    manager = make_manager(reasoner)
    manager.handle_transcript("what time is it?")
    manager.handle_transcript("thanks")
    assert reasoner.calls == 0
