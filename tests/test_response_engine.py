"""
UNIT TEST — Deterministic Response Engine
===========================================
Tests friday/response/engine.py formatting rules.
Ensures spoken output contains NO '[DRY RUN]', NO raw dicts, NO internal policy tokens.
No Ollama required.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.response.engine import format_spoken_response
from friday.intent.models import Action, Intent
from friday.verification.models import ActionOutcome, ExecutionResult, VerificationResult, ExecutionStatus, VerificationStatus, FinalStatus


def test_spoken_response_no_dry_run_tag():
    """format_spoken_response() strips '[DRY RUN]' from spoken output."""
    outcome = ActionOutcome(
        intent=Intent(action=Action.OPEN_APP, target="chrome"),
        execution=ExecutionResult(action=Action.OPEN_APP, target="chrome", status=ExecutionStatus.SUCCESS, message="[DRY RUN] Would open Chrome."),
        verification=VerificationResult(status=VerificationStatus.DRY_RUN, message="Dry run"),
        final_status=FinalStatus.DRY_RUN,
        user_message="[DRY RUN] Would open Chrome.",
    )
    spoken = format_spoken_response(outcome, is_dry_run=True)
    assert "[DRY RUN]" not in spoken
    assert "Opening Chrome." in spoken


def test_spoken_response_verification_failure():
    """Verification failure returns clean spoken failure message."""
    outcome = ActionOutcome(
        intent=Intent(action=Action.OPEN_APP, target="chrome"),
        execution=ExecutionResult(action=Action.OPEN_APP, target="chrome", status=ExecutionStatus.SUCCESS, message="Opening Chrome."),
        verification=VerificationResult(status=VerificationStatus.FAILED, message="Process not found"),
        final_status=FinalStatus.FAILED,
        user_message="Execution succeeded but verification failed.",
    )
    spoken = format_spoken_response(outcome)
    assert "couldn't confirm" in spoken.lower()


def test_spoken_response_search_web():
    """SEARCH_WEB returns clean natural spoken search phrasing."""
    outcome = ActionOutcome(
        intent=Intent(action=Action.SEARCH_WEB, target="python tutorials"),
        execution=ExecutionResult(action=Action.SEARCH_WEB, target="python tutorials", status=ExecutionStatus.SUCCESS, message="[DRY RUN] Would search: https://www.google.com/search?q=python+tutorials"),
        verification=VerificationResult(status=VerificationStatus.DRY_RUN, message="Dry run"),
        final_status=FinalStatus.DRY_RUN,
        user_message="[DRY RUN] Would search Google.",
    )
    spoken = format_spoken_response(outcome)
    assert "[DRY RUN]" not in spoken
    assert "Searching Google for python tutorials." in spoken


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
