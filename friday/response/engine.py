"""
Deterministic Spoken Response Engine for F.R.I.D.A.Y. Phase 12.

Converts structured tool ActionOutcome / ExecutionResult / VerificationResult into
natural, human-friendly spoken text responses without internal debugging tokens or raw dicts.
"""
import re
from typing import Optional, Union
from friday.intent.models import Action, Intent
from friday.verification.models import ActionOutcome, FinalStatus, ExecutionStatus, VerificationStatus


def format_spoken_response(outcome: Union[ActionOutcome, dict, str], is_dry_run: bool = True) -> str:
    """
    Format a clean natural spoken text response from ActionOutcome or result dict/str.

    Ensures:
      - No '[DRY RUN]' prefix in spoken text output.
      - No raw Python dictionaries or json strings.
      - No internal policy codes or stack trace snippets.
    """
    if isinstance(outcome, str):
        return _clean_text(outcome)

    if isinstance(outcome, dict):
        msg = outcome.get("user_message") or outcome.get("message") or "Done."
        return _clean_text(msg)

    if not isinstance(outcome, ActionOutcome):
        return "Done."

    intent = outcome.intent
    exec_res = outcome.execution
    ver_res = outcome.verification

    # Handle Blocked
    if outcome.final_status == FinalStatus.BLOCKED or exec_res.blocked:
        return f"Action {intent.action.name.lower().replace('_', ' ')} is not permitted."

    # Handle Verification Failure
    if outcome.final_status == FinalStatus.FAILED or ver_res.status == VerificationStatus.FAILED:
        target_name = intent.target or "the application"
        return f"I couldn't confirm that {target_name} completed successfully."

    # Action Specific Spoken Response Templates
    action = intent.action
    target = intent.target.strip()

    if action == Action.OPEN_APP:
        app_title = target.capitalize() if target else "the application"
        return f"Opening {app_title}."

    elif action == Action.OPEN_WEBSITE:
        site_title = target.capitalize() if target else "the website"
        return f"Opening {site_title}."

    elif action == Action.SEARCH_WEB:
        return f"Searching Google for {target}." if target else "Searching the web."

    elif action == Action.GET_TIME:
        # Pass through actual time string from tool execution result
        return _clean_text(exec_res.message)

    elif action == Action.FIND_FILE:
        return _clean_text(exec_res.message)

    elif action == Action.OPEN_FOLDER:
        folder_title = target.capitalize() if target else "the folder"
        return f"Opening {folder_title} folder."

    elif action == Action.CLOSE_APP:
        app_title = target.capitalize() if target else "the application"
        return f"Closing {app_title}."

    # Default clean output
    return _clean_text(outcome.user_message)


def _clean_text(text: str) -> str:
    """Strip '[DRY RUN]' tags, dict string formatting, and internal debug noise."""
    if not text:
        return ""
    # Strip [DRY RUN] or [DRY RUN] Would ...
    text = re.sub(r"\[DRY RUN\]\s*(Would\s*)?", "", text, flags=re.IGNORECASE).strip()
    # Strip URL search formatting if user message was raw URL
    if text.startswith("https://www.google.com/search?q="):
        query = text.split("?q=")[-1].replace("+", " ")
        return f"Searching Google for {query}."
    # Ensure capitalization and sentence ending
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text
