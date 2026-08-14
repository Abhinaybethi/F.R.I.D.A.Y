"""
UNIT TEST — Controlled Release Test Mode (RELEASE_TEST_MODE)
============================================================
Tests release_test_mode behavior in friday/tools/registry.py.
No Ollama. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.tools import registry
from friday.intent.models import Action, Intent
from friday.verification.models import ExecutionStatus, VerificationStatus, FinalStatus

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def _intent(action: Action, target: str = "") -> Intent:
    return Intent(action=action, target=target, confidence=0.95)


def test_release_test_mode_whitelisted_target_allows_real():
    """Whitelisted target (OPEN_APP chrome) in release_test_mode is allowed real execution."""
    intent = _intent(Action.OPEN_APP, "chrome")
    outcome = registry.execute(intent, dry_run=True, allow_real_execution=False, permissions=_ALL_ENABLED, release_test_mode=True)
    # Execution is real (not dry-run message)
    assert outcome.execution.status == ExecutionStatus.SUCCESS
    assert outcome.verification.status in (VerificationStatus.VERIFIED_SUCCESS, VerificationStatus.FAILED)


def test_release_test_mode_unwhitelisted_target_forces_dry_run():
    """Un-whitelisted target (OPEN_APP notepad) in release_test_mode remains in dry_run mode."""
    intent = _intent(Action.OPEN_APP, "notepad")
    outcome = registry.execute(intent, dry_run=True, allow_real_execution=False, permissions=_ALL_ENABLED, release_test_mode=True)
    assert outcome.verification.status == VerificationStatus.DRY_RUN
    assert outcome.final_status == FinalStatus.DRY_RUN
    assert "DRY RUN" in outcome.user_message


def test_release_test_mode_close_app_remains_dry_run():
    """CLOSE_APP chrome is NOT in release whitelist, so it remains in dry-run mode."""
    intent = _intent(Action.CLOSE_APP, "chrome")
    outcome = registry.execute(intent, dry_run=True, allow_real_execution=False, permissions=_ALL_ENABLED, release_test_mode=True)
    assert outcome.verification.status == VerificationStatus.DRY_RUN
    assert outcome.final_status == FinalStatus.DRY_RUN


def test_release_test_mode_permission_denial_still_blocks():
    """If permission is False, release_test_mode still blocks execution."""
    perms = dict(_ALL_ENABLED)
    perms["open_app"] = False
    intent = _intent(Action.OPEN_APP, "chrome")
    outcome = registry.execute(intent, dry_run=True, allow_real_execution=False, permissions=perms, release_test_mode=True)
    assert outcome.execution.status == ExecutionStatus.BLOCKED
    assert outcome.final_status == FinalStatus.BLOCKED


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
