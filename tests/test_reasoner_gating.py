"""
UNIT TEST — Reasoner Gating Subsystem
======================================
Tests friday/reasoning/gating.py rules.
Ensures deterministic commands and system intents NEVER trigger Ollama.
No Ollama required. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.reasoning.gating import should_call_reasoner
from friday.intent.models import Action, Intent


def test_known_intent_never_calls_reasoner():
    """Known deterministic intent (OPEN_APP, SEARCH_WEB, GET_TIME) returns False."""
    intents = [
        Intent(action=Action.OPEN_APP, target="chrome"),
        Intent(action=Action.OPEN_WEBSITE, target="youtube"),
        Intent(action=Action.SEARCH_WEB, target="python"),
        Intent(action=Action.GET_TIME),
        Intent(action=Action.OPEN_FOLDER, target="downloads"),
        Intent(action=Action.CLOSE_APP, target="chrome"),
    ]
    for intent in intents:
        call, reason = should_call_reasoner("test transcript", intent, is_in_confirmation=False)
        assert call is False, f"Failed for intent {intent.action.name}: {reason}"


def test_system_commands_never_call_reasoner():
    """System commands ('help', 'repeat', 'cancel', 'stop') return False."""
    cmds = ["help", "repeat", "cancel", "never mind", "stop", "exit", "quit"]
    unknown_intent = Intent(action=Action.UNKNOWN)
    for cmd in cmds:
        call, reason = should_call_reasoner(cmd, unknown_intent, is_in_confirmation=False)
        assert call is False, f"Failed for system command {cmd!r}: {reason}"


def test_bare_confirmations_outside_confirmation_never_call_reasoner():
    """Bare 'yes', 'no' outside confirmation return False."""
    words = ["yes", "yeah", "yep", "sure", "no", "nope", "nah"]
    unknown_intent = Intent(action=Action.UNKNOWN)
    for word in words:
        call, reason = should_call_reasoner(word, unknown_intent, is_in_confirmation=False)
        assert call is False, f"Failed for bare confirmation {word!r}: {reason}"


def test_short_transcripts_never_call_reasoner():
    """Empty or 1-character transcripts return False."""
    unknown_intent = Intent(action=Action.UNKNOWN)
    for short in ["", "a", " ", "  "]:
        call, reason = should_call_reasoner(short, unknown_intent, is_in_confirmation=False)
        assert call is False, f"Failed for short transcript {short!r}: {reason}"


def test_ambiguous_nl_requests_do_call_reasoner():
    """General knowledge & complex NL queries return True."""
    queries = [
        "what is the capital of Japan",
        "explain recursion in python",
        "tell me a joke",
    ]
    unknown_intent = Intent(action=Action.UNKNOWN)
    for q in queries:
        call, reason = should_call_reasoner(q, unknown_intent, is_in_confirmation=False)
        assert call is True, f"Failed for NL query {q!r}: {reason}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
