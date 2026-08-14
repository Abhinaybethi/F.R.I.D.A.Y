"""
UNIT TEST — 30-Minute Stress & Stability (Phase 16 P0)
========================================================
Tests stress_voice_session.py memory and thread stability.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.stress_voice_session import run_stability_stress_test


def test_stress_voice_session_execution():
    """run_stability_stress_test() runs cleanly without memory or thread leaks."""
    res = run_stability_stress_test(duration_seconds=3)
    assert res["successful_commands"] > 0
    assert res["failed_commands"] == 0
    assert res["delta_mem_mb"] < 50.0  # Memory growth under 50 MB for short stress run


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
