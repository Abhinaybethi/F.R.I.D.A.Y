"""
UNIT TEST — Multi-Step Plan Verification & Abort Logic
======================================================
Tests executor.py and ConversationManager multi-step verification.
No Ollama. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.models import Action, Intent
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.executor import execute_plan_step
from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def _intent(action: Action, target: str = "", conf: float = 0.95) -> Intent:
    return Intent(
        action=action,
        target=target,
        intent_confidence=conf,
        target_confidence=conf,
        confidence=conf,
    )


def test_plan_step_success_continues():
    """When a plan step succeeds, current_step_index increments and plan continues."""
    plan = ActionPlan(steps=[
        _intent(Action.GET_TIME, target=""),
        _intent(Action.OPEN_FOLDER, target="downloads"),
    ])
    response, requires_conf, is_completed, tool_res = execute_plan_step(
        plan, dry_run=True, permissions=_ALL_ENABLED
    )
    assert not is_completed
    assert plan.current_step_index == 1
    assert plan.state == PlanState.EXECUTING


def test_plan_step_failure_aborts_plan():
    """When step 1 fails (unknown app), plan state becomes FAILED and execution stops."""
    plan = ActionPlan(steps=[
        _intent(Action.OPEN_APP, target="unknown_app_12345"),
        _intent(Action.OPEN_FOLDER, target="downloads"),
    ])
    response, requires_conf, is_completed, tool_res = execute_plan_step(
        plan, dry_run=True, permissions=_ALL_ENABLED
    )
    assert is_completed is True
    assert plan.state == PlanState.FAILED
    assert plan.current_step_index == 0  # Did not advance to step 2!
    assert "Unknown app" in response or "not in registry" in response.lower()


def test_conversation_manager_multistep_aborts_on_step1_failure():
    """ConversationManager stops multi-step transcript if step 1 fails."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    # "open unknown_app_12345 and open downloads"
    resp, keep = cm.handle_transcript("open unknown_app_12345 and open downloads")

    # Final response must explain rejection or failure of first part
    assert any(tok in resp.lower() for tok in ("cannot safely execute", "unknown_app_12345", "not in registry", "couldn't", "failed"))
    assert cm.context.current_plan is None
    assert cm.state == ConversationState.LISTENING


def test_conversation_manager_multistep_all_safe_succeeds():
    """ConversationManager executes all steps when all steps succeed."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    resp, keep = cm.handle_transcript("open chrome and open downloads")
    assert "Chrome" in resp or "chrome" in resp.lower()
    assert cm.context.current_plan is None
    assert cm.state == ConversationState.LISTENING


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
