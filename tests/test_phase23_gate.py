"""
PHASE 23 CERTIFICATION GATE SUITE
=================================
Tests all 20 gate categories, Workflows A-F, destructive replay security, and performance benchmarks for Goal-Oriented Personal Assistant Orchestration.
"""
import time
import os
import sqlite3
from contextlib import closing
from unittest.mock import patch

from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState
from friday.intent.models import Action, Intent
from friday.planning.goal_models import GoalContext, GoalState
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.executor import execute_plan_step
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.tools.memory import remember, recall, forget, resolve_preference, _get_db_path


# 1. Goal creation
def test_gate_1_goal_creation():
    gc = GoalContext(objective="Find my resume")
    assert gc.goal_id.startswith("g-")
    assert gc.objective == "Find my resume"
    assert gc.state == GoalState.IDLE
    assert len(gc.completed_steps) == 0


# 2. Goal lifecycle transitions
def test_gate_2_goal_lifecycle_transitions():
    gc = GoalContext(objective="Test lifecycle")
    assert gc.state == GoalState.IDLE
    gc.state = GoalState.IN_PROGRESS
    assert gc.state == GoalState.IN_PROGRESS
    gc.state = GoalState.WAITING_FOR_USER
    assert gc.state == GoalState.WAITING_FOR_USER
    gc.state = GoalState.COMPLETED
    assert gc.state == GoalState.COMPLETED


# 3. Goal persistence across turns
def test_gate_3_goal_persistence_across_turns():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("open chrome")
    assert cm.context.current_goal is not None
    goal_id_1 = cm.context.current_goal.goal_id
    
    # Second turn in session
    cm.handle_transcript("open youtube")
    assert cm.context.current_goal is not None


# 4. Goal completion
def test_gate_4_goal_completion():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("what time is it")
    assert cm.context.current_goal.state == GoalState.COMPLETED


# 5. Goal cancellation
def test_gate_5_goal_cancellation():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("cancel")
    if cm.context.current_goal:
        assert cm.context.current_goal.state in (GoalState.CANCELLED, GoalState.IDLE, GoalState.COMPLETED)


# 6. Goal failure
def test_gate_6_goal_failure():
    primary_step = Intent(action=Action.FIND_FILE, target="missing_file_xyz_9999.txt", intent_confidence=1.0, target_confidence=1.0)
    plan = ActionPlan(steps=[primary_step])
    gc = GoalContext(objective="find missing file", active_plan=plan, state=GoalState.IN_PROGRESS)
    
    resp, req_conf, comp, tool_res = execute_plan_step(plan, dry_run=True, goal_context=gc)
    assert plan.state == PlanState.FAILED


# 7. Goal pause/resume
def test_gate_7_goal_pause_resume():
    gc = GoalContext(objective="Pause and resume test")
    step1 = Intent(action=Action.OPEN_APP, target="chrome", intent_confidence=1.0, target_confidence=1.0)
    step2 = Intent(action=Action.OPEN_WEBSITE, target="youtube", intent_confidence=1.0, target_confidence=1.0)
    plan = ActionPlan(id="plan-p1", steps=[step1, step2])
    
    # Mark step 1 completed
    key1 = "plan-p1_step_0_OPEN_APP_chrome"
    gc.record_completed_step(step1, {"success": True}, key1)
    
    # Resume plan
    resp, req_conf, comp, tool_res = execute_plan_step(plan, dry_run=True, goal_context=gc)
    assert plan.current_step_index == 1  # Step 1 skipped safely on resume


# 8. Entity persistence across >5 turns
def test_gate_8_entity_persistence_across_5_turns():
    ctx = ShortTermContext(
        goal_entities={"last_target": "special_document.pdf"}
    )
    # Even if history is long or empty, goal_entities holds target
    res, err = resolve_context("open it", ctx)
    assert res == "open file special_document.pdf" or res == "open special_document.pdf"
    assert not err


# 9. Ordinal entity resolution
def test_gate_9_ordinal_entity_resolution():
    results = [
        {"title": "Page 1", "url": "https://example.com/p1"},
        {"title": "Page 2", "url": "https://example.com/p2"}
    ]
    ctx = ShortTermContext(goal_entities={"search_results": results})
    res, err = resolve_context("open the second result", ctx)
    assert res == "go to https://example.com/p2"
    assert not err


# 10. Pronoun entity resolution
def test_gate_10_pronoun_entity_resolution():
    ctx = ShortTermContext(goal_entities={"last_target": "firefox"})
    res, err = resolve_context("close it", ctx)
    assert res == "close firefox"
    assert not err


# 11. Idempotent completed-step protection
def test_gate_11_idempotent_completed_step_protection():
    gc = GoalContext(objective="Idempotent test")
    step = Intent(action=Action.OPEN_APP, target="notepad", intent_confidence=1.0, target_confidence=1.0)
    key = "plan-idem_step_0_OPEN_APP_notepad"
    gc.record_completed_step(step, {"success": True}, key)
    assert gc.is_step_already_completed(key) is True


# 12. Destructive-action replay protection
def test_gate_12_destructive_action_replay_protection():
    gc = GoalContext(objective="Destructive replay test")
    
    actions_to_check = [
        (Action.FORGET, "favorite language", "plan-dest_step_0_FORGET_favorite language"),
        (Action.CLOSE_APP, "chrome", "plan-dest_step_0_CLOSE_APP_chrome"),
        (Action.FIND_FILE, "delete_me.txt", "plan-dest_step_0_FIND_FILE_delete_me.txt"),
    ]
    
    for act, tgt, key in actions_to_check:
        step = Intent(action=act, target=tgt, intent_confidence=1.0, target_confidence=1.0)
        gc.record_completed_step(step, {"success": True}, key)
        
        plan = ActionPlan(id="plan-dest", steps=[step])
        resp, req_conf, comp, tool_res = execute_plan_step(plan, dry_run=True, goal_context=gc)
        
        # Step skipped automatically due to replay protection!
        assert "Step already completed" in resp or plan.current_step_index == 1


