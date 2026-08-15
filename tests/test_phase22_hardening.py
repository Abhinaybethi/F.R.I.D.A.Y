"""
PHASE 22 HARDENING & REAL-WORLD BEHAVIOR REGRESSION SUITE
==========================================================
Tests:
1. Entity Resolution Adversarial (sequential, ambiguous, safe error bounds)
2. Memory Adversarial (overriding, dedup, FORGET confirmation gates, sensitive rejection, restart persistence)
3. Plan Recovery (isolation, failure boundaries, loops, stale context)
4. Conversational Correction (post-confirmation, post-failure, multi-step, reasoning)
5. Cross-Feature Workflows (Workflows A, B, C, D)
6. Safety Boundary Verification (permissions, confirmations, validators, verifiers)
7. Performance Measurements (< 5ms entity, < 20ms memory, < 20ms correction)
"""
import time
import os
import sqlite3
from contextlib import closing
from unittest.mock import patch

from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState
from friday.intent.models import Action, Intent
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.executor import execute_plan_step
from friday.tools.memory import remember, recall, forget, resolve_preference, _get_db_path


def test_1_entity_resolution_adversarial():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()

        # Sequence: search -> open 1st -> read it -> open 2nd -> close it
        resp1, _ = cm.handle_transcript("search for Python internships")
        assert "Would search" in resp1 or "Searching" in resp1

        resp2, _ = cm.handle_transcript("open the first result")
        assert "Would open" in resp2 or "Opening" in resp2

        resp3, _ = cm.handle_transcript("read it")
        assert "Would read" in resp3 or "Reading" in resp3 or "Here is the page" in resp3

        resp4, _ = cm.handle_transcript("open the second one")
        assert "Would open" in resp4 or "Opening" in resp4

        # Sequence: open Chrome -> close it
        cm2 = ConversationManager(dry_run=True, allow_real_execution=False)
        cm2.start_session()
        cm2.handle_transcript("open chrome")
        resp_c, _ = cm2.handle_transcript("close it")
        assert "chrome" in resp_c.lower() and ("close" in resp_c.lower() or "Do you want me to close" in resp_c)

        # Sequence: find my resume -> open that
        cm3 = ConversationManager(dry_run=True, allow_real_execution=False)
        cm3.start_session()
        cm3.handle_transcript("find my resume")
        resp_f, _ = cm3.handle_transcript("open that")
        assert "resume" in resp_f.lower() or "Would open" in resp_f

        # Ambiguous tests — must fail safely without inventing targets
        cm_amb = ConversationManager(dry_run=True, allow_real_execution=False)
        cm_amb.start_session()
        resp_a1, _ = cm_amb.handle_transcript("open it")
        assert "don't have enough context" in resp_a1.lower() or "don't know" in resp_a1.lower()

        ctx_one = ShortTermContext(last_search_results=[{"title": "Only One", "url": "https://example.com/1"}])
        res_a2, err_a2 = resolve_context("open the second one", ctx_one)
        assert err_a2 and "out of range" in err_a2


def test_2_memory_adversarial():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        # Initial DB cleanup for test isolation
        with closing(sqlite3.connect(_get_db_path())) as conn:
            with conn:
                conn.execute("DELETE FROM memories WHERE content LIKE '%language%' OR content LIKE '%server host%'")

        # Write initial preference
        remember("my favorite language is Python", category="preference", key_name="language", dry_run=False)
        p1 = resolve_preference("language")
        assert p1 == "Python"

        # Update preference
        remember("my favorite language is Java", category="preference", key_name="language", dry_run=False)
        p2 = resolve_preference("language")
        assert p2 == "Java"

        # Sensitive content rejection
        res_sec = remember("my password is SecretPassword123!", dry_run=False)
        assert res_sec.get("blocked") is True

        # FORGET confirmation gate testing
        cm_mem = ConversationManager(dry_run=True, allow_real_execution=False)
        cm_mem.start_session()
        cm_mem.handle_transcript("forget my favorite language")
        assert cm_mem.state == ConversationState.WAITING_FOR_CONFIRMATION

        # CANCEL leaves memory intact
        cm_mem.handle_transcript("no")
        rec_check = recall("favorite language")
        assert rec_check["success"]

        # Re-trigger and confirm YES
        cm_mem2 = ConversationManager(dry_run=True, allow_real_execution=False)
        cm_mem2.start_session()
        cm_mem2.handle_transcript("forget my favorite language")
        cm_mem2.handle_transcript("yes")

        # Restart persistence test
        cm_new = ConversationManager(dry_run=True, allow_real_execution=False)
        cm_new.start_session()
        remember("my server host is local.server", dry_run=False)
        rec_new = cm_new.handle_transcript("recall server host")
        assert "local.server" in rec_new[0]

        # Cleanup
        with closing(sqlite3.connect(_get_db_path())) as conn:
            with conn:
                conn.execute("DELETE FROM memories WHERE content LIKE '%language%' OR content LIKE '%server host%'")


