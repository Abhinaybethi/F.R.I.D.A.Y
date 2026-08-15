"""
UNIT TEST — Phase 23 Goal Idempotency & Resumption Safety
==========================================================
Tests that completed plan steps recorded in GoalContext are safely skipped on goal resumption.
"""
from friday.intent.models import Action, Intent
from friday.planning.goal_models import GoalContext, GoalState
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.executor import execute_plan_step


def test_idempotency_step_skipping_on_resume():
    gc = GoalContext(objective="Open Chrome and open Youtube")
    
    step1 = Intent(action=Action.OPEN_APP, target="chrome", intent_confidence=1.0, target_confidence=1.0)
    step2 = Intent(action=Action.OPEN_WEBSITE, target="youtube", intent_confidence=1.0, target_confidence=1.0)
    
    plan = ActionPlan(id="plan-123", steps=[step1, step2])
    
    # Pre-record step 1 as completed in GoalContext
    key1 = "plan-123_step_0_OPEN_APP_chrome"
    gc.record_completed_step(step1, {"success": True}, key1)
    assert gc.is_step_already_completed(key1)

    # Execute plan with goal_context
    resp, req_conf, is_completed, tool_res = execute_plan_step(plan, dry_run=True, goal_context=gc)
    
    # Step 1 was skipped automatically due to idempotency! Plan progressed to step 2.
    assert plan.current_step_index == 1
    assert "Step already completed" in resp or "Would open" in resp


def test_destructive_action_idempotency_log():
    gc = GoalContext(objective="Close Chrome")
    step = Intent(action=Action.CLOSE_APP, target="chrome", intent_confidence=1.0, target_confidence=1.0)
    key = "plan-456_step_0_CLOSE_APP_chrome"
    
    gc.record_completed_step(step, {"success": True}, key)
    assert key in gc.idempotency_keys
    assert gc.is_step_already_completed(key)
