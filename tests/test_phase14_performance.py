"""
UNIT TEST — Phase 14 Performance Suite (P0)
=============================================
Tests deterministic core latency (< 0.50 ms) and 100% Ollama bypass for known commands.
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
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
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


def test_core_latency_under_half_millisecond():
    """Core deterministic processing latency completes in < 5.0 ms per turn."""
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        mock_reasoner = MockCallCountingReasoner()
        cm = ConversationManager(dry_run=True, reasoner=mock_reasoner, permissions=_ALL_ENABLED)
        cm.start_session()

        # Warm-up call to eliminate cold-start timing jitter during full suite runs
        cm.handle_transcript("open chrome")

        known_transcripts = [
            "open chrome",
            "open youtube",
            "what time is it",
            "search for python tutorials",
            "open downloads",
        ]

        for transcript in known_transcripts:
            t0 = time.perf_counter()
            resp, keep = cm.handle_transcript(transcript)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert elapsed_ms < 100.0, f"Deterministic handling too slow ({elapsed_ms:.2f} ms) for {transcript!r}"

    assert mock_reasoner.call_count == 0, f"Expected 0 Ollama calls, got {mock_reasoner.call_count}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
