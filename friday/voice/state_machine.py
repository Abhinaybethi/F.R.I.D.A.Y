"""
Explicit voice interaction state machine.

Voice lifecycle (wake-gated runtime):

    IDLE               continuously listen ONLY for the wake word; any non-wake
                       speech is ignored and never reaches the assistant.
    WAKE_DETECTED      wake phrase recognised; command extraction begins.
    COMMAND_LISTENING  bare wake word heard — listening for the command within
                       a bounded command window. Also the resting state during
                       an ACTIVE session (no wake word needed per command).
    PROCESSING         clean command sent into the canonical assistant pipeline.
    EXECUTING          deterministic action / multi-step plan being executed.
    SPEAKING           speaking the response (TTS). Mic input is not processed.
    IDLE               back to standby (only after session timeout / exit).

While a voice session is active the lifecycle loops:

    COMMAND_LISTENING -> PROCESSING -> EXECUTING -> SPEAKING -> COMMAND_LISTENING

and returns to wake-word IDLE only when the session expires or the user says
goodbye / end session.

The state machine is inert by itself: it only records/logs the current state
and fires an optional observer callback so callers and tests can assert exact
transitions.
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class VoiceState(Enum):
    IDLE = auto()
    WAKE_DETECTED = auto()
    COMMAND_LISTENING = auto()
    PROCESSING = auto()
    EXECUTING = auto()
    SPEAKING = auto()


# Valid progressions through the voice lifecycle.
_VALID_TRANSITIONS: dict[VoiceState, tuple[VoiceState, ...]] = {
    VoiceState.IDLE: (VoiceState.WAKE_DETECTED,),
    VoiceState.WAKE_DETECTED: (VoiceState.COMMAND_LISTENING, VoiceState.PROCESSING, VoiceState.IDLE),
    VoiceState.COMMAND_LISTENING: (VoiceState.PROCESSING, VoiceState.IDLE),
    VoiceState.PROCESSING: (VoiceState.EXECUTING, VoiceState.SPEAKING, VoiceState.IDLE),
    VoiceState.EXECUTING: (VoiceState.SPEAKING, VoiceState.IDLE),
    VoiceState.SPEAKING: (VoiceState.IDLE, VoiceState.COMMAND_LISTENING),
}


@dataclass
class VoiceStateMachine:
    """Small, testable state holder with transition logging + observer hook."""
    current_state: VoiceState = VoiceState.IDLE
    transitions: list = field(default_factory=list)
    observer: Optional[Callable[[VoiceState], None]] = None
    _max_history: int = 50

    def set_observer(self, observer: Optional[Callable[[VoiceState], None]]):
        self.observer = observer

    @property
    def state(self) -> VoiceState:
        return self.current_state

    def transition_to(self, new_state: VoiceState) -> bool:
        """Move to ``new_state``. Non-valid transitions are ignored (no crash)."""
        if new_state == self.current_state:
            return False
        allowed = _VALID_TRANSITIONS.get(self.current_state, ())
        if new_state not in allowed:
            logger.debug(
                "[VOICE_STATE] Ignoring invalid transition %s -> %s",
                self.current_state.name, new_state.name,
            )
            return False
        previous = self.current_state
        self.current_state = new_state
        self.transitions.append((previous, new_state))
        if len(self.transitions) > self._max_history:
            self.transitions.pop(0)
        logger.info("[VOICE_STATE] %s", new_state.name)
        if self.observer:
            try:
                self.observer(new_state)
            except Exception as e:  # observer must never break the voice loop
                logger.warning("[VOICE_STATE] Observer error: %s", e)
        return True

    def reset(self):
        self.current_state = VoiceState.IDLE
        self.transitions.clear()