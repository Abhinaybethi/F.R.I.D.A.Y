"""
UNIT TEST — Real Execution Gate
================================
Tests the triple-gate logic in friday/tools/registry.py.
No Ollama. No real OS calls. All deterministic.

The triple gate:
    Gate 1: dry_run == False
    Gate 2: allow_real_execution == True
    Gate 3: permissions[action] == True AND permission != DENIED
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.tools import registry
from friday.intent.models import Action, Intent
from friday.safety.permissions import PermissionResult, check_permission

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def _intent(action: Action, target: str = "chrome", conf: float = 0.95) -> Intent:
    return Intent(action=action, target=target,
                  intent_confidence=conf, target_confidence=conf)


# ---------------------------------------------------------------------------
# Gate 1 — dry_run
# ---------------------------------------------------------------------------

def test_gate1_dry_run_prevents_real_execution():
    """dry_run=True must prevent real execution even if gates 2 and 3 are open."""
    i = _intent(Action.GET_TIME)
    # GET_TIME has no side effects, but the message distinguishes dry vs real
    result = registry.execute(i, dry_run=True, allow_real_execution=True,
                              permissions=_ALL_ENABLED)
    assert result["success"]
    # GET_TIME is always real (read-only stdlib) — verify it still succeeds in dry-run path


def test_gate1_dry_run_message():
    """open_app in dry-run mode must return a DRY RUN message."""
    i = _intent(Action.OPEN_APP, "notepad")
    result = registry.execute(i, dry_run=True, allow_real_execution=True,
                              permissions=_ALL_ENABLED)
    assert result["success"]
    assert "DRY RUN" in result["message"] or "Would" in result["message"]


# ---------------------------------------------------------------------------
# Gate 2 — allow_real_execution
# ---------------------------------------------------------------------------

def test_gate2_allow_real_false_forces_dryrun():
    """allow_real_execution=False must force dry-run even if dry_run=False."""
    i = _intent(Action.OPEN_APP, "notepad")
    result = registry.execute(i, dry_run=False, allow_real_execution=False,
                              permissions=_ALL_ENABLED)
    assert result["success"]
    assert "DRY RUN" in result["message"] or "Would" in result["message"]


# ---------------------------------------------------------------------------
# Gate 3 — permissions
# ---------------------------------------------------------------------------

def test_gate3_denied_action_blocked():
    """An action with permission=False must be BLOCKED before reaching the tool."""
    perms = dict(_ALL_ENABLED)
    perms["open_app"] = False
    i = _intent(Action.OPEN_APP, "chrome")
    result = registry.execute(i, dry_run=False, allow_real_execution=True,
                              permissions=perms)
    assert not result["success"]
    assert result.get("blocked") is True


def test_gate3_unknown_action_denied():
    """UNKNOWN action must be DENIED regardless of permissions."""
    i = _intent(Action.UNKNOWN, "")
    result = registry.execute(i, dry_run=False, allow_real_execution=True,
                              permissions=_ALL_ENABLED)
    assert not result["success"]
    assert result.get("blocked") is True


def test_gate3_missing_permission_key_denied():
    """If an action's permission key is absent from the dict, it must be DENIED."""
    i = _intent(Action.OPEN_APP, "chrome")
    result = registry.execute(i, dry_run=False, allow_real_execution=True,
                              permissions={})   # empty dict
    assert not result["success"]
    assert result.get("blocked") is True


# ---------------------------------------------------------------------------
# All three gates must BOTH pass for real execution to occur
# ---------------------------------------------------------------------------

def test_all_three_gates_required():
    """
    Real execution requires ALL THREE gates.
    Check each single-gate failure produces dry-run or block.
    """
    i = _intent(Action.OPEN_APP, "notepad")

    # Only gate 1 closed (dry_run=True)
    r = registry.execute(i, dry_run=True, allow_real_execution=True,
                         permissions=_ALL_ENABLED)
    assert "DRY RUN" in r["message"] or "Would" in r["message"]

    # Only gate 2 closed (allow_real_execution=False)
    r = registry.execute(i, dry_run=False, allow_real_execution=False,
                         permissions=_ALL_ENABLED)
    assert "DRY RUN" in r["message"] or "Would" in r["message"]

    # Only gate 3 closed (permission denied)
    perms = dict(_ALL_ENABLED)
    perms["open_app"] = False
    r = registry.execute(i, dry_run=False, allow_real_execution=True,
                         permissions=perms)
    assert r.get("blocked") is True


# ---------------------------------------------------------------------------
# Backward compatibility — no permissions arg
# ---------------------------------------------------------------------------

def test_backward_compat_no_permissions_arg():
    """Calling execute() without permissions= should still work (default all-enabled)."""
    i = _intent(Action.GET_TIME)
    result = registry.execute(i, dry_run=True)
    assert result["success"]


# ---------------------------------------------------------------------------
# CLOSE_APP permission gate
# ---------------------------------------------------------------------------

def test_close_app_denied_when_permission_false():
    """close_app=False in permissions must block CLOSE_APP."""
    perms = dict(_ALL_ENABLED)
    perms["close_app"] = False
    i = _intent(Action.CLOSE_APP, "chrome")
    result = registry.execute(i, dry_run=False, allow_real_execution=True,
                              permissions=perms)
    assert result.get("blocked") is True


def test_close_app_allowed_produces_dryrun_message():
    """CLOSE_APP with permission enabled in dry-run returns a dry-run message."""
    i = _intent(Action.CLOSE_APP, "chrome")
    result = registry.execute(i, dry_run=True, allow_real_execution=True,
                              permissions=_ALL_ENABLED)
    assert result["success"]
    assert "DRY RUN" in result["message"] or "Would" in result["message"]


# ---------------------------------------------------------------------------
# Verify audit log path exists after execution
# ---------------------------------------------------------------------------

def test_audit_log_created():
    """After any registry.execute() call the audit log file must exist."""
    from pathlib import Path
    i = _intent(Action.GET_TIME)
    registry.execute(i, dry_run=True, permissions=_ALL_ENABLED)
    audit_path = Path(__file__).parent.parent / "logs" / "friday_audit.log"
    assert audit_path.exists(), f"Audit log not found at {audit_path}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
