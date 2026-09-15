"""
Active voice session + contextual memory tests.

Covers the wake-gated voice session contract (spec sections 1-28):

  A. Wake word starts an active session; subsequent commands need no wake word.
  B. Wake + command in one transcript -> wake stripped, command executed.
  C. Bare wake word -> "Yes?" acknowledgment (two-stage command capture).
  D. A second / third command within the session executes hands-free.
  E. Inactivity timeout expires the session -> wake-word mode required again.
  F. Every processed interaction refreshes the inactivity timer.
  G. "goodbye" ends the session and stops the app; "go to sleep" / "end
     session" only end the session while the app keeps running.
  H. "play it" resolves to the previous media query across turns.
  I. "play the second one" resolves to the second search result.
  J. "next video" advances honestly (or answers truthfully, never fabricates).
  K. Search context is reused across turns ("search again" / "same thing").
  L. The reasoner receives compact structured context, not a history blob.
  M. Ephemeral context is cleared on expiry; nothing leaks into the next week.
  N. Ambiguous requests defer to the reasoner clarification path.
  O. Text and voice share ONE session owner living in friday.core (not voice).
  P. Multi-step memory updates: current_media rolls into previous_media.
  Q. A failed step never fabricates memory (no false media/search).
  R. conversation_timeout_seconds is validated/clamped by the config layer.
  S. The voice state machine allows SPEAKING -> COMMAND_LISTENING while a
     session is active.

Hermetic: mic / STT / TTS / reasoner / server are stubs (same pattern as
tests/test_voice_action_execution.py). Dry-run tools never touch the network.
"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import friday.core.assistant as assistant_mod
from friday.core.conversation import ConversationManager
from friday.core.session import ConversationSession
from friday.intent.classifier import RequestClass, classify
from friday.utils.config_validator import validate_config

ROOT = Path(__file__).resolve().parents[1]


class RecordingReasoner:
    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "test-model")
        self.base_url = kwargs.get("base_url", "http://test:1")
        self.endpoint = kwargs.get("endpoint", "http://test:1")
        self.timeout = kwargs.get("timeout", 30)
        self.requests = []
        self.modes = []
        self.contexts = []

    def is_available(self):
        return True

    def health(self):
        return "test reasoner reachable"

    def close(self):
        pass

    def request(self, transcript, context, mode="action"):
        self.requests.append(transcript)
        self.modes.append(mode)
        self.contexts.append(context)
        return {"type": "response", "text": f"You asked about: {transcript}", "confidence": 0.9}


class FakeServerManager:
    def __init__(self, **kwargs):
        self.start_calls = 0
        self.stop_calls = 0
        self.owned_flag = False

    def is_owned(self):
        return self.owned_flag

    def start(self):
        self.start_calls += 1
        return True

    def stop(self):
        self.stop_calls += 1

    def health(self):
        return "test"

    def is_already_running(self):
        return False


class StubTTS:
    def __init__(self, **kwargs):
        self.spoken = []
        self.stopped = False
        self._is_speaking = False

    def warmup(self):
        pass

    def speak(self, text):
        self.spoken.append(text)

    def stop(self):
        self.stopped = True
        self._is_speaking = False

    def is_speaking(self):
        return self._is_speaking


class StubSessionManager:
    def __init__(self, **kwargs):
        self.transcripts = []
        self.started = False
        self.stopped = False

    def set_script(self, transcripts):
        self.transcripts = list(transcripts)

    def start_session(self):
        self.started = True
        return self

    def stop_session(self):
        self.stopped = True

    def __enter__(self):
        return self.start_session()

    def __exit__(self, *args):
        self.stop_session()
        return False

    def listen_once(self):
        if not self.transcripts:
            return ""
        return self.transcripts.pop(0)


class GateWakeWord:
    """Mirrors the real wake-word gate: non-wake transcripts are consumed/dropped."""

    def __init__(self, session, wake_word="friday"):
        self.session = session
        self.wake_word = wake_word

    def wait_for_wake_word(self):
        while True:
            text = self.session.listen_once()
            if not text:
                return ""
            if self.wake_word in text.lower():
                return text


class _FakeProc:
    def __init__(self, name):
        self.info = {"name": name}


class Recorder:
    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        return self.fn(*args, **kwargs)


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    monkeypatch.setattr(assistant_mod, "TextToSpeech", StubTTS)
    monkeypatch.setattr(assistant_mod, "VoiceSessionManager", StubSessionManager)
    monkeypatch.setattr(assistant_mod, "WakeWordListener", GateWakeWord)
    monkeypatch.setattr(assistant_mod, "LlamaCppReasoner", RecordingReasoner)
    monkeypatch.setattr(assistant_mod, "LlamaCppServerManager", FakeServerManager)
    import psutil
    monkeypatch.setattr(psutil, "process_iter", lambda *a, **k: iter([_FakeProc("chrome.exe")]))


@pytest.fixture()
def tools_spy(monkeypatch):
    spy = {"startfile": [], "webbrowser_open": []}
    monkeypatch.setattr(
        "friday.tools.apps.os.startfile",
        lambda *a, **k: spy["startfile"].append(a[0]) or None,
    )
    monkeypatch.setattr(
        "friday.tools.browser.webbrowser.open",
        lambda *a, **k: spy["webbrowser_open"].append(a[0]) or True,
    )
    return spy


@pytest.fixture()
def run_voice(monkeypatch):
    """Build a stub-backed Friday; ``gated=True`` enables the wake gate."""
    def _run(transcripts, gated=False, observer=None):
        friday = assistant_mod.Friday(config_path=str(ROOT / "config.yaml"))
        reasoner = RecordingReasoner()
        friday.reasoner = reasoner
        friday.conversation_manager.reasoner = reasoner
        friday._wake_word_required = gated
        friday.session_manager.set_script(transcripts)
        handle_spy = Recorder(friday.conversation_manager.handle_transcript)
        friday.conversation_manager.handle_transcript = handle_spy
        if observer is not None:
            friday.voice_state.set_observer(observer)
        friday.run()
        return friday, reasoner, friday.tts, handle_spy

    return _run


def _cm(reasoner=None, timeout=300):
    cm = ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=reasoner or RecordingReasoner(),
        conversation_timeout_seconds=timeout,
    )
    cm.start_session()
    return cm


def _count(lst, needle):
    return sum(1 for s in lst if needle in s)


# ==============================================================================
# A-F: Session lifecycle & run-loop gating
# ==============================================================================

def test_session_object_lifecycle_and_timeout_floor():
    s = ConversationSession()
    assert s.timeout_seconds == 300, "Default inactivity timeout must be 300s"
    assert ConversationSession(timeout_seconds=5).timeout_seconds == 30, "Floor is 30s"
    assert not s.is_active()
    s.start(now=1000.0)
    assert s.is_active(now=1000.0)
    assert s.is_active(now=1299.0), "Still inside the inactivity window"
    assert not s.is_active(now=1300.0), "Expired after the inactivity window"
    s.touch(now=1500.0)
    assert s.is_active(now=1500.0), "touch() must refresh the timer"
    assert s.remaining_seconds(now=1500.0) == pytest.approx(300.0)
    s.end()
    assert not s.is_active(now=0.0)


def test_wake_activates_session_then_commands_are_hands_free(run_voice, tools_spy):
    friday, reasoner, tts, handle_spy = run_voice(
        ["hey friday open chrome", "open youtube", "friday goodbye"], gated=True
    )
    # First command wakes + executes; second command needs NO wake word; final
    # goodbye still stops the app (wake prefix stripped by the session branch).
    assert handle_spy.calls == [("open chrome",), ("open youtube",), ("goodbye",)]
    assert tools_spy["startfile"] == [r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
    assert tools_spy["webbrowser_open"] == ["https://www.youtube.com"]
    assert len(reasoner.requests) == 0


def test_bare_wake_yes_ack_then_hands_free(run_voice, tools_spy):
    friday, reasoner, tts, handle_spy = run_voice(
        ["friday", "open chrome", "open youtube", "friday goodbye"], gated=True
    )
    assert handle_spy.calls == [("open chrome",), ("open youtube",), ("goodbye",)]
    assert "Yes?" in tts.spoken, "Bare wake word must be acknowledged"
    assert len(tools_spy["startfile"]) == 1
    assert len(reasoner.requests) == 0


def test_wake_repeated_mid_session_is_acknowledged(run_voice, tools_spy):
    friday, reasoner, tts, handle_spy = run_voice(
        ["friday", "open chrome", "friday", "open youtube", "friday goodbye"], gated=True
    )
    assert handle_spy.calls == [("open chrome",), ("open youtube",), ("goodbye",)], (
        "A bare wake word mid-session must not become a command"
    )
    assert _count(tts.spoken, "Yes?") >= 2
    assert len(tools_spy["startfile"]) == 1
    assert len(reasoner.requests) == 0


def test_expired_session_returns_to_wake_gate(run_voice, tools_spy):
    # Backdate the shared session so it has already timed out before run().
    friday = assistant_mod.Friday(config_path=str(ROOT / "config.yaml"))
    reasoner = RecordingReasoner()
    friday.reasoner = reasoner
    friday.conversation_manager.reasoner = reasoner
    friday._wake_word_required = True
    friday.conversation_manager.session.start()
    friday.conversation_manager.session.touch(now=time.time() - 99999)
    friday.session_manager.set_script(
        ["open chrome", "friday open youtube", "friday goodbye"]
    )
    handle_spy = Recorder(friday.conversation_manager.handle_transcript)
    friday.conversation_manager.handle_transcript = handle_spy
    friday.run()
    # The expired session must NOT leak: "open chrome" is consumed by the wake
    # gate, only the wake-bearing command reaches the assistant.
    assert handle_spy.calls == [("open youtube",), ("goodbye",)]
    assert tools_spy["startfile"] == [], "No-wake command must never execute after expiry"
    assert tools_spy["webbrowser_open"] == ["https://www.youtube.com"]


def test_goodbye_ends_session_and_stops(run_voice):
    friday, reasoner, tts, handle_spy = run_voice(
        ["friday open chrome", "friday goodbye"], gated=True
    )
    assert handle_spy.calls == [("open chrome",), ("goodbye",)]
    assert not friday.conversation_manager.session.is_active()

def test_interaction_refreshes_timer(cm_import=None):
    cm = _cm(timeout=180)
    cm.handle_transcript("play kalyani song on youtube")
    cm.session.touch(now=time.time() - 99999)
    assert not cm.session.is_active()
    # A new interaction is processed; on the conversation layer the session
    # itself stays ended (reactivation is the voice run-loop's job), but
    # touch() must have refreshed the timestamp for the NEW window.
    cm.handle_transcript("open chrome")
    assert cm.session.last_interaction_at > time.time() - 60
    assert not cm.session.is_active(), "Re-activation happens on the next wake word"


# ==============================================================================
# G-I: Session-end voice commands & cross-turn reference resolution
# ==============================================================================

def test_go_to_sleep_ends_session_keeps_running():
    cm = _cm()
    resp, keep = cm.handle_transcript("go to sleep")
    assert keep is True, "go to sleep must NOT stop the app"
    assert not cm.session.is_active()
    for phrase in ("stop listening", "end session", "go idle", "sleep"):
        cm.session.start()
        _, keep2 = cm.handle_transcript(phrase)
        assert keep2 is True
        assert not cm.session.is_active()
    cm.session.start()
    resp3, keep3 = cm.handle_transcript("goodbye")
    assert keep3 is False, "goodbye must fully stop the app"
    assert not cm.session.is_active()


def test_play_it_resolves_across_turns():
    reasoner = RecordingReasoner()
    cm = _cm(reasoner)
    cm.handle_transcript("play kalyani song on youtube")
    resp2, _ = cm.handle_transcript("play it")
    assert "kalyani song" in resp2.lower()
    assert reasoner.requests == [], "'play it' must use structured memory, not the reasoner"


def test_play_second_one_uses_search_results():
    cm = _cm()
    cm.handle_transcript("search for python tutorials on google")
    resp, _ = cm.handle_transcript("play the second one")
    assert "example.com/2" in resp.lower() or "example.com/2" in cm.context.last_search_query.lower(), (
        "'play the second one' must resolve to the #2 search result"
    )


def test_next_video_is_truthful_without_context():
    cm = _cm()
    resp, _ = cm.handle_transcript("next video")
    assert "enough context" in resp.lower(), "No search/media context -> honest clarification"
    assert "python" not in resp.lower()


def test_next_video_replays_active_query_when_position_unknown():
    cm = _cm()
    cm.handle_transcript("play kalyani song on youtube")
    resp, _ = cm.handle_transcript("next video")
    assert "kalyani song" in resp.lower(), (
        "Without a located current video the resolver must replay the active query, not fabricate"
    )


def test_previous_video_uses_previous_media():
    cm = _cm()
    cm.handle_transcript("play phi discourse engage on youtube")
    cm.handle_transcript("play neetha song on youtube")
    # previous_media should hold the first video after the second played.
    assert cm.context.previous_media
    resp, _ = cm.handle_transcript("previous video")
    assert "phi" in resp.lower() and "discourse" in resp.lower(), (
        "'previous video' should roll back to the previously played media"
    )


def test_search_again_reuses_last_query():
    cm = _cm()
    cm.handle_transcript("search for machine learning on google")
    resp, _ = cm.handle_transcript("search again")
    assert "machine learning" in resp.lower(), "'search again' must reuse the last query"
    assert "example.com" not in resp.lower()


def test_conversation_turn_increments():
    cm = _cm()
    cm.handle_transcript("open chrome")
    cm.handle_transcript("open youtube")
    cm.handle_transcript("play kalyani song on youtube")
    assert cm.context.conversation_turn == 3


def test_memory_questions_answered_from_structured_context():
    reasoner = RecordingReasoner()
    cm = _cm(reasoner)
    cm.handle_transcript("play kalyani song on youtube")
    resp_watching, _ = cm.handle_transcript("what are we watching")
    assert "kalyani song" in resp_watching.lower()
    resp_did, _ = cm.handle_transcript("what did you just do")
    assert "kalyani song" in resp_did.lower() and "played" in resp_did.lower()
    assert reasoner.requests == [], "Memory questions must be answered without the reasoner"


def test_reasoner_receives_compact_structured_context():
    reasoner = RecordingReasoner()
    cm = _cm(reasoner)
    cm.handle_transcript("open youtube")
    cm.handle_transcript("play kalyani song on youtube")
    resp, _ = cm.handle_transcript("what is a class in java")
    assert reasoner.requests == ["what is a class in java"]
    assert reasoner.modes == ["chat"]
    ctx = reasoner.contexts[0]
    assert ctx.active_website == "youtube"
    assert ctx.last_action_info is not None and ctx.last_action_info["type"] == "PLAY_VIDEO"
    assert ctx.current_media is not None and ctx.current_media["query"] == "kalyani song"
    assert ctx.conversation_turn == 2
    assert "java" in resp.lower()


def test_ambiguous_request_deferf_to_clarification():
    class ClarifyReasoner:
        def is_available(self):
            return True
        def request(self, transcript, context, mode="action"):
            return {"type": "clarification", "question": "Which window did you mean?"}
        def health(self):
            return "ok"
        def close(self):
            pass
    cm = _cm(ClarifyReasoner())
    resp, _ = cm.handle_transcript("clean my computer screen")
    assert "which window" in resp.lower(), "Ambiguous requests must surface the clarification"


def test_ephemeral_context_cleared_on_expiry_media_retained():
    cm = _cm(timeout=180)
    cm.handle_transcript("play kalyani song on youtube")
    cm.handle_transcript("open chrome")
    assert cm.context.active_goal is not None or cm.context.current_plan is not None or cm.context.pending_intent is not None
    # Simulate inactivity timeout.
    cm.session.touch(now=time.time() - 99999)
    resp, _ = cm.handle_transcript("open youtube")
    assert not cm.session.is_active()
    assert cm.context.pending_intent is None
    assert cm.context.current_plan is None
    assert not cm.context.pending_reference
    assert cm.context.active_media == "kalyani song", "last media must be retained for optional reuse"
    assert cm.context.last_search_query == "kalyani song"


def test_failed_plan_step_does_not_fabricate_memory():
    class BadPlanReasoner:
        def is_available(self):
            return True
        def request(self, transcript, context, mode="action"):
            return {
                "type": "plan",
                "steps": [{"action": "NOT_REAL_ACTION", "target": "does not exist"}],
                "confidence": 0.99,
            }
        def health(self):
            return "ok"
        def close(self):
            pass
    cm = _cm(BadPlanReasoner())
    cm.handle_transcript("play kalyani song on youtube")
    before_media = dict(cm.context.current_media)
    before_action = dict(cm.context.last_action)
    resp, _ = cm.handle_transcript("what is the best way to cook pasta")
    # The reasoner's plan fails validation — no tool runs, memory must not change.
    assert "unknown action" in resp.lower()
    assert cm.context.current_media == before_media, "No false media memory"
    assert cm.context.last_action == before_action, "Last successful action preserved"


def test_multistep_media_rolls_into_previous():
    cm = _cm()
    cm.handle_transcript("play phi discourse engage on youtube")
    cm.handle_transcript("play neetha song on youtube")
    assert cm.context.current_media["query"] == "neetha song"
    assert cm.context.previous_media[-1]["query"] == "phi discourse engage"
    cm.handle_transcript("play classical mix on youtube")
    assert cm.context.previous_media[-1]["query"] == "neetha song", "old current rolls into previous"


# ==============================================================================
# O-R-S: shared owner, config validation, state machine
# ==============================================================================

def test_session_owner_lives_in_core_not_voice_layer():
    # The single clean owner is friday.core.session.ConversationSession.
    import friday.core.session as session_mod
    friday = assistant_mod.Friday(config_path=str(ROOT / "config.yaml"))
    assert isinstance(friday.conversation_manager.session, session_mod.ConversationSession)
    friday.run  # nothing to assert further — the shared owner is the same object used by text+voice


def test_config_validator_defaults_and_clamps():
    ok, sanitized, msgs = validate_config({})
    assert sanitized["voice"]["conversation_timeout_seconds"] == 300
    ok2, s2, m2 = validate_config({"voice": {"conversation_timeout_seconds": 50}})
    assert s2["voice"]["conversation_timeout_seconds"] == 180, "Below-range clamped to 180"
    ok3, s3, m3 = validate_config({"voice": {"conversation_timeout_seconds": 99999}})
    assert s3["voice"]["conversation_timeout_seconds"] == 300, "Above-range clamped to 300"
    ok4, s4, m4 = validate_config({"voice": {"conversation_timeout_seconds": "bogus"}})
    assert s4["voice"]["conversation_timeout_seconds"] == 300, "Invalid values default to 300"


def test_state_machine_speaking_returns_to_command_listening():
    from friday.voice.state_machine import VoiceState, VoiceStateMachine
    machine = VoiceStateMachine()
    machine.transition_to(VoiceState.WAKE_DETECTED)
    machine.transition_to(VoiceState.COMMAND_LISTENING)
    machine.transition_to(VoiceState.PROCESSING)
    machine.transition_to(VoiceState.EXECUTING)
    machine.transition_to(VoiceState.SPEAKING)
    assert machine.state == VoiceState.SPEAKING
    # While the session is active the loop returns to command listening.
    machine.transition_to(VoiceState.COMMAND_LISTENING)
    assert machine.state == VoiceState.COMMAND_LISTENING
    machine.transition_to(VoiceState.PROCESSING)
    machine.transition_to(VoiceState.EXECUTING)
    machine.transition_to(VoiceState.SPEAKING)
    # After session expiry it may also go idle.
    machine.transition_to(VoiceState.IDLE)
    assert machine.state == VoiceState.IDLE


def test_session_control_phrases_classified():
    assert classify("go to sleep") == RequestClass.SESSION_CONTROL
    assert classify("end session") == RequestClass.SESSION_CONTROL
    assert classify("next video") == RequestClass.CONTEXT_REFERENCE
    assert classify("play next video") == RequestClass.CONTEXT_REFERENCE