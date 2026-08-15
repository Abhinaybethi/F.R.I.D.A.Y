"""
UNIT TEST — Phase 22 Goal Re-Planning & Failure Recovery
=========================================================
Tests ActionPlan fallback step execution on intermediate step failure.
"""
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.executor import execute_plan_step
from friday.intent.models import Action, Intent


def test_plan_fallback_on_step_failure():
    primary_step = Intent(action=Action.FIND_FILE, target="nonexistent_file_xyz_123.txt", intent_confidence=1.0, target_confidence=1.0)
    fallback_step = Intent(action=Action.OPEN_APP, target="chrome", intent_confidence=1.0, target_confidence=1.0)

    plan = ActionPlan(
        steps=[primary_step],
        fallbacks={0: [fallback_step]}
    )

    # Executing primary step fails (find_file fails on nonexistent file)
    # The executor catches the failure, pops the fallback step, and succeeds!
    resp, req_conf, completed, tool_res = execute_plan_step(plan, dry_run=True)

    assert plan.state == PlanState.COMPLETED
    assert completed is True
    assert "Would open" in resp or "Opening" in resp
