"""
Safety validator — maps an Intent to an execution policy.

Policy:
  SAFE    confidence >= 0.85  → execute without asking
  CONFIRM confidence >= 0.45  → ask for confirmation first
  REJECT  confidence <  0.45  → do not execute, report failure

Note: When dry_run is enabled, all actions are considered SAFE since
no real execution occurs. This respects the "never ask user for approval"
policy in dry-run mode.
"""
from enum import Enum

from friday.intent.models import Action, Intent


class Policy(Enum):
    SAFE    = "safe"
    CONFIRM = "confirm"
    REJECT  = "reject"


_SAFE_THRESHOLD    = 0.85
_CONFIRM_THRESHOLD = 0.45


def validate(intent: Intent, dry_run: bool = False) -> Policy:
    """Return the execution policy for this intent.

    Args:
        intent: The intent being validated.
        dry_run: When True, all actions are SAFE (no real execution, no prompts).
    """
    # When dry_run is enabled, all actions are SAFE — no real execution, no prompts
    if dry_run:
        return Policy.SAFE
    if intent.action == Action.UNKNOWN:
        return Policy.REJECT
    if intent.confidence < _CONFIRM_THRESHOLD:
        return Policy.REJECT
    # CLOSE_APP and FORGET ALWAYS require confirmation (in non-dry-run mode)
    if intent.action in (Action.CLOSE_APP, Action.FORGET):
        return Policy.CONFIRM
    if intent.confidence >= _SAFE_THRESHOLD:
        return Policy.SAFE
    return Policy.CONFIRM
