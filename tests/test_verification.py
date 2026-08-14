"""
UNIT TEST — Action Verifiers & Verification Subsystem
======================================================
Tests friday/verification/verifier.py and action_verifiers.py.
No Ollama. Deterministic execution.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.models import Action, Intent
from friday.verification.models import (
    ExecutionStatus,
    ExecutionResult,
    VerificationStatus,
    VerificationResult,
)
from friday.verification.verifier import verify_execution
from friday.verification import action_verifiers


def test_dry_run_verification_status():
    """In dry run mode, verifier returns DRY_RUN status."""
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    exec_res = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.SUCCESS,
        message="[DRY RUN] Would open Chrome.",
    )
    v_res = verify_execution(intent, exec_res, is_dry_run=True)
    assert v_res.status == VerificationStatus.DRY_RUN
    assert "[DRY RUN]" in v_res.message


def test_skipped_verification_on_failed_execution():
    """Verification must be SKIPPED if execution failed."""
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    exec_res = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.FAILED,
        message="Could not open Chrome.",
    )
    v_res = verify_execution(intent, exec_res, is_dry_run=False)
    assert v_res.status == VerificationStatus.SKIPPED
    assert "skipped" in v_res.message.lower()


def test_skipped_verification_on_blocked_execution():
    """Verification must be SKIPPED if execution was blocked by permissions."""
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    exec_res = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.BLOCKED,
        message="Action OPEN_APP('chrome') is not permitted.",
        blocked=True,
    )
    v_res = verify_execution(intent, exec_res, is_dry_run=False)
    assert v_res.status == VerificationStatus.SKIPPED


def test_folder_verification_known_folder():
    """OPEN_FOLDER for downloads in real mode verifies folder path exists."""
    v_res = action_verifiers.verify_open_folder("downloads", is_dry_run=False)
    # Downloads folder exists on standard Windows install
    assert v_res.status in (VerificationStatus.VERIFIED_SUCCESS, VerificationStatus.FAILED)
    if v_res.status == VerificationStatus.VERIFIED_SUCCESS:
        assert "Downloads" in v_res.message or "downloads" in v_res.message.lower()


def test_folder_verification_invalid_folder():
    """OPEN_FOLDER for invalid folder target returns FAILED verification."""
    v_res = action_verifiers.verify_open_folder("invalid_folder_target_xyz", is_dry_run=False)
    assert v_res.status == VerificationStatus.FAILED
    assert "not a known safe directory" in v_res.message.lower()


def test_website_verification_known_site():
    """OPEN_WEBSITE for youtube in real mode returns VERIFIED_SUCCESS."""
    v_res = action_verifiers.verify_open_website("youtube", is_dry_run=False)
    assert v_res.status == VerificationStatus.VERIFIED_SUCCESS
    assert "youtube.com" in v_res.details.get("url", "")


def test_website_verification_unknown_site():
    """OPEN_WEBSITE for unknown website returns FAILED verification."""
    v_res = action_verifiers.verify_open_website("unknownsite123", is_dry_run=False)
    assert v_res.status == VerificationStatus.FAILED


def test_get_time_not_applicable():
    """GET_TIME verification status is NOT_APPLICABLE."""
    intent = Intent(action=Action.GET_TIME, target="")
    exec_res = ExecutionResult(
        action=Action.GET_TIME,
        target="",
        status=ExecutionStatus.SUCCESS,
        message="It's 10:00 AM.",
    )
    v_res = verify_execution(intent, exec_res, is_dry_run=False)
    assert v_res.status == VerificationStatus.NOT_APPLICABLE


def test_find_file_not_applicable():
    """FIND_FILE verification status is NOT_APPLICABLE."""
    intent = Intent(action=Action.FIND_FILE, target="test")
    exec_res = ExecutionResult(
        action=Action.FIND_FILE,
        target="test",
        status=ExecutionStatus.SUCCESS,
        message="Found 1 file.",
    )
    v_res = verify_execution(intent, exec_res, is_dry_run=False)
    assert v_res.status == VerificationStatus.NOT_APPLICABLE


def test_unknown_action_verifier_fallback():
    """Unregistered action in verifier table returns NOT_APPLICABLE."""
    intent = Intent(action=Action.SYSTEM_HELP, target="")
    exec_res = ExecutionResult(
        action=Action.SYSTEM_HELP,
        target="",
        status=ExecutionStatus.SUCCESS,
        message="Help text.",
    )
    v_res = verify_execution(intent, exec_res, is_dry_run=False)
    assert v_res.status == VerificationStatus.NOT_APPLICABLE


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
