"""
Confirmation engine and response parsing.

Exposes a generic interface for resolving confirmation responses across voice and console layers.
"""
from friday.intent.models import Action, Intent
from friday.intent.normalizer import normalize

_AFFIRMATIVE = {
    "yes", "y", "yeah", "yep", "yup", "correct", "sure", "ok", "okay",
    "that's right", "thats right", "do it", "go ahead"
}

_NEGATIVE = {
    "no", "n", "nope", "wrong", "not that", "cancel", "abort", "stop",
    "never mind", "nevermind"
}


def parse_confirmation_response(transcript: str) -> bool | None:
    """
    Parse a user transcript for a confirmation response.

    Uses conservative normalization to handle STT punctuation (e.g. "yes.", "yeah!").

    Returns:
        True  -> Affirmative (confirmed)
        False -> Negative (declined / cancelled)
        None  -> Ambiguous / unrecognized (remain in WAITING_FOR_CONFIRMATION)
    """
    if not transcript:
        return None

    # Normalize input: lowercase, strip punctuation and whitespace
    t = normalize(transcript)
    if t in _AFFIRMATIVE:
        return True
    if t in _NEGATIVE:
        return False
    return None


def format_confirmation_prompt(intent: Intent) -> str:
    """
    Concise, natural user-facing confirmation prompt message.

    Examples:
        OPEN_APP(chrome)     -> "Did you mean Chrome?"
        OPEN_WEBSITE(youtube)-> "Did you mean Youtube?"
        CLOSE_APP(chrome)    -> "Do you want me to close Chrome?"
    """
    target = intent.target.title() if intent.target else ""

    if intent.action == Action.CLOSE_APP:
        target_display = target if target else "the application"
        return f"Do you want me to close {target_display}?"

    if target:
        return f"Did you mean {target}?"

    action_label = intent.action.name.replace("_", " ").title()
    return f"Did you mean {action_label}?"


def request_confirmation(intent: Intent) -> bool:
    """
    Console prompt for confirmation.

    Returns True if user confirms, False otherwise.
    """
    prompt = format_confirmation_prompt(intent)
    print(f"\nF.R.I.D.A.Y: {prompt}")
    print(         "           [yes / no]: ", end="", flush=True)

    try:
        answer = input().strip()
    except (EOFError, KeyboardInterrupt):
        print("\nF.R.I.D.A.Y: Cancelled.")
        return False

    parsed = parse_confirmation_response(answer)
    if parsed is True:
        return True

    print("F.R.I.D.A.Y: Cancelled.")
    return False
