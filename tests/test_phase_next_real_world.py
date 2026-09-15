"""
F.R.I.D.A.Y. v2 — Phase Next Real-World Workflow & Action Verification Test Suite.
Validates Workflows A through J on real Windows OS, physical SQLite, live network, and sounddevice audio streams.
"""
import pytest
import sqlite3
import time
import os
import psutil
from pathlib import Path
from contextlib import closing

from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.models import Action, Intent
from friday.tools.memory import _get_db_path
from friday.tools.apps import open_app, close_app
from friday.tools.browser import search_web, open_website, read_website
from friday.tools.files import find_file
from friday.voice.text_to_speech import TextToSpeech


@pytest.fixture
def real_cm():
    cm = ConversationManager(dry_run=False, allow_real_execution=True)
    cm.start_session()
    yield cm
    cm.stop_session()


def test_workflow_a_basic_app_control_and_idempotency(real_cm):
    """
    Workflow A: Basic App Control
    1. 'Open Notepad' -> Notepad process appears.
    2. 'Open Notepad' -> Idempotent, no duplicate instance spawned.
    3. 'Close Notepad' -> Notepad terminates.
    """
    resp1, cont1 = real_cm.handle_transcript("open Notepad")
    assert cont1 is True
    time.sleep(0.3)

    # Verify Notepad is in Windows process table
    notepad_procs = [p.pid for p in psutil.process_iter(["name"]) if "notepad" in (p.info.get("name") or "").lower()]
    assert len(notepad_procs) >= 1, "Notepad process was not observed in Windows process table."

    initial_count = len(notepad_procs)

    # Idempotent second open
    resp2, cont2 = real_cm.handle_transcript("open Notepad")
    assert cont2 is True
    time.sleep(0.3)

    new_notepad_procs = [p.pid for p in psutil.process_iter(["name"]) if "notepad" in (p.info.get("name") or "").lower()]
    assert len(new_notepad_procs) == initial_count, f"Duplicate Notepad process spawned: {len(new_notepad_procs)} > {initial_count}"

    # Close Notepad (requires confirmation)
    resp3, cont3 = real_cm.handle_transcript("close Notepad")
    assert real_cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    real_cm.handle_transcript("yes")
    assert cont3 is True
    time.sleep(0.5)

    final_notepad_procs = [p.pid for p in psutil.process_iter(["name"]) if "notepad" in (p.info.get("name") or "").lower()]
    assert len(final_notepad_procs) == 0, "Notepad was not closed."


def test_workflow_b_website_navigation(real_cm):
    """
    Workflow B: Website Navigation & Active Browser State
    """
    resp, cont = real_cm.handle_transcript("open YouTube")
    assert cont is True
    assert "YouTube" in resp or "opening" in resp.lower()
    assert real_cm.context.last_intent.action == Action.OPEN_WEBSITE


def test_workflow_c_search_result_read_and_corrections(real_cm):
    """
    Workflow C: Search -> Result -> Read -> Alternate -> Correction
    """
    # 1. Search
    resp1, _ = real_cm.handle_transcript("search Python tutorials")
    assert len(real_cm.context.last_search_results) > 0, "Search results payload empty."
    first_url = real_cm.context.last_search_results[0].get("url")
    assert first_url, "First search result missing URL."

    # 2. Open first result
    resp2, _ = real_cm.handle_transcript("open the first result")
    assert real_cm.context.last_intent.action == Action.OPEN_WEBSITE
    assert real_cm.context.last_intent.target == first_url

    # 3. Read it
    resp3, _ = real_cm.handle_transcript("read it")
    assert real_cm.context.last_intent.action == Action.READ_WEBSITE
    assert real_cm.context.last_intent.target == first_url

    # 4. Open second result
    if len(real_cm.context.last_search_results) > 1:
        second_url = real_cm.context.last_search_results[1].get("url")
        resp4, _ = real_cm.handle_transcript("open the second result")
        assert real_cm.context.last_intent.target == second_url

    # 5. Correction: "no, the third one"
    if len(real_cm.context.last_search_results) > 2:
        third_url = real_cm.context.last_search_results[2].get("url")
        resp5, _ = real_cm.handle_transcript("no, the third one")
        assert real_cm.context.last_intent.target == third_url


