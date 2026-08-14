"""
UNIT TEST — Anaphora Pronoun & Search Result Indexing (Phase 13 P0)
====================================================================
Tests friday/planning/context_resolver.py.
Ensures "close it" after OPEN_APP(chrome) resolves to "close chrome",
and "open the first result" resolves to OPEN_WEBSITE(url[0]).
No Ollama required. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.intent.models import Action
from friday.core.conversation import ConversationManager


def test_anaphora_pronoun_close_it():
    """'close it' resolves to 'close chrome' when last_target is 'chrome'."""
    ctx = ShortTermContext(last_action=Action.OPEN_APP, last_target="chrome")
    resolved, err = resolve_context("close it", ctx)
    assert err == ""
    assert resolved == "close chrome"


def test_anaphora_pronoun_close_that():
    """'close that' resolves to 'close notepad' when last_target is 'notepad'."""
    ctx = ShortTermContext(last_action=Action.OPEN_APP, last_target="notepad")
    resolved, err = resolve_context("close that", ctx)
    assert err == ""
    assert resolved == "close notepad"


def test_search_result_indexing_open_first():
    """'open the first result' resolves to 'open website <URL>' from search results."""
    results = [{"url": "https://www.python.org", "title": "Python Website"}]
    ctx = ShortTermContext(last_search_query="python", last_search_results=results)
    resolved, err = resolve_context("open the first result", ctx)
    assert err == ""
    assert "https://www.python.org" in resolved


def test_conversation_manager_end_to_end_context_anaphora():
    """ConversationManager resolves 'close it' across turns."""
    cm = ConversationManager(dry_run=True)
    cm.start_session()
    cm.handle_transcript("open chrome")
    # Next turn: close it
    resp, _ = cm.handle_transcript("close it")
    assert "Chrome" in resp or "chrome" in resp.lower() or "sure" in resp.lower()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
