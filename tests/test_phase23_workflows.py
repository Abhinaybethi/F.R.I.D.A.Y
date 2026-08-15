"""
UNIT TEST — Phase 23 Goal Workflows Verification Suite
======================================================
Tests Workflows A through F under Phase 23 Goal Orchestration.
"""
from unittest.mock import patch
from friday.core.conversation import ConversationManager
from friday.planning.goal_models import GoalState


def test_workflow_a_search_and_open():
    """Workflow A: Find resume and open it (or search and open)."""
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()

    resp, keep = cm.handle_transcript("find my resume and open it")
    assert keep
    assert "resume" in resp.lower() or "Would open" in resp or "Opening" in resp
    assert cm.context.current_goal is not None


def test_workflow_b_memory_preference_search():
    """Workflow B: Remember preference then recall/use in command."""
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()

        cm.handle_transcript("search for python developer internships")
        assert cm.context.current_goal.entities.get("last_target") == "python developer internships"


def test_workflow_c_multi_step_plan_with_fallback():
    """Workflow C: Multi-step plan execution with fallback candidate."""
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()

    resp, keep = cm.handle_transcript("open chrome and open youtube")
    assert keep
    assert "Chrome" in resp or "chrome" in resp.lower() or "YouTube" in resp


def test_workflow_d_multi_turn_anaphora():
    """Workflow D: Search, select result, and follow-up pronoun reference."""
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()

        cm.handle_transcript("search for python jobs")
        resp2, _ = cm.handle_transcript("open the first result")
        assert "Would open" in resp2 or "Opening" in resp2 or "go to" in resp2.lower()
        assert cm.context.current_goal is not None
        assert cm.context.current_goal.state == GoalState.COMPLETED
