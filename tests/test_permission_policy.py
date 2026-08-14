"""
UNIT TEST — Permission Policy
==============================
Tests friday/safety/permissions.py in isolation.
No Ollama. No real execution. No filesystem access.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.safety.permissions import check_permission, PermissionResult
from friday.intent.models import Action, Intent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_ENABLED = {
    "open_app": True,
    "close_app": True,
    "open_folder": True,
    "open_website": True,
    "search_web": True,
    "get_time": True,
    "find_file": True,
    "open_file": True,
}

_ALL_DISABLED = {k: False for k in _ALL_ENABLED}


def _intent(action: Action, target: str = "chrome", confidence: float = 0.95) -> Intent:
    return Intent(
        action=action,
        target=target,
        intent_confidence=confidence,
        target_confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_unknown_action_always_denied():
    """UNKNOWN is always DENIED regardless of permissions config."""
    i = _intent(Action.UNKNOWN, target="")
    assert check_permission(i, _ALL_ENABLED) == PermissionResult.DENIED
    assert check_permission(i, _ALL_DISABLED) == PermissionResult.DENIED
    assert check_permission(i, {}) == PermissionResult.DENIED


def test_open_app_allowed_when_permitted():
    i = _intent(Action.OPEN_APP, "chrome")
    assert check_permission(i, _ALL_ENABLED) == PermissionResult.ALLOWED


def test_open_app_denied_when_permission_false():
    perms = dict(_ALL_ENABLED)
    perms["open_app"] = False
    i = _intent(Action.OPEN_APP, "chrome")
    assert check_permission(i, perms) == PermissionResult.DENIED


def test_open_app_denied_when_key_missing():
    i = _intent(Action.OPEN_APP, "chrome")
    assert check_permission(i, {}) == PermissionResult.DENIED


def test_close_app_always_confirm_required():
    """CLOSE_APP is CONFIRM_REQUIRED even with full permissions and high confidence."""
    i = _intent(Action.CLOSE_APP, "chrome", confidence=1.0)
    assert check_permission(i, _ALL_ENABLED) == PermissionResult.CONFIRM_REQUIRED


def test_close_app_denied_when_permission_false():
    """If close_app permission is False, result is DENIED not CONFIRM_REQUIRED."""
    perms = dict(_ALL_ENABLED)
    perms["close_app"] = False
    i = _intent(Action.CLOSE_APP, "chrome")
    assert check_permission(i, perms) == PermissionResult.DENIED


def test_search_web_allowed():
    i = _intent(Action.SEARCH_WEB, "python tutorials")
    assert check_permission(i, _ALL_ENABLED) == PermissionResult.ALLOWED


def test_search_web_denied():
    perms = dict(_ALL_ENABLED)
    perms["search_web"] = False
    i = _intent(Action.SEARCH_WEB, "python tutorials")
    assert check_permission(i, perms) == PermissionResult.DENIED


def test_get_time_allowed():
    i = _intent(Action.GET_TIME, "")
    assert check_permission(i, _ALL_ENABLED) == PermissionResult.ALLOWED


def test_get_time_denied():
    i = _intent(Action.GET_TIME, "")
    assert check_permission(i, _ALL_DISABLED) == PermissionResult.DENIED


def test_open_website_allowed():
    i = _intent(Action.OPEN_WEBSITE, "youtube")
    assert check_permission(i, _ALL_ENABLED) == PermissionResult.ALLOWED


def test_open_website_denied():
    perms = dict(_ALL_ENABLED)
    perms["open_website"] = False
    i = _intent(Action.OPEN_WEBSITE, "youtube")
    assert check_permission(i, perms) == PermissionResult.DENIED


def test_find_file_allowed():
    i = _intent(Action.FIND_FILE, "resume")
    assert check_permission(i, _ALL_ENABLED) == PermissionResult.ALLOWED


def test_open_folder_allowed():
    i = _intent(Action.OPEN_FOLDER, "downloads")
    assert check_permission(i, _ALL_ENABLED) == PermissionResult.ALLOWED


def test_system_intents_bypass_permission_check():
    """System intents (HELP, REPEAT) are always ALLOWED — not gated by permissions."""
    for action in (Action.SYSTEM_HELP, Action.SYSTEM_REPEAT):
        i = _intent(action, "")
        assert check_permission(i, _ALL_DISABLED) == PermissionResult.ALLOWED, \
            f"{action.name} should bypass permission check"


def test_all_disabled_denies_all_real_actions():
    """With all permissions False, every real action is DENIED."""
    real_actions = [
        Action.OPEN_APP, Action.CLOSE_APP, Action.OPEN_WEBSITE,
        Action.SEARCH_WEB, Action.GET_TIME, Action.FIND_FILE,
        Action.OPEN_FILE, Action.OPEN_FOLDER,
    ]
    for action in real_actions:
        i = _intent(action, "chrome")
        result = check_permission(i, _ALL_DISABLED)
        assert result == PermissionResult.DENIED, \
            f"{action.name} should be DENIED when all permissions are False"


def test_permission_is_not_confidence_based():
    """
    Permission check must be independent of confidence.
    A low-confidence intent with a valid action and permission should still be ALLOWED
    at the permission layer (the safety validator handles confidence separately).
    """
    i = _intent(Action.OPEN_APP, "chrome", confidence=0.0)
    assert check_permission(i, _ALL_ENABLED) == PermissionResult.ALLOWED


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
