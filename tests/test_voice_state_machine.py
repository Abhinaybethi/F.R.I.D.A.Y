"""
Voice state machine unit tests.

Validates the explicit IDLE -> WAKE_DETECTED -> COMMAND_LISTENING ->
PROCESSING -> EXECUTING -> SPEAKING -> IDLE lifecycle used by the runtime.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.voice.state_machine import VoiceState, VoiceStateMachine, _VALID_TRANSITIONS


def test_initial_state_is_idle():
    sm = VoiceStateMachine()
    assert sm.state == VoiceState.IDLE


def test_valid_single_cycle():
    sm = VoiceStateMachine()
    assert sm.transition_to(VoiceState.WAKE_DETECTED)
    assert sm.transition_to(VoiceState.COMMAND_LISTENING)
    assert sm.transition_to(VoiceState.PROCESSING)
    assert sm.transition_to(VoiceState.EXECUTING)
    assert sm.transition_to(VoiceState.SPEAKING)
    assert sm.transition_to(VoiceState.IDLE)
    assert sm.state == VoiceState.IDLE


def test_invalid_transition_is_ignored():
    sm = VoiceStateMachine()
    # IDLE may only go to WAKE_DETECTED — PROCESSING must be rejected.
    assert not sm.transition_to(VoiceState.PROCESSING)
    assert sm.state == VoiceState.IDLE
    # COMMAND_LISTENING -> SPEAKING is not valid either.
    assert sm.transition_to(VoiceState.WAKE_DETECTED)
    assert sm.transition_to(VoiceState.COMMAND_LISTENING)
    assert not sm.transition_to(VoiceState.SPEAKING)
    assert sm.state == VoiceState.COMMAND_LISTENING


def test_same_state_is_noop():
    sm = VoiceStateMachine()
    assert not sm.transition_to(VoiceState.IDLE)
    assert sm.transitions == []


def test_observer_fires_and_transitions_logged():
    seen = []
    sm = VoiceStateMachine(observer=lambda s: seen.append(s.name))
    assert sm.transition_to(VoiceState.WAKE_DETECTED)
    assert sm.transition_to(VoiceState.PROCESSING)   # allowed from WAKE_DETECTED
    assert sm.transition_to(VoiceState.SPEAKING)      # allowed from PROCESSING
    assert seen == ["WAKE_DETECTED", "PROCESSING", "SPEAKING"]
    assert len(sm.transitions) == 3
    assert sm.transitions[0] == (VoiceState.IDLE, VoiceState.WAKE_DETECTED)


def test_observer_error_does_not_break_machine():
    def bad(_s):
        raise RuntimeError("boom")

    sm = VoiceStateMachine(observer=bad)
    sm.transition_to(VoiceState.WAKE_DETECTED)
    assert sm.state == VoiceState.WAKE_DETECTED, "Observer errors must be swallowed"


def test_reset_returns_to_idle():
    sm = VoiceStateMachine()
    sm.transition_to(VoiceState.WAKE_DETECTED)
    sm.reset()
    assert sm.state == VoiceState.IDLE
    assert sm.transitions == []


def test_graph_has_speaking_to_idle_escape():
    # The lifecycle MUST be escapable back to IDLE from SPEAKING and PROCESSING
    # directly (e.g. hard stop) without deadlock.
    assert VoiceState.IDLE in _VALID_TRANSITIONS[VoiceState.SPEAKING]
    assert VoiceState.IDLE in _VALID_TRANSITIONS[VoiceState.PROCESSING]
    assert VoiceState.IDLE in _VALID_TRANSITIONS[VoiceState.EXECUTING]