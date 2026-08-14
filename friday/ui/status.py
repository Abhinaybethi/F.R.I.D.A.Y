"""
Desktop Assistant Status Engine for F.R.I.D.A.Y. Phase 13 (P1).

Provides clean visual status indicators for assistant state machine transitions.
"""
from typing import Union
from friday.core.state import ConversationState


class AssistantStatus:
    IDLE = "[IDLE]"
    LISTENING = "[LISTENING]"
    PROCESSING = "[PROCESSING]"
    EXECUTING = "[EXECUTING]"
    SPEAKING = "[SPEAKING]"
    CONFIRMATION = "[CONFIRMATION REQUIRED]"
    STOPPING = "[STOPPING]"


def get_status_text(state: Union[ConversationState, str]) -> str:
    """Return formatted status text for current ConversationState."""
    state_str = state.name if isinstance(state, ConversationState) else str(state).upper()

    if state_str == "LISTENING":
        return AssistantStatus.LISTENING
    elif state_str == "PROCESSING":
        return AssistantStatus.PROCESSING
    elif state_str == "EXECUTING":
        return AssistantStatus.EXECUTING
    elif state_str == "RESPONDING":
        return AssistantStatus.SPEAKING
    elif state_str == "WAITING_FOR_CONFIRMATION":
        return AssistantStatus.CONFIRMATION
    elif state_str == "STOPPING":
        return AssistantStatus.STOPPING
    else:
        return AssistantStatus.IDLE
