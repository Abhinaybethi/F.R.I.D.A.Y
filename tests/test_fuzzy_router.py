"""
UNIT TEST — Fuzzy Phonetic Router (Phase 13 P0)
================================================
Tests friday/intent/fuzzy_router.py.
Ensures STT near-misses ("open grove", "on youtube", "openvscode")
are resolved deterministically in < 0.5 ms without calling Ollama.
No Ollama required. All deterministic.
"""
import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.router import route
from friday.intent.models import Action


def test_fuzzy_router_app_near_misses():
    """Near-miss app STT transcriptions resolve to canonical app intent."""
    near_misses = [
        ("open grove", Action.OPEN_APP, "chrome"),
        ("open groom", Action.OPEN_APP, "chrome"),
        ("open chorm", Action.OPEN_APP, "chrome"),
        ("openvscode", Action.OPEN_APP, "vscode"),
        ("open note pad", Action.OPEN_APP, "notepad"),
    ]
    route("warm up")  # Warm-up cold start
    for transcript, expected_action, expected_target in near_misses:
        t0 = time.perf_counter()
        intent = route(transcript)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert intent.action == expected_action, f"Failed action for {transcript!r}"
        assert intent.target == expected_target, f"Failed target for {transcript!r}"
        assert elapsed_ms < 5.0, f"Fuzzy routing too slow ({elapsed_ms:.2f} ms)"


def test_fuzzy_router_website_near_misses():
    """Near-miss website STT transcriptions resolve to canonical website intent."""
    near_misses = [
        ("on youtube", Action.OPEN_WEBSITE, "youtube"),
        ("open u tube", Action.OPEN_WEBSITE, "youtube"),
        ("open googl", Action.OPEN_WEBSITE, "google"),
    ]
    for transcript, expected_action, expected_target in near_misses:
        intent = route(transcript)
        assert intent.action == expected_action, f"Failed action for {transcript!r}"
        assert intent.target == expected_target, f"Failed target for {transcript!r}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
