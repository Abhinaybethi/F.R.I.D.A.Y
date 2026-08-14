"""
UNIT TEST — Desktop Assistant Status Indicator (Phase 13 P1)
=============================================================
Tests friday/ui/status.py state formatting rules.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.ui.status import get_status_text, AssistantStatus
from friday.core.state import ConversationState


def test_status_text_formatting():
    """get_status_text() formats ConversationState correctly."""
    assert get_status_text(ConversationState.IDLE) == AssistantStatus.IDLE
    assert get_status_text(ConversationState.LISTENING) == AssistantStatus.LISTENING
    assert get_status_text(ConversationState.PROCESSING) == AssistantStatus.PROCESSING
    assert get_status_text(ConversationState.EXECUTING) == AssistantStatus.EXECUTING
    assert get_status_text(ConversationState.RESPONDING) == AssistantStatus.SPEAKING
    assert get_status_text(ConversationState.WAITING_FOR_CONFIRMATION) == AssistantStatus.CONFIRMATION


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