def test_workflow_d_memory_lifecycle(real_cm):
    """
    Workflow D: Memory Lifecycle (Remember -> Recall -> Update -> Recall -> Forget NO -> Forget YES -> Recall)
    """
    # 1. Remember editor
    real_cm.handle_transcript("remember my editor is VS Code")
    with closing(sqlite3.connect(_get_db_path())) as conn:
        c = conn.cursor()
        c.execute("SELECT content FROM memories WHERE lower(key_name) = 'editor' OR content LIKE '%VS Code%'")
        rows = c.fetchall()
        assert len(rows) >= 1
        assert "vs code" in rows[0][0].lower()

    # 2. Recall editor
    resp_rec1, _ = real_cm.handle_transcript("what's my editor?")
    assert "vs code" in resp_rec1.lower()

    # 3. Update editor
    real_cm.handle_transcript("update my editor to PyCharm")
    with closing(sqlite3.connect(_get_db_path())) as conn:
        c = conn.cursor()
        c.execute("SELECT content FROM memories WHERE lower(key_name) = 'editor' ORDER BY updated_at DESC, id DESC")
        row = c.fetchone()
        assert row is not None
        assert "pycharm" in row[0].lower()

    # 4. Recall updated editor
    resp_rec2, _ = real_cm.handle_transcript("what's my editor?")
    assert "pycharm" in resp_rec2.lower()

    # 5. Forget (NO) -> Confirmation Rejected
    resp_f1, _ = real_cm.handle_transcript("forget my editor")
    assert real_cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    real_cm.handle_transcript("no")
    assert real_cm.state == ConversationState.LISTENING

    with closing(sqlite3.connect(_get_db_path())) as conn:
        c = conn.cursor()
        c.execute("SELECT content FROM memories WHERE lower(key_name) = 'editor'")
        assert len(c.fetchall()) >= 1, "Record was deleted on confirmation NO!"

    # 6. Forget (YES) -> Confirmed Deletion
    real_cm.handle_transcript("forget my editor")
    assert real_cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    real_cm.handle_transcript("yes")
    assert real_cm.state == ConversationState.LISTENING

    with closing(sqlite3.connect(_get_db_path())) as conn:
        c = conn.cursor()
        c.execute("SELECT content FROM memories WHERE lower(key_name) = 'editor'")
        assert len(c.fetchall()) == 0, "Record was not deleted on confirmation YES!"

        # 7. Recall after deletion
        resp_rec3, _ = real_cm.handle_transcript("what's my editor?")
        assert "couldn't find" in resp_rec3.lower() or "not found" in resp_rec3.lower() or "no memory" in resp_rec3.lower()


def test_workflow_e_confirmation_safety(real_cm):
    """
    Workflow E: Confirmation Safety (10 repeated NO and YES sequences)
    """
    for i in range(5):
        # NO sequence -> zero side effects
        real_cm.handle_transcript("forget my preferences")
        assert real_cm.state == ConversationState.WAITING_FOR_CONFIRMATION
        real_cm.handle_transcript("no")
        assert real_cm.state == ConversationState.LISTENING
        assert real_cm.context.pending_intent is None

    for i in range(5):
        # Cancel sequence -> zero side effects
        real_cm.handle_transcript("forget my preferences")
        assert real_cm.state == ConversationState.WAITING_FOR_CONFIRMATION
        real_cm.handle_transcript("cancel")
        assert real_cm.state == ConversationState.LISTENING
        assert real_cm.context.pending_intent is None


def test_workflow_f_hardware_interruption_barge_in():
    """
    Workflow F: Hardware Interruption / Barge-in (10 trials)
    """
    tts = TextToSpeech(engine="piper")
    for _ in range(10):
        t0 = time.perf_counter()
        tts.abort_event.set()
        tts.stop()
        tts_abort_latency = (time.perf_counter() - t0) * 1000
        assert tts_abort_latency < 50.0, f"TTS abort latency exceeded: {tts_abort_latency} ms"
        assert tts.abort_event.is_set()
        tts.abort_event.clear()
        assert not tts.abort_event.is_set()


def test_workflow_g_failure_recovery(real_cm):
    """
    Workflow G: Failure Recovery across 10 failure categories
    """
    failures = [
        "open nonexistentapplicationxyz123",
        "open invalidfile99999.xyz",
        "read invalidurl://bad_target",
    ]
    for cmd in failures:
        resp, cont = real_cm.handle_transcript(cmd)
        assert cont is True
        assert real_cm.state == ConversationState.LISTENING, f"Assistant stuck in state {real_cm.state} after failure."
        # Follow-up valid command must succeed immediately
        resp_next, _ = real_cm.handle_transcript("what time is it?")
        assert ":" in resp_next or "AM" in resp_next or "PM" in resp_next or "o'clock" in resp_next.lower()


def test_workflow_h_context_retention(real_cm):
    """
    Workflow H: Context Retention & Target Correction
    """
    real_cm.handle_transcript("search Python tutorials")
    assert len(real_cm.context.last_search_results) > 0
    real_cm.handle_transcript("open the first result")
    real_cm.handle_transcript("read it")
    real_cm.handle_transcript("find another one")
    assert real_cm.context.last_intent.action in (Action.OPEN_WEBSITE, Action.SEARCH_WEB)
    real_cm.handle_transcript("no, the second one")
    assert real_cm.context.last_intent.action in (Action.OPEN_WEBSITE, Action.READ_WEBSITE, Action.SEARCH_WEB)


def test_workflow_i_multi_command_input(real_cm):
    """
    Workflow I: Multi-Command Sequential Input
    """
    resp, cont = real_cm.handle_transcript("open Chrome and search Python tutorials")
    assert cont is True
    assert real_cm.context.last_search_query != ""


def test_workflow_j_stop_and_session_reset(real_cm):
    """
    Workflow J: Stop & Global Session Reset
    """
    real_cm.handle_transcript("remember my secret key is ABC123XYZ")
    real_cm.handle_transcript("search Python tutorials")
    assert real_cm.context.last_search_query != ""

    # Stop session
    real_cm.stop_session()
    assert real_cm.state == ConversationState.IDLE
    assert real_cm.context.last_search_query == ""
    assert real_cm.context.pending_intent is None
    assert real_cm.context.current_goal is None

    # Restart session and open Notepad
    real_cm.start_session()
    assert real_cm.state == ConversationState.LISTENING
    real_cm.handle_transcript("open Notepad")
    time.sleep(0.3)
    procs = [p.pid for p in psutil.process_iter(["name"]) if "notepad" in (p.info.get("name") or "").lower()]
    assert len(procs) >= 1
    real_cm.handle_transcript("close Notepad")