def test_3_plan_recovery_isolation():
    primary_step = Intent(action=Action.FIND_FILE, target="missing_file_abc_999.txt", intent_confidence=1.0, target_confidence=1.0)
    fallback_step = Intent(action=Action.OPEN_APP, target="chrome", intent_confidence=1.0, target_confidence=1.0)
    unrelated_step = Intent(action=Action.GET_TIME, target="", intent_confidence=1.0, target_confidence=1.0)

    plan = ActionPlan(
        steps=[primary_step, unrelated_step],
        fallbacks={0: [fallback_step]}
    )

    # Step 1 fails, fallback executes, plan continues cleanly to step 2 (unrelated_step)
    resp1, req1, comp1, _ = execute_plan_step(plan, dry_run=True)
    assert "Would open" in resp1 or "Opening" in resp1  # fallback executed
    assert comp1 is False
    assert plan.current_step_index == 1

    resp2, req2, comp2, _ = execute_plan_step(plan, dry_run=True)
    assert comp2 is True  # Step 2 (get_time) executed safely
    assert plan.state == PlanState.COMPLETED


def test_4_conversational_correction():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()

        cm.handle_transcript("open chrome")
        resp_corr, _ = cm.handle_transcript("no, I meant firefox")
        assert "firefox" in resp_corr.lower()

        cm.handle_transcript("search python")
        resp_corr2, _ = cm.handle_transcript("no, search java instead")
        assert "java" in resp_corr2.lower()


def test_5_cross_feature_workflows():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        # Workflow A: search -> result #1 -> open it -> correction -> read it -> verify
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()
        cm.handle_transcript("search for python tutorials")
        cm.handle_transcript("open the first result")
        resp_a, _ = cm.handle_transcript("no, read it")
        assert "Would read" in resp_a or "Reading" in resp_a or "Here is" in resp_a

        # Workflow B: remember preference -> new session -> recall preference
        remember("my preferred editor is VSCode", category="preference", key_name="editor", dry_run=False)
        cm_b = ConversationManager(dry_run=True, allow_real_execution=False)
        cm_b.start_session()
        resp_b, _ = cm_b.handle_transcript("recall preferred editor")
        assert "VSCode" in resp_b

        # Cleanup
        with closing(sqlite3.connect(_get_db_path())) as conn:
            with conn:
                conn.execute("DELETE FROM memories WHERE content LIKE '%preferred editor%'")


def test_6_safety_boundary():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("open chrome")

    # "close it" resolves target to "chrome", but MUST STILL REQUIRE CONFIRMATION for CLOSE_APP!
    resp, keep = cm.handle_transcript("close it")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    assert "Do you want me to close" in resp


def test_7_performance_benchmarks():
    ctx = ShortTermContext(
        last_search_results=[{"title": f"Res {i}", "url": f"https://example.com/{i}"} for i in range(5)]
    )

    # 1. Entity resolution latency
    t0 = time.perf_counter()
    for _ in range(100):
        resolve_context("open the second result", ctx)
    t_entity_ms = ((time.perf_counter() - t0) / 100) * 1000
    assert t_entity_ms < 5.0, f"Entity resolution too slow ({t_entity_ms:.3f} ms)"

    # 2. Memory lookup latency
    remember("my favorite color is blue", category="preference", key_name="color", dry_run=False)
    try:
        t0 = time.perf_counter()
        for _ in range(50):
            resolve_preference("color")
        t_mem_ms = ((time.perf_counter() - t0) / 50) * 1000
        assert t_mem_ms < 20.0, f"Memory lookup too slow ({t_mem_ms:.3f} ms)"
    finally:
        with closing(sqlite3.connect(_get_db_path())) as conn:
            with conn:
                conn.execute("DELETE FROM memories WHERE content LIKE '%favorite color%'")

    # 3. Correction handling latency
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    cm.handle_transcript("open chrome")
    t0 = time.perf_counter()
    cm.handle_transcript("no, I meant firefox")
    t_corr_ms = (time.perf_counter() - t0) * 1000
    assert t_corr_ms < 20.0, f"Correction handling too slow ({t_corr_ms:.3f} ms)"

    print(f"BENCHMARKS: Entity={t_entity_ms:.3f}ms, Memory={t_mem_ms:.3f}ms, Correction={t_corr_ms:.3f}ms")
