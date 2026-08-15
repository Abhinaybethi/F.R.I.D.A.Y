"""
Phase 8 Permission Layer.

Centralized per-action permission policy.
Called by registry.execute() before any tool is dispatched.

PermissionResult values:
    ALLOWED          — action is permitted, proceed
    CONFIRM_REQUIRED — action requires explicit user confirmation first
    DENIED           — action is not permitted, fail closed

No scattered if-statements elsewhere. All policy here.
"""
from enum import Enum

from friday.intent.models import Action, Intent

# Maps Action enum member to the config.yaml permissions key
_ACTION_PERMISSION_KEY: dict[Action, str] = {
    Action.OPEN_APP:        "open_app",
    Action.CLOSE_APP:       "close_app",
    Action.OPEN_WEBSITE:    "open_website",
    Action.READ_WEBSITE:    "read_website",
    Action.SEARCH_WEB:      "search_web",
    Action.GET_TIME:        "get_time",
    Action.FIND_FILE:       "find_file",
    Action.OPEN_FILE:       "open_file",
    Action.OPEN_FOLDER:     "open_folder",
    Action.MINIMIZE_APP:    "minimize_app",
    Action.MAXIMIZE_APP:    "maximize_app",
    Action.TAKE_SCREENSHOT: "take_screenshot",
    Action.REMEMBER:        "remember",
    Action.RECALL:          "recall",
    Action.FORGET:          "forget",
}


class PermissionResult(Enum):
    ALLOWED          = "allowed"
    CONFIRM_REQUIRED = "confirm_required"
    DENIED           = "denied"


def check_permission(intent: Intent, permissions: dict) -> PermissionResult:
    """
    Return the permission decision for this intent.

    Args:
        intent:      A validated Intent object.
        permissions: The ``tools.permissions`` dict from config.yaml.
                     Example: {"open_app": True, "close_app": True, ...}

    Rules (evaluated in order):
        1. UNKNOWN action  → DENIED
        2. Action not in permission map → DENIED
        3. permissions[key] is False → DENIED
        4. CLOSE_APP or FORGET → CONFIRM_REQUIRED (always, regardless of confidence)
        5. Otherwise → ALLOWED
    """
    if intent.action == Action.UNKNOWN:
        return PermissionResult.DENIED

    key = _ACTION_PERMISSION_KEY.get(intent.action)
    if key is None:
        # System intents (SYSTEM_HELP, SYSTEM_REPEAT, etc.) bypass permission check
        if intent.action.name.startswith("SYSTEM_"):
            return PermissionResult.ALLOWED
        return PermissionResult.DENIED

    if not permissions.get(key, False):
        return PermissionResult.DENIED

    # CLOSE_APP and FORGET always require explicit confirmation
    if intent.action in (Action.CLOSE_APP, Action.FORGET):
        return PermissionResult.CONFIRM_REQUIRED

    return PermissionResult.ALLOWED
