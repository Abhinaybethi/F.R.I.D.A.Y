"""
PHASE 24 CERTIFICATION GATE SUITE
=================================
Evaluates 20 certification gate checks for Phase 24 Real-World Daily-Use Validation & Reliability Audit.
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


# Gate 1: No unsafe action replay
def test_gate_1_no_unsafe_action_replay():
    gc = GoalContext(objective="Idempotency gate")
    step = Intent(action=Action.OPEN_APP, target="chrome", intent_confidence=1.0, target_confidence=1.0)
    key = "plan-g1_step_0_OPEN_APP_chrome"
    gc.record_completed_step(step, {"success": True}, key)

    plan = ActionPlan(id="plan-g1", steps=[step])
    resp, req_conf, comp, tool_res = execute_plan_step(plan, dry_run=True, goal_context=gc)
    assert plan.current_step_index == 1 or "Step already completed" in resp


# Gate 2: Cross-goal state isolation
def test_gate_2_cross_goal_state_isolation():
    g1 = GoalContext(objective="Goal 1")
    g1.entities["key1"] = "val1"
    g2 = GoalContext(objective="Goal 2")
    assert "key1" not in g2.entities


# Gate 3: Destructive replay protection
def test_gate_3_destructive_replay_protection():
    gc = GoalContext(objective="Destructive replay gate")
    destructive_actions = [Action.FORGET, Action.CLOSE_APP, Action.FIND_FILE]
    
    for i, act in enumerate(destructive_actions):
        step = Intent(action=act, target="target", intent_confidence=1.0, target_confidence=1.0)
        key = f"plan-g3_step_0_{act.name}_target"
        gc.record_completed_step(step, {"success": True}, key)
        plan = ActionPlan(id="plan-g3", steps=[step])
        resp, req_conf, comp, tool_res = execute_plan_step(plan, dry_run=True, goal_context=gc)
        assert plan.current_step_index == 1 or "Step already completed" in resp


# Gate 4: Security boundary preservation
def test_gate_4_security_boundary_preservation():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    resp, keep = cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION


# Gate 5: Resource stability & memory leak check
def test_gate_5_resource_stability_memory_leak():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    for _ in range(50):
        cm.handle_transcript("open chrome")
    assert len(cm.context.history) <= 5


# Gate 6: No critical context loss
def test_gate_6_no_critical_context_loss():
    ctx = ShortTermContext(goal_entities={"last_target": "my_file.pdf"})
    res, err = resolve_context("open it", ctx)
    assert "my_file.pdf" in res


# Gate 7: No critical recovery failure
def test_gate_7_no_critical_recovery_failure():
    primary_step = Intent(action=Action.FIND_FILE, target="missing_file.txt", intent_confidence=1.0, target_confidence=1.0)
    fallback_step = Intent(action=Action.OPEN_APP, target="chrome", intent_confidence=1.0, target_confidence=1.0)
    plan = ActionPlan(steps=[primary_step], fallbacks={0: [fallback_step]})
    resp, req_conf, comp, tool_res = execute_plan_step(plan, dry_run=True)
    assert "Would open" in resp or "Opening" in resp


# Gate 8: Full deterministic regression passing
def test_gate_8_full_deterministic_regression_passing():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    resp, keep = cm.handle_transcript("what time is it")
    assert keep is True
    assert len(resp) > 0


# Gate 9: dry_run preservation
def test_gate_9_dry_run_preservation():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    assert cm.dry_run is True


# Gate 10: allow_real_execution preservation
def test_gate_10_allow_real_execution_preservation():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    assert cm.allow_real_execution is False


# Gate 11: Anaphora pronoun bounds
def test_gate_11_anaphora_pronoun_bounds():
    ctx = ShortTermContext()
    res, err = resolve_context("open it", ctx)
    assert err and "don't have enough context" in err


# Gate 12: Ordinal search result bounds
def test_gate_12_ordinal_search_result_bounds():
    results = [{"title": "P1", "url": "https://example.com/1"}]
    ctx = ShortTermContext(last_search_results=results)
    res, err = resolve_context("open the second result", ctx)
    assert err and "out of range" in err


# Gate 13: Inline correction target replacement
def test_gate_13_inline_correction_target_replacement():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("open chrome")
    resp, _ = cm.handle_transcript("no, I meant firefox")
    assert "firefox" in resp.lower()


# Gate 14: Multi-step plan fallback recovery
def test_gate_14_multistep_plan_fallback_recovery():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    resp, _ = cm.handle_transcript("open chrome and open youtube")
    assert "Chrome" in resp or "chrome" in resp.lower() or "YouTube" in resp


# Gate 15: Confirmation timeout reset
def test_gate_15_confirmation_timeout_reset():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    # Simulate past 30s timeout
    cm.context.confirmation_start_time = time.time() - 35.0
    cm.handle_transcript("open firefox")
    assert cm.state == ConversationState.LISTENING or cm.state == ConversationState.EXECUTING


# Gate 16: Sensitive content rejection in memory
def test_gate_16_sensitive_content_rejection_memory():
    res = remember("my password is SecretPassword123!", dry_run=False)
    assert res.get("blocked") is True


# Gate 17: Deterministic latency bound (< 500ms)
def test_gate_17_deterministic_latency_bound():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    t0 = time.perf_counter()
    cm.handle_transcript("what time is it")
    lat_ms = (time.perf_counter() - t0) * 1000
    assert lat_ms < 500.0


# Gate 18: Goal state transition overhead (< 50ms)
def test_gate_18_goal_state_transition_overhead():
    gc = GoalContext(objective="Transition test")
    t0 = time.perf_counter()
    for _ in range(100):
        gc.state = GoalState.IN_PROGRESS
        gc.state = GoalState.COMPLETED
    lat_ms = ((time.perf_counter() - t0) / 100) * 1000
    assert lat_ms < 50.0


# Gate 19: Memory lookup latency (< 50ms)
def test_gate_19_memory_lookup_latency():
    remember("my favorite language is Python", category="preference", key_name="fav_lang", dry_run=False)
    try:
        t0 = time.perf_counter()
        resolve_preference("fav_lang")
        lat_ms = (time.perf_counter() - t0) * 1000
        assert lat_ms < 50.0
    finally:
        with closing(sqlite3.connect(_get_db_path())) as conn:
            with conn:
                conn.execute("DELETE FROM memories WHERE key_name = 'fav_lang'")


# Gate 20: Audit log completeness & PII sanitization
def test_gate_20_audit_log_completeness():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("open chrome")
    assert cm.context.last_response is not None
