"""
Phase 30 End-to-End Multi-Turn Workflow Tests.

Validates complete workflow lifecycles (Workflows A through H), state integrity,
context preservation, duplicate protection, and confirmation safety.
"""
import pytest
import sqlite3
from contextlib import closing

from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.models import Action, Intent
from friday.tools import memory, browser, files, apps
from friday.verification.models import ExecutionStatus, VerificationStatus


def _get_cm():
    cm = ConversationManager(dry_run=False, allow_real_execution=True)
    cm.start_session()
    return cm


# ----------------------------------------------------------------------
# Workflow A: Search -> Open First -> Read It
# ----------------------------------------------------------------------
def test_workflow_a_search_open_read():
    cm = _get_cm()
    # 1. search Python tutorials
    resp1, cont1 = cm.handle_transcript("search Python tutorials")
    assert "Searching" in resp1 or "results for" in resp1 or "python" in resp1.lower()
    assert cm.context.last_intent.action == Action.SEARCH_WEB
    assert len(cm.context.last_search_results) > 0

    # 2. open first result
    resp2, cont2 = cm.handle_transcript("open first result")
    assert "Opening" in resp2 or "http" in resp2
    assert cm.context.last_intent.action == Action.OPEN_WEBSITE

    # 3. read it
    resp3, cont3 = cm.handle_transcript("read it")
    assert "Reading" in resp3 or "Here is the page content" in resp3 or "http" in resp3 or "python" in resp3.lower()
    assert cm.context.last_intent.action == Action.READ_WEBSITE


# ----------------------------------------------------------------------
# Workflow B: Search -> Open -> Read -> Find Another -> Read Second
# ----------------------------------------------------------------------
def test_workflow_b_search_alternate_results():
    cm = _get_cm()
    # 1. search Python internships
    resp1, cont1 = cm.handle_transcript("search Python internships")
    assert cm.context.last_intent.action == Action.SEARCH_WEB
    assert len(cm.context.last_search_results) > 0

    # 2. open first result
    resp2, cont2 = cm.handle_transcript("open first result")
    assert cm.context.last_intent.action == Action.OPEN_WEBSITE

    # 3. read it
    resp3, cont3 = cm.handle_transcript("read it")
    assert cm.context.last_intent.action == Action.READ_WEBSITE

    # 4. find another one / the second one
    resp4, cont4 = cm.handle_transcript("open the second result")
    assert cm.context.last_intent.action == Action.OPEN_WEBSITE

    # 5. read it
    resp5, cont5 = cm.handle_transcript("read it")
    assert cm.context.last_intent.action == Action.READ_WEBSITE


# ----------------------------------------------------------------------
# Workflow C: Remember -> Recall -> Update -> Recall -> Forget(NO) -> Forget(YES) -> Recall
# ----------------------------------------------------------------------
def test_workflow_c_memory_lifecycle():
    cm = _get_cm()
    # 1. remember my editor is VS Code
    resp1, _ = cm.handle_transcript("remember my editor is VS Code")
    assert "editor" in resp1.lower() or "remember" in resp1.lower() or "already" in resp1.lower()

    # 2. recall my editor
    resp2, _ = cm.handle_transcript("recall my editor")
    assert "vs code" in resp2.lower()

    # 3. update my editor to PyCharm
    resp3, _ = cm.handle_transcript("update my editor to PyCharm")
    assert "editor" in resp3.lower() or "remember" in resp3.lower() or "pycharm" in resp3.lower()

    # 4. recall my editor
    resp4, _ = cm.handle_transcript("recall my editor")
    assert "pycharm" in resp4.lower()

    # 5. forget my editor (confirmation NO)
    resp5, _ = cm.handle_transcript("forget my editor")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    resp6, _ = cm.handle_transcript("no")
    assert resp6 == "Cancelled."
    assert cm.state == ConversationState.LISTENING

    # 6. recall still exists
    resp7, _ = cm.handle_transcript("recall my editor")
    assert "pycharm" in resp7.lower()

    # 7. forget my editor (confirmation YES)
    resp8, _ = cm.handle_transcript("forget my editor")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    resp9, _ = cm.handle_transcript("yes")
    assert "Forgot" in resp9 or "forgotten" in resp9 or "Forgotten" in resp9

    # 8. recall is gone
    resp10, _ = cm.handle_transcript("recall my editor")
    assert "couldn't find" in resp10.lower() or "no memory" in resp10.lower()


