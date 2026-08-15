from unittest.mock import patch
import os
import sys

# Ensure friday is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState

def test_multi_step_commands():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()

        # Test 1: Single command remains unchanged
        resp, keep = cm.handle_transcript("open chrome")
        assert keep
        assert "Would open" in resp or "Opening" in resp
        assert cm.context.current_plan is None

        # Test 2: Two step command
        resp, keep = cm.handle_transcript("open chrome and search for python tutorials")
        assert keep
        assert "Would open" in resp or "Opening" in resp
        assert "Would search" in resp or "Searching" in resp
        assert cm.context.current_plan is None # Completed

        # Test 3: Plan with confirmation
        resp, keep = cm.handle_transcript("open youtube and close vscode")
        assert keep
        assert "Would open" in resp or "Opening" in resp
        assert "Do you want me to close" in resp
        assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
        assert cm.context.current_plan is not None

        # Confirm
        resp, keep = cm.handle_transcript("yes")
        assert keep
        assert "Would close" in resp or "Closing" in resp
        assert cm.context.current_plan is None # Completed

        # Test 4: Cancel a plan
        resp, keep = cm.handle_transcript("open youtube and close vscode")
        assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
        resp, keep = cm.handle_transcript("cancel")
        assert keep
        assert "Cancelled" in resp
        assert cm.context.current_plan is None

        # Test 5: Context aware command
        cm.handle_transcript("search for python tutorials")
        assert cm.context.last_search_query == "python tutorials"
        resp, keep = cm.handle_transcript("search for java instead")
        assert "java" in resp.lower()

        # Test 6: Context aware search result opening & empty list rejection
        resp, keep = cm.handle_transcript("open the first result")
        assert "Would open" in resp or "Opening" in resp

        # Reset tool result and search results to verify empty list rejection
        cm.context.last_tool_result = None
        cm.context.last_search_results = []
        resp, keep = cm.handle_transcript("open the first result")
        assert "I don't have a result list" in resp

        print("ALL MULTI-STEP COMMAND TESTS PASSED")

if __name__ == "__main__":
    test_multi_step_commands()
