"""
UNIT TEST — Phase 23 Goal Lifecycle & Multi-Turn Entity Persistence
================================================────────────────=====
Tests GoalContext lifecycle, entity accumulation across turns, and state transitions.
"""
from friday.core.conversation import ConversationManager
from friday.planning.goal_models import GoalContext, GoalState
from friday.intent.models import Action, Intent
from friday.planning.plan_models import ActionPlan


def test_goal_context_initialization_and_touch():
    gc = GoalContext(objective="Find my resume and open it")
    assert gc.state == GoalState.IDLE
    assert gc.objective == "Find my resume and open it"
    assert gc.goal_id.startswith("g-")
    assert len(gc.completed_steps) == 0

    t0 = gc.updated_at
    gc.touch()
    assert gc.updated_at >= t0


def test_goal_context_multi_turn_entity_persistence():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()

    # Turn 1: search for python tutorials
    resp1, keep1 = cm.handle_transcript("search for python tutorials")
    assert keep1
    assert cm.context.current_goal is not None
    assert cm.context.current_goal.state == GoalState.COMPLETED
    assert "last_target" in cm.context.current_goal.entities
    assert cm.context.current_goal.entities["last_target"] == "python tutorials"

    # Turn 2: open the first result (entity resolved from current_goal.entities / search results)
    resp2, keep2 = cm.handle_transcript("open the first result")
    assert keep2
    assert "Would open" in resp2 or "Opening" in resp2 or "go to" in resp2.lower()


def test_goal_state_transitions_during_confirmation():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()

    # Trigger action requiring confirmation
    cm.handle_transcript("close chrome")
    assert cm.context.current_goal is not None
    assert cm.context.current_goal.state == GoalState.WAITING_FOR_USER

    # Confirm action
    cm.handle_transcript("yes")
    assert cm.context.current_goal.state == GoalState.COMPLETED
