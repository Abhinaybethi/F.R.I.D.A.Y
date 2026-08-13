import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.planning.context_resolver import ShortTermContext
from friday.intent.models import Action

def test_context_passed_to_reasoner(monkeypatch):
    called_context = None
    
    class MockReasoner:
        def is_available(self): return True
        def request(self, transcript, context):
            nonlocal called_context
            called_context = context
            return {"type": "response", "text": "OK"}
            
    cm = ConversationManager(dry_run=True, reasoner=MockReasoner())
    cm.start_session()
    
    # Establish some context first
    cm.context.last_search_query = "python"
    
    cm.handle_transcript("can you actually search for ruby instead")
    
    assert called_context is not None
    assert called_context.last_search_query == "python"
