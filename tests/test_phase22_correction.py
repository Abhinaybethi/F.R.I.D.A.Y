"""
UNIT TEST — Phase 22 Conversational Correction Handler
======================================================
Tests conversational correction logic ("no, I meant X") in ConversationManager.
"""
from friday.core.conversation import ConversationManager


def test_conversational_correction_open_app():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()

    # Turn 1: open notepad
    resp1, keep1 = cm.handle_transcript("open notepad")
    assert keep1
    assert "Would open" in resp1 or "Opening" in resp1

    # Turn 2: no, I meant chrome
    resp2, keep2 = cm.handle_transcript("no, I meant chrome")
    assert keep2
    assert "chrome" in resp2.lower()
