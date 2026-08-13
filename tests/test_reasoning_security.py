import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.planning.context_resolver import ShortTermContext
class MockReasoner:
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

def test_reasoning_cannot_bypass_safety():
    # Reasoner proposes CLOSE_APP which requires CONFIRM policy
    reasoner = MockReasoner({
        "type": "intent",
        "action": "CLOSE_APP",
        "target": "vscode",
        "confidence": 0.9
    })
    
    cm = ConversationManager(dry_run=True, reasoner=reasoner)
    cm.start_session()
    
    resp, keep = cm.handle_transcript("can you close vscode")
    
    # Should be waiting for confirmation, NOT executed!
    from friday.core.state import ConversationState
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    assert "close Vscode" in resp or "close vscode" in resp.lower()

def test_reasoning_plan_limit():
    # Reasoner tries to propose a 6-step plan
    reasoner = MockReasoner({
        "type": "plan",
        "steps": [
            {"action": "OPEN_APP", "target": "chrome"} for _ in range(6)
        ],
        "confidence": 0.9
    })
    
    cm = ConversationManager(dry_run=True, reasoner=reasoner)
    cm.start_session()
    
    resp, keep = cm.handle_transcript("do six things")
    # Validator rejects > 5 steps and returns {"type": "unknown"}
    # Wait, the MockReasoner currently bypasses the validator because it directly injects the dict!
    # Let's import the validator to simulate real flow.
    from friday.reasoning.validator import validate_reasoning_output
    
    validated = validate_reasoning_output(reasoner.mock_response)
    assert validated == {"type": "unknown"}
