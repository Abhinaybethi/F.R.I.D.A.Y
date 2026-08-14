"""
UNIT TEST — Dynamic Target Alias Registry (Phase 14 P1)
========================================================
Tests get_dynamic_targets() in friday/intent/fuzzy_router.py.
No Ollama required. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.fuzzy_router import get_dynamic_targets, fuzzy_route


def test_dynamic_targets_harvesting():
    """get_dynamic_targets() includes registered apps, websites, and folders."""
    targets = get_dynamic_targets()
    assert "chrome" in targets
    assert "youtube" in targets
    assert "downloads" in targets


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
