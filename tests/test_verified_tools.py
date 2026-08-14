"""
UNIT TEST — Verified Tool Dispatch & Outcome Handling
=======================================================
Tests registry.execute() tool dispatch + verifier integration.
No Ollama. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.tools import registry
from friday.intent.models import Action, Intent
from friday.verification.models import (
    ExecutionStatus,
    VerificationStatus,
    FinalStatus,
    ActionOutcome,
)

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def test_registry_returns_action_outcome():
    """registry.execute() must return an ActionOutcome object."""
    intent = Intent(action=Action.GET_TIME, target="")
    outcome_dry = registry.execute(intent, dry_run=True, permissions=_ALL_ENABLED)
    assert isinstance(outcome_dry, ActionOutcome)
    assert outcome_dry.execution.status == ExecutionStatus.SUCCESS
    assert outcome_dry.verification.status == VerificationStatus.NOT_APPLICABLE
    assert outcome_dry.final_status == FinalStatus.DRY_RUN

    outcome_real = registry.execute(intent, dry_run=False, allow_real_execution=True, permissions=_ALL_ENABLED)
    assert outcome_real.final_status == FinalStatus.SUCCESS


def test_outcome_dict_indexing_backward_compatibility():
    """ActionOutcome must support dict indexing for backward compatibility."""
    intent = Intent(action=Action.OPEN_APP, target="notepad")
    outcome = registry.execute(intent, dry_run=True, permissions=_ALL_ENABLED)

    # Subscripting & get()
    assert outcome["success"] is True
    assert "message" in outcome
    assert "DRY RUN" in outcome["message"] or "Would" in outcome["message"]
    assert outcome.get("blocked", False) is False
    assert outcome.get("outcome") == outcome


def test_blocked_permission_returns_blocked_outcome():
    """Denied permission returns BLOCKED execution and SKIPPED verification."""
    perms = dict(_ALL_ENABLED)
    perms["open_app"] = False
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    outcome = registry.execute(intent, dry_run=False, allow_real_execution=True, permissions=perms)

    assert outcome.execution.status == ExecutionStatus.BLOCKED
    assert outcome.verification.status == VerificationStatus.SKIPPED
    assert outcome.final_status == FinalStatus.BLOCKED
    assert outcome["blocked"] is True
    assert outcome["success"] is False


def test_unknown_app_tool_failure_outcome():
    """Unknown app target produces FAILED execution and SKIPPED verification."""
    intent = Intent(action=Action.OPEN_APP, target="unknown_app_999")
    outcome = registry.execute(intent, dry_run=True, permissions=_ALL_ENABLED)

    assert outcome.execution.status == ExecutionStatus.FAILED
    assert outcome.verification.status == VerificationStatus.SKIPPED
    assert outcome.final_status == FinalStatus.FAILED
    assert outcome.is_success is False


def test_dry_run_tool_execution_outcome():
    """Dry run execution produces SUCCESS execution, DRY_RUN verification, and DRY_RUN final status."""
    intent = Intent(action=Action.OPEN_WEBSITE, target="youtube")
    outcome = registry.execute(intent, dry_run=True, permissions=_ALL_ENABLED)

    assert outcome.execution.status == ExecutionStatus.SUCCESS
    assert outcome.verification.status == VerificationStatus.DRY_RUN
    assert outcome.final_status == FinalStatus.DRY_RUN
    assert outcome.is_success is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
