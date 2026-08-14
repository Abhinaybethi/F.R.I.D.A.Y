import sys
import os
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.router import route
from friday.intent.models import Action, Intent
from friday.core.conversation import ConversationManager, ConversationState
from friday.planning.plan_models import PlanState
from friday.utils.logger import request_id_var
from friday.tools import registry
from friday.verification.models import ActionOutcome, FinalStatus

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
}

# --- INCREMENT 1: Request Correlation ---
def test_request_correlation_id_set():
    request_id_var.set("test-id-123")
    assert request_id_var.get() == "test-id-123"
    
    import logging
    from friday.utils.logger import RequestIDFilter
    f = RequestIDFilter()
    r = logging.LogRecord("test", logging.INFO, "path", 1, "msg", (), None)
    f.filter(r)
    assert hasattr(r, "request_id")
    assert r.request_id == "test-id-123"

# --- INCREMENT 2: Conversational Deterministic Routing ---
@pytest.mark.parametrize("transcript", [
    "can you open chrome",
    "please open chrome",
    "could you open chrome for me",
    "would you please open chrome",
    "hey friday please open chrome",
    "open chrome please",
    "kindly open chrome"
])
def test_conversational_deterministic_routing(transcript):
    intent = route(transcript)
    assert intent.action == Action.OPEN_APP
    assert intent.target == "chrome"
    assert intent.confidence >= 0.9  # Should be high enough to not invoke Ollama

def test_malicious_conversational_variants_rejected():
    intent = route("hey friday please rm -rf /")
    assert intent.action == Action.UNKNOWN  # Fallback to reasoner/UNKNOWN

# --- INCREMENT 3: Confirmation Expiry & Stale Protection ---
def test_confirmation_timeout():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    
    # 1. Trigger confirmation
    resp, keep = cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    
    # 2. Simulate time passing (set start time to 31 seconds ago)
    cm.context.confirmation_start_time = time.time() - 31.0
    
    # 3. Say "yes" (stale confirmation)
    with patch("friday.intent.router.route") as mock_route:
        # It should transition back to LISTENING and then process "yes" as a normal command
        mock_route.return_value = Intent(action=Action.UNKNOWN, raw_text="yes")
        # Ensure we don't try to call the real reasoner in tests for this
        cm.reasoner = None 
        resp, keep = cm.handle_transcript("yes")
        
    assert cm.state == ConversationState.LISTENING
    assert cm.context.pending_intent is None
    # We should NOT have executed close chrome
    # It would say "I didn't understand that." since UNKNOWN without reasoner fails policy

# --- INCREMENT 4: Structured Spoken Responses ---
def test_structured_spoken_responses_dry_run():
    intent = Intent(action=Action.OPEN_APP, target="chrome", confidence=1.0)
    outcome: ActionOutcome = registry.execute(intent, dry_run=True, permissions=_ALL_ENABLED)
    
    assert outcome.final_status == FinalStatus.DRY_RUN
    assert outcome.user_message == "[DRY RUN] Would open Chrome."
    assert outcome.spoken_message == "Opening Chrome."
    
    # Test dict-like backwards compat
    assert outcome["spoken_message"] == "Opening Chrome."
    assert outcome.get("spoken_message") == "Opening Chrome."

# --- INCREMENT 5: Reasoner Gating ---
def test_reasoner_gating_bypassed_for_simple_conversational():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    
    # Mock reasoner so we know if it was called
    mock_reasoner = MagicMock()
    mock_reasoner.is_available.return_value = True
    cm.reasoner = mock_reasoner
    
    cm.handle_transcript("could you open chrome for me")
    
    # Assert reasoner was NEVER called
    mock_reasoner.request.assert_not_called()

