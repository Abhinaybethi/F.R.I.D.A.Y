"""
UNIT TEST — Failure Mode Recovery Suite
========================================
Tests fail-closed recovery behavior for Ollama offline, malformed JSON,
tool exceptions, verification failure, confirmation rejection, and step failure.
No Ollama required. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.models import Action, Intent
from friday.reasoning.interface import Reasoner
from friday.planning.context_resolver import ShortTermContext
from friday.verification.models import ExecutionStatus, VerificationStatus, FinalStatus
from friday.tools import registry

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def test_ollama_offline_recovery():
    """When Ollama is unavailable, unknown transcripts fail closed to safe error message."""
    class OfflineReasoner(Reasoner):
        def request(self, transcript: str, context: ShortTermContext) -> dict:
            raise RuntimeError("Ollama connection refused")
        def is_available(self) -> bool:
            return False
        def health(self) -> str:
            return "offline"
        def close(self):
            pass

    cm = ConversationManager(dry_run=True, reasoner=OfflineReasoner(), permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("unrecognized command text 123")
    assert "didn't understand" in resp.lower() or "sorry" in resp.lower()
    assert keep is True
    assert cm.state == ConversationState.LISTENING


def test_malformed_llm_json_recovery():
    """When Ollama returns malformed JSON, system fails closed to safe error message."""
    class BadJsonReasoner(Reasoner):
        def request(self, transcript: str, context: ShortTermContext) -> dict:
            return {"type": "unknown", "raw": "invalid_json"}
        def is_available(self) -> bool:
            return True
        def health(self) -> str:
            return "ok"
        def close(self):
            pass

    cm = ConversationManager(dry_run=True, reasoner=BadJsonReasoner(), permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("unrecognized command text 123")
    assert "didn't understand" in resp.lower() or "sorry" in resp.lower()
    assert cm.state == ConversationState.LISTENING


def test_tool_execution_exception_recovery():
    """When tool execution handler throws exception, registry returns FAILED status."""
    intent = Intent(action=Action.OPEN_APP, target="unknown_app_99999", confidence=0.95)
    outcome = registry.execute(intent, dry_run=True, permissions=_ALL_ENABLED)
    assert outcome.execution.status == ExecutionStatus.FAILED
    assert outcome.verification.status == VerificationStatus.SKIPPED
    assert outcome.final_status == FinalStatus.FAILED
    assert outcome.is_success is False


def test_confirmation_rejection_recovery():
    """Rejecting confirmation with 'no' cancels pending intent and resets state."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    # Trigger confirmation
    cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    # Reject
    resp, keep = cm.handle_transcript("no")
    assert cm.state == ConversationState.LISTENING
    assert "Cancelled" in resp
    assert cm.context.pending_intent is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
