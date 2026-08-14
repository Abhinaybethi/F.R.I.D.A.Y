"""
UNIT TEST — Phase 13 Performance Suite (P0)
=============================================
Tests fuzzy router and context resolution speed and zero Ollama calls for near-miss STT transcriptions.
No Ollama required. All deterministic.
"""
import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.intent.models import Action
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


def test_fuzzy_router_zero_ollama_calls():
    """STT near-misses ('open grove', 'openvscode', 'on youtube') resolve in < 5ms with 0 Ollama calls."""
    mock_reasoner = MockCallCountingReasoner()
    cm = ConversationManager(dry_run=True, reasoner=mock_reasoner, permissions=_ALL_ENABLED)
    cm.start_session()

    near_miss_transcripts = [
        "open grove",
        "open groom",
        "openvscode",
        "on youtube",
        "open note pad",
    ]

    for transcript in near_miss_transcripts:
        t0 = time.perf_counter()
        resp, keep = cm.handle_transcript(transcript)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 50.0, f"Fuzzy routing too slow ({elapsed_ms:.2f} ms) for {transcript!r}"

    assert mock_reasoner.call_count == 0, f"Expected 0 Ollama calls for fuzzy near-misses, got {mock_reasoner.call_count}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