# ----------------------------------------------------------------------
# Workflow D: Open Apps & Web Search with Correction
# ----------------------------------------------------------------------
def test_workflow_d_correction_flow():
    cm = _get_cm()
    # 1. open Chrome
    resp1, _ = cm.handle_transcript("open Chrome")
    assert cm.context.last_intent.action == Action.OPEN_APP

    # 2. search Python tutorials
    resp2, _ = cm.handle_transcript("search Python tutorials")
    assert cm.context.last_intent.action == Action.SEARCH_WEB

    # 3. read first result
    resp3, _ = cm.handle_transcript("read the first result")
    assert cm.context.last_intent.action == Action.READ_WEBSITE

    # 4. correction: "no, the second one"
    resp4, _ = cm.handle_transcript("no, the second one")
    assert cm.context.last_intent.action in (Action.OPEN_WEBSITE, Action.READ_WEBSITE)


# ----------------------------------------------------------------------
# Workflow E: Failure -> Recovery -> Next Command
# ----------------------------------------------------------------------
def test_workflow_e_failure_recovery():
    cm = _get_cm()
    # 1. invalid application fails gracefully
    resp1, cont1 = cm.handle_transcript("open fake_invalid_unknown_app_xyz")
    assert "could not locate" in resp1.lower() or "unknown" in resp1.lower() or "didn't understand" in resp1.lower()
    assert cm.state == ConversationState.LISTENING

    # 2. immediate next valid command executes successfully
    resp2, cont2 = cm.handle_transcript("what time is it")
    assert cm.context.last_intent.action == Action.GET_TIME
    assert ":" in resp2 or "The time is" in resp2 or "current time" in resp2.lower()


# ----------------------------------------------------------------------
# Workflow F: Cancellation & Interruption
# ----------------------------------------------------------------------
def test_workflow_f_cancellation():
    cm = _get_cm()
    # 1. search Python
    cm.handle_transcript("search Python")
    assert cm.context.last_search_query != ""

    # 2. user cancels
    resp2, cont2 = cm.handle_transcript("cancel")
    assert resp2 == "Cancelled."
    assert cm.state == ConversationState.LISTENING

    # 3. next command succeeds
    resp3, cont3 = cm.handle_transcript("what time is it")
    assert cm.context.last_intent.action == Action.GET_TIME


# ----------------------------------------------------------------------
# Workflow G: Confirmation NO -> Zero Side Effects
# ----------------------------------------------------------------------
def test_workflow_g_confirmation_no_zero_side_effects():
    memory.remember("favorite recipe is pasta carbonara", dry_run=False)
    cm = _get_cm()

    resp1, _ = cm.handle_transcript("forget favorite recipe is pasta carbonara")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    resp2, _ = cm.handle_transcript("no")
    assert resp2 == "Cancelled."
    assert cm.state == ConversationState.LISTENING

    # Verify zero side effects: memory remains intact
    recalled = memory.recall("pasta carbonara")
    assert recalled["success"] is True
    assert "pasta carbonara" in recalled["message"]

    # Cleanup
    memory.forget("pasta carbonara", dry_run=False)


# ----------------------------------------------------------------------
# Workflow H: Confirmation YES -> Exactly One Side Effect
# ----------------------------------------------------------------------
def test_workflow_h_confirmation_yes_exact_side_effect():
    memory.remember("unique_temp_item_98765", dry_run=False)
    cm = _get_cm()

    resp1, _ = cm.handle_transcript("forget unique_temp_item_98765")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    resp2, _ = cm.handle_transcript("yes")
    assert "Forgot" in resp2 or "forgotten" in resp2 or "Forgotten" in resp2

    # Verify exactly one side effect: memory is deleted
    recalled = memory.recall("unique_temp_item_98765")
    assert recalled["success"] is False
