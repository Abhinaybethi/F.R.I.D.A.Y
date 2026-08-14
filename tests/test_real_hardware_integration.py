"""
INTEGRATION TEST — Real Hardware & Voice System Integration
============================================================
Programmatic validation of real microphone device settings,
Silero VAD, faster-whisper STT, Piper TTS, and Ollama server.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.utils.health_diagnostics import check_system_health


def test_hardware_health_diagnostics():
    """Verify hardware diagnostics runs cleanly and returns component statuses."""
    health = check_system_health()
    assert "overall_status" in health
    assert "components" in health
    comps = health["components"]
    assert "microphone" in comps
    assert "vad" in comps
    assert "stt" in comps
    assert "tts" in comps
    assert "ollama" in comps
    assert comps["config"]["status"] == "PASS"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
