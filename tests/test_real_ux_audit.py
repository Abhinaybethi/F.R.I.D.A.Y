"""
UNIT TEST — Real User Experience Audit (Phase 16 P1)
======================================================
Verifies realistic voice conversations for concise, natural spoken responses without
exposing dry-run tags, confidence codes, or raw JSON.
No Ollama required. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager, ConversationState
from friday.response.engine import format_spoken_response
from friday.intent.models import Action

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
}


def test_ux_conversation_1_anaphora_flow():
    """Flow 1: 'Open Chrome' -> 'Close it'."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    
    resp1, _ = cm.handle_transcript("Open Chrome.")
    assert "[DRY RUN]" not in format_spoken_response(resp1)
    
    resp2, _ = cm.handle_transcript("Close it.")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    assert "close" in resp2.lower() or "application" in resp2.lower()


def test_ux_conversation_2_search_indexing():
    """Flow 2: 'Search Python tutorials' -> 'Open the first result'."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    
    resp1, _ = cm.handle_transcript("Search Python tutorials.")
    assert "search" in resp1.lower() or "python" in resp1.lower()
    
    cm.context.last_tool_result = {"results": [{"url": "https://www.python.org"}]}
    resp2, _ = cm.handle_transcript("Open the first result.")
    assert resp2 is not None
    assert "[DRY RUN]" not in format_spoken_response(resp2)


def test_ux_conversation_3_fuzzy_confirm_yes():
    """Flow 3: 'Open grove' -> 'Yes'."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    
    resp1, _ = cm.handle_transcript("Open grove.")
    assert "chrome" in resp1.lower()
    
    resp2, _ = cm.handle_transcript("Yes.")
    assert cm.state == ConversationState.LISTENING
    assert "[DRY RUN]" not in format_spoken_response(resp2)


def test_ux_conversation_4_fuzzy_confirm_no():
    """Flow 4: 'Open grove' -> 'No'."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    
    cm.handle_transcript("Open grove.")
    resp2, _ = cm.handle_transcript("No.")
    assert cm.state == ConversationState.LISTENING
    assert "cancelled" in resp2.lower() or "didn't" in resp2.lower() or "ok" in resp2.lower()


def test_ux_conversation_5_close_cancel():
    """Flow 5: 'Close Chrome' -> 'Cancel'."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    
    cm.handle_transcript("Close Chrome.")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    
    resp2, _ = cm.handle_transcript("Cancel.")
    assert cm.state == ConversationState.LISTENING
    assert "cancelled" in resp2.lower() or "cleared" in resp2.lower()


def test_ux_conversation_6_stop_session():
    """Flow 6: 'Stop'."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    
    resp, keep = cm.handle_transcript("Stop.")
    assert keep is False
    assert cm.state in (ConversationState.STOPPING, ConversationState.IDLE)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
