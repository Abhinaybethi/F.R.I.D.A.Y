import os
import sys

# Ensure friday is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.planning.planner import parse_plan
from friday.planning.context_resolver import ShortTermContext
from friday.intent.models import Action

def test_planner():
    ctx = ShortTermContext()
    
    # Test 1: "open chrome and search for python tutorials"
    plan, err = parse_plan("open chrome and search for python tutorials", ctx)
    assert not err, f"Error: {err}"
    assert plan is not None
    assert len(plan.steps) == 2
    assert plan.steps[0].action == Action.OPEN_APP
    assert plan.steps[0].target == "chrome"
    assert plan.steps[1].action == Action.SEARCH_WEB
    assert plan.steps[1].target == "python tutorials"
    
    # Test 2: "open youtube and search for java tutorials"
    plan, err = parse_plan("open youtube and search for java tutorials", ctx)
    assert not err
    assert len(plan.steps) == 2
    assert plan.steps[0].action == Action.OPEN_WEBSITE
    assert plan.steps[0].target == "youtube"
    assert plan.steps[1].action == Action.SEARCH_WEB
    assert plan.steps[1].target == "java tutorials"
    
    # Test 3: Plan with > 5 steps
    long_command = "open chrome and open youtube and open google and open github and get time and cancel"
    plan, err = parse_plan(long_command, ctx)
    assert plan is None
    assert "five actions" in err
    
    # Test 4: Unknown action inside a plan
    plan, err = parse_plan("open chrome and bloop bleep", ctx)
    assert plan is None
    assert "didn't understand part" in err
    
    print("ALL PLANNER TESTS PASSED")

if __name__ == "__main__":
    test_planner()
