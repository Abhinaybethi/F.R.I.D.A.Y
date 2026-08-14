import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.reasoning.interface import Reasoner
from friday.planning.context_resolver import ShortTermContext

class MockReasoner(Reasoner):
    def __init__(self, response: dict, available: bool = True):
        self.mock_response = response
        self.mock_available = available
        self.called = False
        
    def is_available(self) -> bool:
        return self.mock_available
        
    def health(self) -> str:
        return "mock"
        
    def request(self, transcript: str, context: ShortTermContext) -> dict:
        self.called = True
        return self.mock_response
        
    def close(self):
        pass

def test_router_deterministic_priority():
    reasoner = MockReasoner({"type": "response", "text": "This should not be called."})
    cm = ConversationManager(dry_run=True, reasoner=reasoner)
    cm.start_session()
    
    # "open chrome" is deterministic and known
    resp, keep = cm.handle_transcript("open chrome")
    assert not reasoner.called
    assert "Would open Chrome" in resp or "Opening Chrome" in resp

def test_router_reasoner_fallback():
    reasoner = MockReasoner({"type": "response", "text": "Sure, I can help with that."})
    cm = ConversationManager(dry_run=True, reasoner=reasoner)
    cm.start_session()
    
    # "explain quantum computing" is not recognized deterministically
    resp, keep = cm.handle_transcript("explain quantum computing")
    assert reasoner.called
    assert resp == "Sure, I can help with that."

def test_reasoner_unavailable_fallback():
    reasoner = MockReasoner({"type": "response", "text": "This should not be called."}, available=False)
    cm = ConversationManager(dry_run=True, reasoner=reasoner)
    cm.start_session()
    
    resp, keep = cm.handle_transcript("explain quantum computing")
    assert not reasoner.called
    assert "understand" in resp.lower()

def test_reasoner_returns_intent():
    reasoner = MockReasoner({
        "type": "intent",
        "action": "OPEN_APP",
        "target": "chrome",
        "confidence": 0.9
    })
    cm = ConversationManager(dry_run=True, reasoner=reasoner)
    cm.start_session()
    
    resp, keep = cm.handle_transcript("explain quantum computing")
    assert reasoner.called
    assert "Would open Chrome" in resp or "Opening Chrome" in resp or "Opening" in resp

def test_reasoner_returns_plan():
    reasoner = MockReasoner({
        "type": "plan",
        "steps": [
            {"action": "OPEN_APP", "target": "chrome"},
            {"action": "SEARCH_WEB", "target": "python"}
        ],
        "confidence": 0.9
    })
    cm = ConversationManager(dry_run=True, reasoner=reasoner)
    cm.start_session()
    
    resp, keep = cm.handle_transcript("I need you to run a complex plan")
    assert reasoner.called
    assert "Would open Chrome" in resp or "Opening Chrome" in resp or "Opening" in resp
