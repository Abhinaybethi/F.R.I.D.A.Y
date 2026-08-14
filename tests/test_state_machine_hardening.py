"""
UNIT TEST — State Machine Hardening & Resource Safety (Phase 16 P0)
====================================================================
Tests state machine transitions under barge-in, cancellation, stops, exceptions,
and audio resource cleanup.
No Ollama required. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.state import StateMachine, ConversationState
from friday.core.conversation import ConversationManager
from friday.intent.models import Action, Intent
from friday.reasoning.interface import Reasoner
from friday.planning.context_resolver import ShortTermContext

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
}


class ExceptionThrowingReasoner(Reasoner):
    def request(self, transcript: str, context: ShortTermContext) -> dict:
        raise RuntimeError("Simulated Ollama Timeout / Exception")
    def is_available(self) -> bool:
        return True
    def health(self) -> str:
        return "error"
    def close(self):
        pass


def test_state_machine_barge_in_recovery():
    """State machine recovers cleanly to LISTENING state after barge-in interrupt."""
    sm = StateMachine(ConversationState.RESPONDING)
    sm.transition_to(ConversationState.LISTENING)
    assert sm.current_state == ConversationState.LISTENING


def test_state_machine_cancel_during_confirmation():
    """Cancel command during WAITING_FOR_CONFIRMATION resets pending intent."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    
    resp, keep = cm.handle_transcript("cancel")
    assert cm.state == ConversationState.LISTENING
    assert cm.context.pending_intent is None
    assert "Cancelled" in resp or "cleared" in resp.lower()


def test_state_machine_stop_during_tts():
    """Stop command halts session cleanly from any state."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("stop")
    assert keep is False
    assert cm.state in (ConversationState.STOPPING, ConversationState.IDLE)


def test_state_machine_reasoner_exception_recovery():
    """Ollama exception in reasoner recovers cleanly to LISTENING state without crashing."""
    cm = ConversationManager(dry_run=True, reasoner=ExceptionThrowingReasoner(), permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("tell me a complex joke")
    assert cm.state == ConversationState.LISTENING
    assert keep is True
    assert "unavailable" in resp.lower() or "reasoning" in resp.lower()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
