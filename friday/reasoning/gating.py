"""
Reasoner Gating Subsystem for F.R.I.D.A.Y. Phase 12.

Determines deterministically whether a transcript requires fallback reasoning
via the local Ollama LLM, ensuring known commands and system intents NEVER call Ollama.
"""
from typing import Tuple, Optional
from friday.intent.models import Action, Intent
from friday.planning.context_resolver import ShortTermContext
from friday.utils.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_COMMANDS = {"help", "repeat", "cancel", "never mind", "nevermind", "abort", "stop", "exit", "quit"}
_BARE_CONFIRMATIONS = {"yes", "yeah", "yep", "sure", "no", "nope", "nah"}


def should_call_reasoner(
    transcript: str,
    intent: Intent,
    is_in_confirmation: bool = False,
) -> Tuple[bool, str]:
    """
    Determine whether the local LLM reasoner should be invoked for transcript.

    Returns:
        (should_call: bool, reason: str)
    """
    norm = transcript.lower().strip()

    if not norm or len(norm) < 2:
        return False, "Transcript too short/empty"

    # Rule 1: Known deterministic intent match
    if intent.action != Action.UNKNOWN:
        return False, f"Deterministic match: {intent.action.name}"

    # Rule 2: System commands
    if norm in _SYSTEM_COMMANDS:
        return False, "System command handled deterministically"

    # Rule 3: Bare confirmation words outside confirmation state
    if not is_in_confirmation and norm in _BARE_CONFIRMATIONS:
        return False, "Bare confirmation token outside confirmation state"

    # Rule 4: Ambiguous / Natural Language query -> Requires reasoner
    return True, "Ambiguous / Natural language request requires reasoning"
