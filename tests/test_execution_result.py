"""
UNIT TEST — Execution & Verification Models
============================================
Tests friday/verification/models.py in isolation.
No Ollama. No OS execution. No network.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.models import Action, Intent
from friday.verification.models import (
    ExecutionStatus,
    VerificationStatus,
    FinalStatus,
    ExecutionResult,
    VerificationResult,
    ActionOutcome,
)


def test_execution_status_enum_values():
    """Verify ExecutionStatus contains required values."""
    assert ExecutionStatus.SUCCESS.value == "SUCCESS"
    assert ExecutionStatus.FAILED.value == "FAILED"
    assert ExecutionStatus.BLOCKED.value == "BLOCKED"
    assert ExecutionStatus.DENIED.value == "DENIED"
    assert ExecutionStatus.CONFIRMATION_REQUIRED.value == "CONFIRMATION_REQUIRED"


def test_verification_status_enum_values():
    """Verify VerificationStatus contains required values."""
    assert VerificationStatus.VERIFIED_SUCCESS.value == "VERIFIED_SUCCESS"
    assert VerificationStatus.FAILED.value == "FAILED"
    assert VerificationStatus.NOT_APPLICABLE.value == "NOT_APPLICABLE"
    assert VerificationStatus.DRY_RUN.value == "DRY_RUN"
    assert VerificationStatus.SKIPPED.value == "SKIPPED"


def test_final_status_enum_values():
    """Verify FinalStatus contains required values."""
    assert FinalStatus.SUCCESS.value == "SUCCESS"
    assert FinalStatus.FAILED.value == "FAILED"
    assert FinalStatus.BLOCKED.value == "BLOCKED"
    assert FinalStatus.CONFIRMATION_REQUIRED.value == "CONFIRMATION_REQUIRED"
    assert FinalStatus.DRY_RUN.value == "DRY_RUN"


def test_execution_result_dataclass():
    """Verify ExecutionResult instantiation and default fields."""
    res = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.SUCCESS,
        message="Opening Chrome.",
    )
    assert res.action == Action.OPEN_APP
    assert res.target == "chrome"
    assert res.status == ExecutionStatus.SUCCESS
    assert res.message == "Opening Chrome."
    assert res.blocked is False
    assert res.raw_tool_result == {}
    assert res.execution_latency_ms == 0.0


def test_verification_result_dataclass():
    """Verify VerificationResult instantiation and default fields."""
    v_res = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        message="Chrome process detected.",
        details={"pid": 1234},
        verification_latency_ms=5.2,
    )
    assert v_res.status == VerificationStatus.VERIFIED_SUCCESS
    assert v_res.message == "Chrome process detected."
    assert v_res.details == {"pid": 1234}
    assert v_res.verification_latency_ms == 5.2


def test_action_outcome_dataclass():
    """Verify ActionOutcome aggregation and helper properties."""
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    exec_res = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.SUCCESS,
        message="Opening Chrome.",
    )
    ver_res = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        message="Process chrome.exe found.",
    )
    outcome = ActionOutcome(
        intent=intent,
        execution=exec_res,
        verification=ver_res,
        final_status=FinalStatus.SUCCESS,
        user_message="Opening Chrome.",
    )
    assert outcome.intent == intent
    assert outcome.execution == exec_res
    assert outcome.verification == ver_res
    assert outcome.final_status == FinalStatus.SUCCESS
    assert outcome.is_success is True


def test_action_outcome_dry_run_is_success():
    """Dry run outcome should count as is_success = True."""
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    exec_res = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.SUCCESS,
        message="[DRY RUN] Would open Chrome.",
    )
    ver_res = VerificationResult(
        status=VerificationStatus.DRY_RUN,
        message="[DRY RUN] Verification simulated.",
    )
    outcome = ActionOutcome(
        intent=intent,
        execution=exec_res,
        verification=ver_res,
        final_status=FinalStatus.DRY_RUN,
        user_message="[DRY RUN] Would open Chrome.",
    )
    assert outcome.final_status == FinalStatus.DRY_RUN
    assert outcome.is_success is True


def test_action_outcome_failed_is_not_success():
    """Failed outcome should count as is_success = False."""
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    exec_res = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.FAILED,
        message="Failed to open Chrome.",
    )
    ver_res = VerificationResult(
        status=VerificationStatus.SKIPPED,
        message="Verification skipped due to execution failure.",
    )
    outcome = ActionOutcome(
        intent=intent,
        execution=exec_res,
        verification=ver_res,
        final_status=FinalStatus.FAILED,
        user_message="I couldn't open Chrome.",
    )
    assert outcome.final_status == FinalStatus.FAILED
    assert outcome.is_success is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
