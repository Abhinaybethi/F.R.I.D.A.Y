"""
UNIT TEST — Native Desktop Control (Phase 14 P0)
=================================================
Tests native ctypes desktop control hooks in friday/tools/desktop.py.
No Ollama required. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.tools import desktop


def test_desktop_minimize_dry_run():
    """minimize_app returns dry-run string in dry-run mode."""
    res = desktop.minimize_app("chrome", dry_run=True)
    assert res["success"] is True
    assert "[DRY RUN]" in res["message"]


def test_desktop_maximize_dry_run():
    """maximize_app returns dry-run string in dry-run mode."""
    res = desktop.maximize_app("vscode", dry_run=True)
    assert res["success"] is True
    assert "[DRY RUN]" in res["message"]


def test_desktop_release_test_mode_dispatch():
    """minimize_app in RELEASE_TEST_MODE returns execution status."""
    os.environ["RELEASE_TEST_MODE"] = "1"
    try:
        res = desktop.minimize_app("NonExistentWindow", dry_run=True)
        assert res["success"] is True
    finally:
        os.environ.pop("RELEASE_TEST_MODE", None)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
