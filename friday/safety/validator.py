"""
Safety validator — maps an Intent to an execution policy.

Policy:
  SAFE    confidence >= 0.85  → execute without asking
  CONFIRM confidence >= 0.45  → ask for confirmation first
  REJECT  confidence <  0.45  → do not execute, report failure
"""
from enum import Enum

from friday.intent.models import Action, Intent


class Policy(Enum):
    SAFE    = "safe"
    CONFIRM = "confirm"
    REJECT  = "reject"


_SAFE_THRESHOLD    = 0.85
_CONFIRM_THRESHOLD = 0.45


def validate(intent: Intent) -> Policy:
    """Return the execution policy for this intent."""
    if intent.action == Action.UNKNOWN:
        return Policy.REJECT
    if intent.confidence < _CONFIRM_THRESHOLD:
        return Policy.REJECT
    # CLOSE_APP ALWAYS requires confirmation for now
    if intent.action == Action.CLOSE_APP:
        return Policy.CONFIRM
    if intent.confidence >= _SAFE_THRESHOLD:
        return Policy.SAFE
    return Policy.CONFIRM
