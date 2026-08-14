"""
Conversation State Machine for F.R.I.D.A.Y. v2.

Explicit state enum — no scattered booleans.
"""
from enum import Enum, auto


class ConversationState(Enum):
    IDLE                    = auto()
    LISTENING               = auto()
    PROCESSING              = auto()
    WAITING_FOR_CONFIRMATION = auto()
    EXECUTING               = auto()
    RESPONDING              = auto()
    PAUSED                  = auto()
    STOPPING                = auto()


class StateMachine:
    """
    Validates and manages explicit conversation state transitions.
    """

    def __init__(self, initial_state: ConversationState = ConversationState.IDLE):
        self._state = initial_state

    @property
    def current_state(self) -> ConversationState:
        return self._state

    def transition_to(self, new_state: ConversationState):
        """
        Transition to a new state.
        ANY state can transition to STOPPING.
        """
        if new_state == ConversationState.STOPPING:
            self._state = new_state
            return

        # Allowed transitions
        allowed = {
            ConversationState.IDLE: {ConversationState.LISTENING, ConversationState.PAUSED},
            ConversationState.LISTENING: {ConversationState.PROCESSING, ConversationState.IDLE, ConversationState.PAUSED},
            ConversationState.PAUSED: {ConversationState.LISTENING, ConversationState.IDLE},
            ConversationState.PROCESSING: {
                ConversationState.EXECUTING,
                ConversationState.WAITING_FOR_CONFIRMATION,
                ConversationState.RESPONDING,
            },
            ConversationState.WAITING_FOR_CONFIRMATION: {
                ConversationState.EXECUTING,
                ConversationState.RESPONDING,
                ConversationState.WAITING_FOR_CONFIRMATION,
                ConversationState.LISTENING,
            },
            ConversationState.EXECUTING: {
                ConversationState.RESPONDING, 
                ConversationState.WAITING_FOR_CONFIRMATION
            },
            ConversationState.RESPONDING: {ConversationState.LISTENING, ConversationState.IDLE, ConversationState.PAUSED},
            ConversationState.STOPPING: {ConversationState.IDLE},
        }

        valid_targets = allowed.get(self._state, set())
        if new_state not in valid_targets:
            raise ValueError(f"Invalid state transition: {self._state.name} -> {new_state.name}")

        self._state = new_state
