"""
UNIT TEST — System Health Diagnostics
======================================
Tests friday/utils/health_diagnostics.py in isolation.
No Ollama required.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.utils.health_diagnostics import check_system_health


def test_check_system_health_structure():
    """check_system_health() returns structured result dictionary."""
    health = check_system_health()
    assert "overall_status" in health
    assert health["overall_status"] in ("PASS", "DEGRADED", "FAIL")

    comps = health.get("components", {})
    assert "config" in comps
    assert "microphone" in comps
    assert "vad" in comps
    assert "stt" in comps
    assert "tts" in comps
    assert "ollama" in comps

    assert comps["config"]["status"] in ("PASS", "FAIL")


def test_health_check_missing_config():
    """check_system_health() with non-existent config returns FAIL for config component."""
    health = check_system_health(config_path="non_existent_config_12345.yaml")
    assert health["components"]["config"]["status"] == "FAIL"
    assert health["overall_status"] == "DEGRADED"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