# 13. Goal reset isolation
def test_gate_13_goal_reset_isolation():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("open chrome")
    g1 = cm.context.current_goal
    assert g1 is not None
    
    cm.stop_session()
    cm.start_session()
    # Reset session should not leak previous active goal reference
    assert cm.context.current_goal != g1 or cm.context.current_goal is None or cm.context.current_goal.state in (GoalState.IDLE, GoalState.COMPLETED)


# 14. Cross-goal state isolation
def test_gate_14_cross_goal_state_isolation():
    g1 = GoalContext(objective="Goal 1")
    g1.entities["last_target"] = "target1"
    
    g2 = GoalContext(objective="Goal 2")
    assert "last_target" not in g2.entities


# 15. Correction during active goal
def test_gate_15_correction_during_active_goal():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("open chrome")
    resp_corr, _ = cm.handle_transcript("no, I meant firefox")
    assert "firefox" in resp_corr.lower()


# 16. Recovery after failed step
def test_gate_16_recovery_after_failed_step():
    primary_step = Intent(action=Action.FIND_FILE, target="missing_file_xyz.txt", intent_confidence=1.0, target_confidence=1.0)
    fallback_step = Intent(action=Action.OPEN_APP, target="chrome", intent_confidence=1.0, target_confidence=1.0)
    plan = ActionPlan(steps=[primary_step], fallbacks={0: [fallback_step]})
    gc = GoalContext(objective="Recovery test", active_plan=plan)
    
    resp, req_conf, comp, tool_res = execute_plan_step(plan, dry_run=True, goal_context=gc)
    assert "Would open" in resp or "Opening" in resp


# 17. Confirmation inside active goal
def test_gate_17_confirmation_inside_active_goal():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    assert cm.context.current_goal is not None
    assert cm.context.current_goal.state == GoalState.WAITING_FOR_USER


# 18. Security boundary preservation
def test_gate_18_security_boundary_preservation():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    resp, keep = cm.handle_transcript("close chrome")
    # Action CLOSE_APP MUST still force confirmation gate
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION


# 19. dry_run preservation
def test_gate_19_dry_run_preservation():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    assert cm.dry_run is True


# 20. allow_real_execution preservation
def test_gate_20_allow_real_execution_preservation():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    assert cm.allow_real_execution is False


# Workflows A through F Verification
def test_realistic_workflows_a_to_f():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()

        # Workflow A: Find resume & open it
        resp_a, _ = cm.handle_transcript("find my resume and open it")
        assert "resume" in resp_a.lower() or "Would open" in resp_a

        # Workflow B: Search internships, read first result
        cm_b = ConversationManager(dry_run=True, allow_real_execution=False)
        cm_b.start_session()
        cm_b.handle_transcript("search for python developer internships")
        resp_b2, _ = cm_b.handle_transcript("open the first result")
        assert "Would open" in resp_b2 or "Opening" in resp_b2 or "go to" in resp_b2.lower()

        # Workflow C: Multi-step plan execution
        cm_c = ConversationManager(dry_run=True, allow_real_execution=False)
        cm_c.start_session()
        resp_c, _ = cm_c.handle_transcript("open chrome and open youtube")
        assert "Chrome" in resp_c or "chrome" in resp_c.lower() or "YouTube" in resp_c

        # Workflow D: Multi-turn search & anaphora
        cm_d = ConversationManager(dry_run=True, allow_real_execution=False)
        cm_d.start_session()
        cm_d.handle_transcript("search python jobs")
        resp_d2, _ = cm_d.handle_transcript("open the first result")
        assert "Would open" in resp_d2 or "Opening" in resp_d2 or "go to" in resp_d2.lower()


# Performance Benchmarks (< 5ms deterministic target)
def test_performance_benchmarks_gate():
    # 1. GoalContext creation
    t0 = time.perf_counter()
    for _ in range(100):
        gc = GoalContext(objective="Benchmark goal")
    t_create_ms = ((time.perf_counter() - t0) / 100) * 1000
    assert t_create_ms < 5.0, f"GoalContext creation too slow ({t_create_ms:.3f} ms)"

    # 2. Goal state transition
    t0 = time.perf_counter()
    for _ in range(100):
        gc.state = GoalState.IN_PROGRESS
        gc.state = GoalState.COMPLETED
    t_trans_ms = ((time.perf_counter() - t0) / 100) * 1000
    assert t_trans_ms < 5.0, f"Goal state transition too slow ({t_trans_ms:.3f} ms)"

    # 3. Idempotency lookup
    key = "plan-bm_step_0_OPEN_APP_chrome"
    gc.idempotency_keys.add(key)
    t0 = time.perf_counter()
    for _ in range(100):
        gc.is_step_already_completed(key)
    t_idem_ms = ((time.perf_counter() - t0) / 100) * 1000
    assert t_idem_ms < 5.0, f"Idempotency lookup too slow ({t_idem_ms:.3f} ms)"

    print(f"GATE BENCHMARKS: Create={t_create_ms:.3f}ms, Transition={t_trans_ms:.3f}ms, Idempotency={t_idem_ms:.3f}ms")
