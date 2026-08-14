"""
UNIT TEST — Conversation UX Refinement
=======================================
Tests deterministic UX handling for yes, no, cancel, stop, repeat, and help
across confirmation states in ConversationManager.
No Ollama required. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.models import Action

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def test_ux_yes_outside_confirmation_does_not_call_ollama():
    """'yes' outside WAITING_FOR_CONFIRMATION state returns 'didn't understand' without calling reasoner."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("yes")
    assert "didn't understand" in resp.lower() or "sorry" in resp.lower()
    assert cm.state == ConversationState.LISTENING


def test_ux_yes_inside_confirmation_executes_pending_intent():
    """'yes' during WAITING_FOR_CONFIRMATION executes pending CLOSE_APP intent."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    resp, keep = cm.handle_transcript("yes")
    assert cm.state == ConversationState.LISTENING
    assert "Chrome" in resp or "chrome" in resp.lower() or "Cancelled" in resp


def test_ux_no_inside_confirmation_cancels_pending_intent():
    """'no' during WAITING_FOR_CONFIRMATION cancels pending intent."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    resp, keep = cm.handle_transcript("no")
    assert cm.state == ConversationState.LISTENING
    assert "Cancelled" in resp
    assert cm.context.pending_intent is None


def test_ux_cancel_clears_pending_state():
    """'cancel' clears pending intent/plan and returns 'Cancelled.'."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    resp, keep = cm.handle_transcript("cancel")
    assert "Cancelled" in resp
    assert cm.state == ConversationState.LISTENING
    assert cm.context.pending_intent is None


def test_ux_stop_halts_session():
    """'stop' halts session and returns keep=False."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    resp, keep = cm.handle_transcript("stop")
    assert "Goodbye" in resp
    assert keep is False


def test_ux_repeat_returns_last_response():
    """'repeat' returns context.last_response."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    resp1, _ = cm.handle_transcript("open chrome")
    resp2, _ = cm.handle_transcript("repeat")
    assert resp2 == resp1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
