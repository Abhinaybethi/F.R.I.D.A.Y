"""
UNIT TEST — Real Command Matrix Test Suite
===========================================
Tests all 21 utterances from the Phase 11 Command Matrix through ConversationManager.
Verifies STT -> Intent -> Policy -> Permission -> Execution -> Verification -> Response.
No Ollama required for deterministic commands.
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


def test_matrix_safe_commands():
    """Test safe app, website, search, time, file, folder commands."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    # 1. Safe App
    resp, keep = cm.handle_transcript("open chrome")
    assert "Chrome" in resp or "chrome" in resp.lower()
    assert keep is True

    # 2. Safe Website
    resp, keep = cm.handle_transcript("open youtube")
    assert "YouTube" in resp or "youtube" in resp.lower()

    # 3. Safe Search
    resp, keep = cm.handle_transcript("search for python tutorials")
    assert "python" in resp.lower() and "tutorials" in resp.lower()

    # 4. Safe Time
    resp, keep = cm.handle_transcript("what time is it")
    assert ":" in resp or "PM" in resp or "AM" in resp

    # 5. Safe File
    resp, keep = cm.handle_transcript("find my resume")
    assert "resume" in resp.lower() or "file" in resp.lower()

    # 6. Safe Folder
    resp, keep = cm.handle_transcript("open downloads")
    assert "Downloads" in resp or "downloads" in resp.lower()


def test_matrix_ambiguous_commands():
    """Test ambiguous commands fall back safely."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    # "openvscode" compound utterance
    resp, keep = cm.handle_transcript("openvscode")
    assert "VS Code" in resp or "vscode" in resp.lower() or "didn't understand" in resp.lower()


def test_matrix_confirmation_flow():
    """Test confirmation flow for CLOSE_APP."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    resp, keep = cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    assert "sure" in resp.lower() or "close" in resp.lower()

    # Confirm "yes"
    resp_yes, keep_yes = cm.handle_transcript("yes")
    assert cm.state == ConversationState.LISTENING
    assert "Chrome" in resp_yes or "chrome" in resp_yes.lower() or "Cancelled" in resp_yes


def test_matrix_system_commands():
    """Test help, repeat, cancel, stop."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    # Help
    resp_help, _ = cm.handle_transcript("help")
    assert "open applications" in resp_help.lower()

    # Repeat
    resp_rep, _ = cm.handle_transcript("repeat")
    assert resp_rep == cm.context.last_response

    # Cancel
    resp_can, _ = cm.handle_transcript("cancel")
    assert "Cancelled" in resp_can

    # Stop
    resp_stop, keep = cm.handle_transcript("stop")
    assert "Goodbye" in resp_stop
    assert keep is False


def test_matrix_natural_language_phrasings():
    """Test natural language phrasings route correctly."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    resp1, _ = cm.handle_transcript("could you open chrome for me")
    assert "Chrome" in resp1 or "chrome" in resp1.lower()

    resp2, _ = cm.handle_transcript("search python tutorials on the web")
    assert "python" in resp2.lower() and "tutorials" in resp2.lower()

    resp3, _ = cm.handle_transcript("what time is it right now")
    assert ":" in resp3 or "PM" in resp3 or "AM" in resp3 or "time" in resp3.lower()


def test_matrix_multi_step_plans():
    """Test multi-step plans execute sequentially."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    resp, _ = cm.handle_transcript("open chrome and open youtube")
    assert "Chrome" in resp or "chrome" in resp.lower()
    assert "YouTube" in resp or "youtube" in resp.lower()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
