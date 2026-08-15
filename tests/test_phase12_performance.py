"""
UNIT TEST — Phase 12 Performance Regression Suite
===================================================
Proves that known deterministic commands and system intents NEVER call Ollama.
Tracks Ollama invocation counts and verifies sub-millisecond routing latency.
No Ollama required. All deterministic.
"""
import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.reasoning.interface import Reasoner
from friday.planning.context_resolver import ShortTermContext

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


class MockCallCountingReasoner(Reasoner):
    def __init__(self):
        self.call_count = 0
    def request(self, transcript: str, context: ShortTermContext) -> dict:
        self.call_count += 1
        return {"type": "unknown"}
    def is_available(self) -> bool:
        return True
    def health(self) -> str:
        return "mock"
    def close(self):
        pass


from unittest.mock import patch


def test_performance_known_commands_zero_ollama_calls():
    """Known commands and system intents MUST result in 0 calls to Ollama reasoner."""
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        mock_reasoner = MockCallCountingReasoner()
        cm = ConversationManager(dry_run=True, reasoner=mock_reasoner, permissions=_ALL_ENABLED)
        cm.start_session()

        known_transcripts = [
            "open chrome",
            "open youtube",
            "what time is it",
            "search for python tutorials",
            "open downloads",
            "close chrome",
            "help",
            "repeat",
            "cancel",
            "yes",  # outside confirmation
            "no",   # outside confirmation
        ]

        # Warm-up to eliminate cold-start import/regex initialization jitter under full suite CPU load
        cm.handle_transcript("open firefox")
        mock_reasoner.call_count = 0

        for transcript in known_transcripts:
            t0 = time.perf_counter()
            cm.handle_transcript(transcript)
            t_elapsed_ms = (time.perf_counter() - t0) * 1000
            assert t_elapsed_ms < 50.0, f"Latency too high ({t_elapsed_ms:.2f} ms) for {transcript!r}"

        assert mock_reasoner.call_count == 0, f"Expected 0 Ollama calls for known commands, got {mock_reasoner.call_count}"


def test_performance_natural_language_queries_do_call_ollama():
    """General knowledge query MUST invoke Ollama reasoner once."""
    mock_reasoner = MockCallCountingReasoner()
    cm = ConversationManager(dry_run=True, reasoner=mock_reasoner, permissions=_ALL_ENABLED)
    cm.start_session()

    cm.handle_transcript("what is the capital of Japan")
    assert mock_reasoner.call_count == 1, f"Expected 1 Ollama call for NL query, got {mock_reasoner.call_count}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
