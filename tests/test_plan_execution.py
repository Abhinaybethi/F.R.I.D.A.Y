import os
import sys

# Ensure friday is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.planning.planner import parse_plan
from friday.planning.executor import execute_plan_step
from friday.planning.context_resolver import ShortTermContext
from friday.planning.plan_models import PlanState
from friday.intent.models import Action

def test_plan_execution():
    ctx = ShortTermContext()
    plan, _ = parse_plan("open chrome and close vscode", ctx)
    assert plan is not None
    
    # Execute step 1: open chrome (SAFE)
    resp, req_conf, complete, result = execute_plan_step(plan)
    assert not req_conf
    assert not complete
    assert plan.current_step_index == 1
    assert plan.state == PlanState.EXECUTING
    
    # Execute step 2: close vscode (CONFIRM)
    resp, req_conf, complete, result = execute_plan_step(plan)
    assert req_conf
    assert not complete
    assert plan.current_step_index == 1
    assert plan.state == PlanState.WAITING_FOR_CONFIRMATION
    
    # Simulate confirmation received
    plan.state = PlanState.EXECUTING
    resp, req_conf, complete, result = execute_plan_step(plan, is_confirmed=True)
    assert not req_conf
    assert complete
    assert plan.current_step_index == 2
    assert plan.state == PlanState.COMPLETED
    
    print("ALL PLAN EXECUTION TESTS PASSED")

if __name__ == "__main__":
    test_plan_execution()
