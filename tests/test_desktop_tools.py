"""
UNIT TEST — Desktop Window & Screenshot Tools (Phase 13 P2)
=============================================================
Tests friday/tools/desktop.py (minimize_app, maximize_app, take_screenshot).
No Ollama required. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.tools import desktop, registry
from friday.intent.models import Action, Intent
from friday.verification.models import ExecutionStatus, FinalStatus

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
}


def test_minimize_app_tool():
    """minimize_app returns dry_run message in dry_run mode."""
    res = desktop.minimize_app("chrome", dry_run=True)
    assert res["success"] is True
    assert "[DRY RUN]" in res["message"]
    assert "chrome" in res["message"]


def test_maximize_app_tool():
    """maximize_app returns dry_run message in dry_run mode."""
    res = desktop.maximize_app("vscode", dry_run=True)
    assert res["success"] is True
    assert "[DRY RUN]" in res["message"]
    assert "vscode" in res["message"]


def test_take_screenshot_tool():
    """take_screenshot returns dry_run message in dry_run mode."""
    res = desktop.take_screenshot(dry_run=True)
    assert res["success"] is True
    assert "[DRY RUN]" in res["message"]


def test_registry_dispatch_desktop_tools():
    """registry.execute dispatches MINIMIZE_APP, MAXIMIZE_APP, TAKE_SCREENSHOT."""
    outcome_min = registry.execute(Intent(action=Action.MINIMIZE_APP, target="chrome"), dry_run=True, permissions=_ALL_ENABLED)
    assert outcome_min.execution.status == ExecutionStatus.SUCCESS

    outcome_max = registry.execute(Intent(action=Action.MAXIMIZE_APP, target="chrome"), dry_run=True, permissions=_ALL_ENABLED)
    assert outcome_max.execution.status == ExecutionStatus.SUCCESS

    outcome_ss = registry.execute(Intent(action=Action.TAKE_SCREENSHOT), dry_run=True, permissions=_ALL_ENABLED)
    assert outcome_ss.execution.status == ExecutionStatus.SUCCESS


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
